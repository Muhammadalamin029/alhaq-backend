import base64
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from core.config import settings

logger = logging.getLogger(__name__)

FLW_BASE_URL = "https://api.flutterwave.com/v3"


def derive_3des_key(encryption_key: str) -> bytes:
    """Derive the 24-byte 3DES key from a Flutterwave encryption key.

    Matches the official v3 encryption scheme: MD5 the encryption key,
    then concatenate the last 12 hex chars + first 12 hex chars.
    """
    digest = hashlib.md5(encryption_key.encode("utf-8")).hexdigest()
    return (digest[-12:] + digest[:12]).encode("utf-8")


def encrypt_payload(encryption_key: str, payload: Dict[str, Any]) -> str:
    """3DES-encrypt a card-charge payload for POST /v3/charges?type=card.

    Pure function (no settings access) so it is unit-testable.
    Requires ``pycryptodome`` (``Crypto.Cipher.DES3``).
    """
    from Crypto.Cipher import DES3

    raw = json.dumps(payload, separators=(",", ":"))
    # PKCS#7-style padding to an 8-byte block boundary
    pad_len = 8 - (len(raw.encode("utf-8")) % 8)
    raw += chr(pad_len) * pad_len
    cipher = DES3.new(derive_3des_key(encryption_key), DES3.MODE_ECB)
    return base64.b64encode(cipher.encrypt(raw.encode("utf-8"))).decode("utf-8")


class FlutterwaveService:
    """Flutterwave **v3 Direct API** client (no hosted links, no Inline modal).

    Card charges go through the multi-step direct flow:
      1. ``charge_card``            -> inspect ``meta.authorization.mode``
      2. ``authorize_card``         -> PIN / AVS (same endpoint + ``authorization``)
      3. ``validate_charge``        -> OTP via ``POST /v3/validate-charge``
      4. ``verify_transaction``     -> ``GET /v3/transactions/{id}/verify``

    Amounts are in **Naira major units** (unlike Paystack's kobo).
    Our internal idempotency key is ``tx_ref`` (``LEL_…`` format is kept).
    Never pass raw card fields to logs — the service redacts them on error.
    """

    def __init__(self):
        self.secret_key = settings.FLUTTERWAVE_SECRET_KEY
        self.public_key = settings.FLUTTERWAVE_PUBLIC_KEY
        self.encryption_key = settings.FLUTTERWAVE_ENCRYPTION_KEY
        self.secret_hash = settings.FLUTTERWAVE_SECRET_HASH
        self.base_url = getattr(settings, "FLUTTERWAVE_BASE_URL", None) or FLW_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }
        self.is_production = str(getattr(settings, "ENVIRONMENT", "development")).lower() == "production"

        if not self.secret_key:
            logger.warning("Flutterwave secret key not configured. Payment functionality will not work.")

    # ── internals ──────────────────────────────────────────────
    def _require_keys(self, operation: str) -> None:
        """Fail closed in production when keys are missing (never mock money)."""
        if self.is_production and not self.secret_key:
            logger.error(f"Flutterwave keys missing in production during {operation}. Refusing mock.")
            raise RuntimeError("Payment provider is not configured")

    def _mock(self, operation: str) -> bool:
        if not self.secret_key:
            self._require_keys(operation)
            logger.warning("Flutterwave keys not configured. Using mock payment for development.")
            return True
        return False

    @staticmethod
    def _redacted(payload: Dict[str, Any]) -> Dict[str, Any]:
        safe = dict(payload)
        for field in ("card_number", "cvv", "pin"):
            if field in safe:
                safe[field] = "***"
        auth = safe.get("authorization")
        if isinstance(auth, dict) and "pin" in auth:
            auth = dict(auth)
            auth["pin"] = "***"
            safe["authorization"] = auth
        safe.pop("client", None)  # encrypted blob — never log it
        return safe

    def _post(self, path: str, body: Dict[str, Any], operation: str) -> Dict[str, Any]:
        try:
            response = requests.post(f"{self.base_url}{path}", json=body, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Flutterwave {operation} error: {self._redacted(body)} -> {e}")
            raise Exception(f"Flutterwave {operation} failed: {str(e)}")

    def _get(self, path: str, operation: str) -> Dict[str, Any]:
        try:
            response = requests.get(f"{self.base_url}{path}", headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Flutterwave {operation} error: {e}")
            raise Exception(f"Flutterwave {operation} failed: {str(e)}")

    # ── step 1+2: direct card charge ───────────────────────────
    def charge_card(
        self,
        card_number: str,
        cvv: str,
        expiry_month: str,
        expiry_year: str,
        amount: float,
        email: str,
        tx_ref: str,
        fullname: Optional[str] = None,
        phone_number: Optional[str] = None,
        redirect_url: Optional[str] = None,
        authorization: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Initiate (or authorize) a direct card charge. Returns the raw FLW response."""
        if self._mock("card charge"):
            return {
                "status": "success",
                "message": "Charge initiated",
                "data": {
                    "id": 999000111,
                    "tx_ref": tx_ref,
                    "flw_ref": f"MOCKFLW-{tx_ref}",
                    "amount": amount,
                    "currency": "NGN",
                    "status": "pending",
                    "processor_response": "Enter the OTP sent to 080****1234",
                    "auth_model": "PIN",
                    "payment_type": "card",
                    "card": {"first_6digits": "553188", "last_4digits": card_number[-4:], "issuer": "MASTERCARD", "country": "NG", "type": "MASTERCARD", "expiry": f"{expiry_month}/{expiry_year}"},
                },
                "meta": {"authorization": {"mode": "otp", "endpoint": "/v3/validate-charge"}},
            }

        if not self.encryption_key:
            raise RuntimeError("FLUTTERWAVE_ENCRYPTION_KEY is required for direct card charges")

        payload: Dict[str, Any] = {
            "card_number": card_number.replace(" ", ""),
            "cvv": cvv,
            "expiry_month": expiry_month,
            "expiry_year": expiry_year,
            "currency": "NGN",
            "amount": str(amount),
            "email": email,
            "fullname": fullname or email,
            "tx_ref": tx_ref,
            "meta": meta or {},
        }
        if phone_number:
            payload["phone_number"] = phone_number
        if redirect_url:
            payload["redirect_url"] = redirect_url
        if authorization:
            payload["authorization"] = authorization

        encrypted = encrypt_payload(self.encryption_key, payload)
        data = self._post("/charges?type=card", {"client": encrypted}, "card charge")
        logger.info(f"Flutterwave card charge initiated: {tx_ref}")
        return data

    def next_step(self, flw_response: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a charge response into a frontend-friendly next-step descriptor.

        Returns ``next_step`` of pin | avs | otp | redirect | success | failed | pending.
        """
        data = flw_response.get("data") or {}
        meta = flw_response.get("meta") or {}
        auth = meta.get("authorization") or {}
        mode = (auth.get("mode") or "").lower()
        status = (data.get("status") or "").lower()

        out: Dict[str, Any] = {
            "tx_ref": data.get("tx_ref"),
            "flw_ref": data.get("flw_ref"),
            "transaction_id": data.get("id"),
            "status": data.get("status"),
            "processor_response": data.get("processor_response"),
            "auth_model": data.get("auth_model"),
        }
        if status == "successful":
            out["next_step"] = "success"
        elif status in ("failed",):
            out["next_step"] = "failed"
        elif mode == "pin":
            out["next_step"] = "pin"
            out["fields"] = auth.get("fields") or ["pin"]
        elif mode in ("avs_noauth", "avs"):
            out["next_step"] = "avs"
            out["fields"] = auth.get("fields") or ["address", "city", "state", "country", "zipcode"]
        elif mode == "otp":
            out["next_step"] = "otp"
            out["validate_endpoint"] = auth.get("endpoint") or "/v3/validate-charge"
        elif mode == "redirect":
            out["next_step"] = "redirect"
            out["redirect_url"] = auth.get("redirect")
        else:
            out["next_step"] = "pending"
        return out

    # ── step 3: OTP validation ─────────────────────────────────
    def validate_charge(self, otp: str, flw_ref: str) -> Dict[str, Any]:
        if self._mock("validate charge"):
            return {
                "status": "success",
                "message": "Charge validated",
                "data": {"id": 999000111, "tx_ref": "MOCK", "flw_ref": flw_ref, "amount": 0, "currency": "NGN", "status": "successful", "payment_type": "card"},
            }
        data = self._post("/validate-charge", {"otp": otp, "flw_ref": flw_ref, "type": "card"}, "validate charge")
        logger.info(f"Flutterwave charge validated: {flw_ref}")
        return data

    # ── step 4: verification ───────────────────────────────────
    def verify_transaction(self, transaction_id: int) -> Dict[str, Any]:
        """Verify by Flutterwave transaction id (``data.id``)."""
        if self._mock("verify transaction"):
            return {
                "status": "success",
                "message": "Transaction fetched successfully",
                "data": {"id": transaction_id, "tx_ref": "MOCK", "flw_ref": f"MOCKFLW-{transaction_id}", "amount": 0, "currency": "NGN", "charged_amount": 0, "status": "successful", "payment_type": "card",
                         "card": {"first_6digits": "553188", "last_4digits": "2950", "issuer": "MASTERCARD", "country": "NG", "type": "MASTERCARD", "expiry": "09/32"},
                         "customer": {"email": "mock@example.com", "name": "Mock", "phone_number": None}},
            }
        data = self._get(f"/transactions/{transaction_id}/verify", "verify transaction")
        logger.info(f"Flutterwave transaction verified: {transaction_id}")
        return data

    def verify_by_tx_ref(self, tx_ref: str) -> Dict[str, Any]:
        """Verify by our own reference (handy for bank-transfer polling)."""
        if self._mock("verify by reference"):
            return {
                "status": "success",
                "message": "Transaction fetched successfully",
                "data": {"id": 999000111, "tx_ref": tx_ref, "flw_ref": f"MOCKFLW-{tx_ref}", "amount": 0, "currency": "NGN", "charged_amount": 0, "status": "successful", "payment_type": "bank_transfer"},
            }
        return self._get(f"/transactions/verify_by_reference?tx_ref={tx_ref}", "verify by reference")

    # ── bank transfer (Pay with Bank Transfer) ─────────────────
    def charge_bank_transfer(
        self,
        email: str,
        amount: float,
        tx_ref: str,
        fullname: Optional[str] = None,
        phone_number: Optional[str] = None,
        meta: Optional[Dict] = None,
        expires_minutes: int = 60,
    ) -> Dict[str, Any]:
        if self._mock("bank transfer charge"):
            expires_dt = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
            return {
                "status": "success",
                "message": "Charge initiated",
                "data": {"id": 999000222, "tx_ref": tx_ref, "flw_ref": f"MOCKFLW-{tx_ref}", "amount": amount, "currency": "NGN", "status": "pending", "payment_type": "bank_transfer"},
                "meta": {"authorization": {"transfer_reference": f"MOCK-{tx_ref}", "transfer_account": "9999999999", "transfer_bank": "Test Bank", "transfer_amount": amount,
                                           "account_expiration": expires_dt.strftime("%Y-%m-%d %H:%M:%S"), "transfer_note": "Mock transfer", "mode": "banktransfer"}},
            }
        payload: Dict[str, Any] = {"tx_ref": tx_ref, "amount": str(amount), "currency": "NGN", "email": email, "meta": meta or {}}
        if fullname:
            payload["fullname"] = fullname
        if phone_number:
            payload["phone_number"] = phone_number
        if expires_minutes:
            payload["bank_transfer_options"] = {"expires": expires_minutes * 60}
        data = self._post("/charges?type=bank_transfer", payload, "bank transfer charge")
        logger.info(f"Flutterwave bank transfer charge initiated: {tx_ref}")
        return data

    # ── tokenized recurring charge ─────────────────────────────
    def create_tokenized_charge(
        self,
        token: str,
        email: str,
        amount: float,
        tx_ref: str,
        narration: Optional[str] = None,
        redirect_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Charge a stored card token (mandate installments). Token is tied to ``email``."""
        if self._mock("tokenized charge"):
            return {
                "status": "success",
                "message": "Charge initiated",
                "data": {"id": 999000333, "tx_ref": tx_ref, "flw_ref": f"MOCKFLW-{tx_ref}", "amount": amount, "currency": "NGN", "status": "successful", "processor_response": "Approved (mock)", "payment_type": "card"},
            }
        payload: Dict[str, Any] = {"token": token, "currency": "NGN", "country": "NG", "amount": amount, "email": email, "tx_ref": tx_ref}
        if narration:
            payload["narration"] = narration
        if redirect_url:
            payload["redirect_url"] = redirect_url
        data = self._post("/tokenized-charges", payload, "tokenized charge")
        logger.info(f"Flutterwave tokenized charge initiated: {tx_ref}")
        return data

    # ── refunds ────────────────────────────────────────────────
    def initiate_refund(self, flw_transaction_id: int, amount: Optional[float] = None) -> Dict[str, Any]:
        if self._mock("refund"):
            return {
                "status": "success",
                "message": "Refund initiated",
                "data": {"id": 999000444, "account_id": 0, "tx_ref": "MOCK", "flw_ref": f"MOCKFLW-{flw_transaction_id}", "amount_refunded": amount or 0, "status": "pending"},
            }
        payload: Dict[str, Any] = {"id": flw_transaction_id}
        if amount is not None:
            payload["amount"] = amount
        data = self._post("/refunds", payload, "refund")
        logger.info(f"Flutterwave refund initiated for transaction: {flw_transaction_id}")
        return data

    # ── webhooks ───────────────────────────────────────────────
    def verify_webhook_signature(self, headers: Dict[str, str], raw_body: Optional[bytes] = None) -> bool:
        """Verify a Flutterwave webhook.

        Accepts the legacy plain ``verif-hash`` comparison and the newer
        HMAC-SHA256 ``flutterwave-signature`` over the raw body.
        """
        lowered = {str(k).lower(): v for k, v in (headers or {}).items()}
        signature = lowered.get("verif-hash") or lowered.get("flutterwave-signature")
        if not signature:
            if getattr(self, "is_production", False):
                logger.error("Flutterwave webhook missing signature in production. Rejecting.")
                return False
            logger.warning("No Flutterwave signature configured. Skipping verification.")
            return True
        if not self.secret_hash:
            if getattr(self, "is_production", False):
                logger.error("FLUTTERWAVE_SECRET_HASH not configured in production. Rejecting webhook.")
                return False
            logger.warning("FLUTTERWAVE_SECRET_HASH not configured. Skipping verification.")
            return True
        # Legacy mode: header carries the secret hash verbatim
        if hmac.compare_digest(str(signature), str(self.secret_hash)):
            return True
        # Newer mode: HMAC-SHA256 of the raw body keyed with the secret hash
        if raw_body:
            try:
                expected = hmac.new(self.secret_hash.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
                return hmac.compare_digest(expected, str(signature))
            except Exception as e:
                logger.error(f"Flutterwave webhook signature verification failed: {e}")
                return False
        return False

    # ── helpers ────────────────────────────────────────────────
    @staticmethod
    def extract_card_token(verify_or_charge_data: Dict[str, Any]) -> Optional[str]:
        """Pull the reusable card token from a charge/verify ``data`` object."""
        card = (verify_or_charge_data or {}).get("card") or {}
        return card.get("token")

    @staticmethod
    def normalize_expiry_iso(value: Any, fallback_minutes: int = 60) -> str:
        """Normalize any expiry representation to ISO-8601 **with explicit UTC offset**.

        Accepts Flutterwave's naive ``"YYYY-MM-DD HH:MM:SS"`` (assumed UTC),
        ISO strings with ``T``/``Z``/offsets, and epoch seconds/millis. Falls
        back to ``now + fallback_minutes`` so callers never emit a missing or
        ambiguous timestamp — the #1 cause of clients showing "expired" for a
        freshly minted account.
        """
        now = datetime.now(timezone.utc)
        dt: Optional[datetime] = None
        if isinstance(value, bool):
            dt = None
        elif isinstance(value, (int, float)):
            try:
                ts = float(value)
                if ts > 1e12:  # millis -> seconds
                    ts /= 1000.0
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                dt = None
        elif isinstance(value, str):
            s = value.strip()
            if s:
                if re.match(r"^\d{10,13}$", s):
                    return FlutterwaveService.normalize_expiry_iso(float(s), fallback_minutes)
                cand = s
                if "T" not in cand and " " in cand:
                    cand = cand.replace(" ", "T", 1)
                try:
                    dt = datetime.fromisoformat(cand.replace("Z", "+00:00"))
                except ValueError:
                    dt = None
                if dt is None:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                                "%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                        try:
                            dt = datetime.strptime(s, fmt)
                            break
                        except ValueError:
                            continue
                if dt is not None and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
        if dt is None:
            dt = now + timedelta(minutes=fallback_minutes)
        return dt.astimezone(timezone.utc).isoformat()

    @staticmethod
    def expiry_is_fresh(value: Any, grace_seconds: int = 30) -> bool:
        """True when ``value`` parses to a timestamp more than ``grace_seconds`` in the future."""
        try:
            dt = datetime.fromisoformat(
                FlutterwaveService.normalize_expiry_iso(value).replace("Z", "+00:00")
            )
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt > datetime.now(timezone.utc) + timedelta(seconds=grace_seconds)
        except ValueError:
            return False

    @staticmethod
    def normalize_bank_transfer_details(flw_response: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """Extract display fields from a bank-transfer charge response.

        Flutterwave nests them under ``meta.authorization`` as
        ``transfer_account`` / ``transfer_bank`` / ``account_expiration``.
        Lookups are defensive across the few shapes seen in the wild, and
        ``expires_at`` is always returned as ISO-8601 with an explicit UTC
        offset so browser ``new Date()`` parsing is unambiguous.
        """
        meta = flw_response.get("meta") or {}
        auth = meta.get("authorization") or {}
        data = flw_response.get("data") or {}

        def first(*candidates: Any) -> Any:
            for c in candidates:
                if c:
                    return c
            return ""

        return {
            "account_number": first(auth.get("transfer_account"), data.get("transfer_account"),
                                    auth.get("account_number"), data.get("account_number")),
            "account_name": first(auth.get("transfer_note"), data.get("transfer_note"),
                                   auth.get("account_name"), data.get("account_name")),
            "bank_name": first(auth.get("transfer_bank"), data.get("transfer_bank"),
                                auth.get("bank_name"), data.get("bank_name")),
            "expires_at": FlutterwaveService.normalize_expiry_iso(
                first(auth.get("account_expiration"), data.get("account_expiration"),
                      auth.get("expires_at"), data.get("expires_at"),
                      auth.get("expiry_date"), data.get("expiry_date"), None) or None
            ),
            "transfer_reference": auth.get("transfer_reference") or data.get("transfer_reference"),
            "transfer_amount": auth.get("transfer_amount") or data.get("transfer_amount"),
        }


# Global instance
flutterwave_service = FlutterwaveService()
