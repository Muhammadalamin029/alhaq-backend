"""Payment receipts.

A receipt is an acknowledgement that money was received, so it is keyed to a
`Payment` (the atomic money-movement record) rather than to an `Order`. A single
order can be settled by several payments (partial payments, installments), and
payments also exist for asset agreements that have no order at all. Tying the
receipt to the payment keeps one receipt per actual transaction and lets the
same document serve order, deposit, installment and full-pay payments.
"""

from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from core.model import Order, OrderItem, Payment, Product, Profile, StoreProfile, User


CURRENCY = "NGN"

PURPOSE_LABELS = {
    "order": "Order payment",
    "asset_deposit": "Asset deposit",
    "asset_installment": "Asset installment",
    "full_pay": "Full payment",
}


def _money(value: Optional[Decimal]) -> str:
    if value is None:
        return f"{CURRENCY} 0.00"
    return f"{CURRENCY} {Decimal(value):,.2f}"


def _receipt_number(payment: Payment) -> str:
    created = payment.created_at or datetime.now(timezone.utc)
    return f"RCPT-{created:%Y%m%d}-{str(payment.id).replace('-', '')[:8].upper()}"


def _asset_name(payment: Payment) -> Optional[str]:
    agreement = payment.agreement
    if not agreement:
        return None
    if agreement.asset_type == "automotive" and agreement.car:
        car = agreement.car
        return f"{car.year} {car.brand} {car.model}".strip()
    if agreement.asset_type == "property" and agreement.property:
        return agreement.property.title
    return None


def _order_lines(db: Session, order: Order) -> Dict[str, Any]:
    items = (
        db.query(OrderItem, Product.name)
        .outerjoin(Product, OrderItem.product_id == Product.id)
        .filter(OrderItem.order_id == order.id)
        .all()
    )

    lines = []
    subtotal = Decimal("0.00")
    for item, product_name in items:
        line_total = (item.price or Decimal("0.00")) * (item.quantity or 0)
        subtotal += line_total
        lines.append(
            {
                "name": product_name or "Item",
                "quantity": item.quantity,
                "unit_price": item.price,
                "line_total": line_total,
                "status": item.status,
            }
        )

    delivery_fee = order.delivery_fee or Decimal("0.00")
    return {
        "id": order.id,
        "status": order.status,
        "created_at": order.created_at,
        "items": lines,
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "total": subtotal + delivery_fee,
    }


def build_receipt(db: Session, payment: Payment) -> Dict[str, Any]:
    """Build a serialisable receipt for a payment (no access checks here)."""
    buyer_profile = (
        db.query(Profile).filter(Profile.id == payment.buyer_id).first()
        if payment.buyer_id
        else None
    )
    buyer_user = (
        db.query(User).filter(User.id == payment.buyer_id).first()
        if payment.buyer_id
        else None
    )
    seller = (
        db.query(StoreProfile).filter(StoreProfile.id == payment.seller_id).first()
        if payment.seller_id
        else db.query(StoreProfile).first()
    )

    order = payment.order
    if order is None and payment.order_id:
        order = db.query(Order).filter(Order.id == payment.order_id).first()

    agreement = payment.agreement
    agreement_block = None
    if agreement:
        agreement_block = {
            "id": agreement.id,
            "asset_type": agreement.asset_type,
            "asset_name": _asset_name(payment),
            "payment_plan": agreement.payment_plan,
            "plan_type": agreement.plan_type,
            "total_price": agreement.total_price,
            "remaining_balance": agreement.remaining_balance,
        }

    return {
        "receipt_number": _receipt_number(payment),
        "issued_at": datetime.now(timezone.utc),
        "currency": CURRENCY,
        "amount": payment.amount,
        "amount_display": _money(payment.amount),
        "status": payment.status,
        "reference": payment.reference,
        "transaction_id": payment.transaction_id,
        "payment_method": payment.payment_method,
        "payment_category": payment.payment_category,
        "payment_type": payment.payment_type,
        "purpose": PURPOSE_LABELS.get(payment.payment_category, "Payment"),
        "paid_at": payment.created_at,
        "payer": {
            "name": (buyer_profile.name if buyer_profile else None),
            "email": (buyer_user.email if buyer_user else None),
        },
        "payee": {
            "name": seller.business_name if seller else "LEL Store",
            "email": seller.contact_email if seller else None,
            "phone": seller.contact_phone if seller else None,
        },
        "order": _order_lines(db, order) if order else None,
        "agreement": agreement_block,
    }


def get_receipt(db: Session, user: Dict[str, Any], payment_id: UUID) -> Optional[Dict[str, Any]]:
    """Return a receipt for a payment the caller is allowed to see.

    Customers may only see their own payments; the store side (admin) may see
    payments belonging to the store.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        return None

    if user["role"] == "admin":
        store = db.query(StoreProfile).first()
        if payment.seller_id and store and payment.seller_id != store.id:
            return None
    elif payment.buyer_id != UUID(str(user["id"])):
        return None

    return build_receipt(db, payment)


def render_receipt_html(receipt: Dict[str, Any]) -> str:
    """Render a self-contained, printable HTML receipt (use the browser's
    print-to-PDF to save a copy)."""

    def esc(value: Any) -> str:
        return escape(str(value)) if value not in (None, "") else "-"

    order = receipt.get("order")
    agreement = receipt.get("agreement")

    if order:
        rows = "".join(
            f"""
            <tr>
              <td>{esc(line["name"])}</td>
              <td class="center">{esc(line["quantity"])}</td>
              <td class="right">{esc(_money(line["unit_price"]))}</td>
              <td class="right">{esc(_money(line["line_total"]))}</td>
            </tr>"""
            for line in order["items"]
        )
        detail_table = f"""
        <table class="lines">
          <thead>
            <tr><th>Item</th><th class="center">Qty</th><th class="right">Unit price</th><th class="right">Amount</th></tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        <table class="totals">
          <tr><td>Subtotal</td><td class="right">{esc(_money(order["subtotal"]))}</td></tr>
          <tr><td>Delivery fee</td><td class="right">{esc(_money(order["delivery_fee"]))}</td></tr>
          <tr class="grand"><td>Order total</td><td class="right">{esc(_money(order["total"]))}</td></tr>
        </table>"""
        related = f"Order #{esc(str(order['id']).split('-')[0].upper())}"
    elif agreement:
        asset_name = agreement.get("asset_name") or agreement["asset_type"]
        detail_table = f"""
        <table class="totals">
          <tr><td>Asset</td><td class="right">{esc(asset_name)}</td></tr>
          <tr><td>Payment plan</td><td class="right">{esc(str(agreement["payment_plan"]).replace("_", " "))}</td></tr>
          <tr><td>Agreement total</td><td class="right">{esc(_money(agreement["total_price"]))}</td></tr>
          <tr class="grand"><td>Remaining balance</td><td class="right">{esc(_money(agreement["remaining_balance"]))}</td></tr>
        </table>"""
        related = f"Agreement #{esc(str(agreement['id']).split('-')[0].upper())}"
    else:
        detail_table = ""
        related = "-"

    payee = receipt["payee"]
    payer = receipt["payer"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Receipt {esc(receipt["receipt_number"])}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         margin: 0; padding: 32px; color: #111827; background: #f9fafb; }}
  .receipt {{ max-width: 720px; margin: 0 auto; background: #fff; border: 1px solid #e5e7eb;
              border-top: 6px solid #16a34a; border-radius: 12px; padding: 32px; }}
  .head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 24px;
           border-bottom: 1px solid #e5e7eb; padding-bottom: 20px; }}
  .brand {{ font-size: 20px; font-weight: 700; }}
  .brand small {{ display: block; font-size: 12px; font-weight: 400; color: #6b7280; margin-top: 4px; }}
  .meta {{ text-align: right; font-size: 13px; color: #374151; }}
  .meta strong {{ display: block; font-size: 16px; color: #111827; }}
  .amount {{ margin: 24px 0; padding: 20px; border-radius: 10px; background: #f0fdf4; text-align: center; }}
  .amount span {{ display: block; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: #16a34a; font-weight: 700; }}
  .amount strong {{ font-size: 32px; }}
  .status {{ display: inline-block; margin-top: 8px; padding: 4px 12px; border-radius: 999px;
             font-size: 12px; font-weight: 700; text-transform: capitalize;
             background: #dcfce7; color: #15803d; }}
  .parties {{ display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 24px; }}
  .party {{ flex: 1 1 200px; }}
  .party h3 {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #6b7280; margin: 0 0 6px; }}
  .party p {{ margin: 2px 0; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  table.lines {{ margin-bottom: 16px; }}
  table.lines th, table.lines td {{ padding: 10px 8px; border-bottom: 1px solid #e5e7eb; text-align: left; }}
  table.lines th {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: #6b7280; }}
  table.totals td {{ padding: 6px 8px; }}
  table.totals tr.grand td {{ font-weight: 700; font-size: 16px; border-top: 1px solid #e5e7eb; padding-top: 12px; }}
  .center {{ text-align: center; }} .right {{ text-align: right; }}
  .kv {{ margin-top: 24px; border-top: 1px solid #e5e7eb; padding-top: 16px; font-size: 13px; color: #374151; }}
  .kv div {{ display: flex; justify-content: space-between; padding: 4px 0; }}
  .kv span:first-child {{ color: #6b7280; }}
  .foot {{ margin-top: 28px; font-size: 12px; color: #6b7280; text-align: center; line-height: 1.6; }}
  .actions {{ max-width: 720px; margin: 16px auto 0; text-align: right; }}
  .actions button {{ background: #16a34a; color: #fff; border: 0; border-radius: 8px; padding: 10px 18px;
                     font-size: 14px; font-weight: 600; cursor: pointer; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .receipt {{ border: 0; border-radius: 0; max-width: none; }}
    .actions {{ display: none; }}
  }}
</style>
</head>
<body>
  <div class="receipt">
    <div class="head">
      <div class="brand">{esc(payee["name"])}<small>Payment Receipt</small></div>
      <div class="meta">
        <strong>{esc(receipt["receipt_number"])}</strong>
        Issued {esc(receipt["issued_at"].strftime("%d %b %Y, %H:%M UTC"))}
      </div>
    </div>

    <div class="amount">
      <span>Amount paid</span>
      <strong>{esc(receipt["amount_display"])}</strong>
      <div class="status">{esc(receipt["status"])}</div>
    </div>

    <div class="parties">
      <div class="party">
        <h3>Paid by</h3>
        <p>{esc(payer["name"])}</p>
        <p>{esc(payer["email"])}</p>
      </div>
      <div class="party">
        <h3>Paid to</h3>
        <p>{esc(payee["name"])}</p>
        <p>{esc(payee["email"])}</p>
      </div>
    </div>

    {detail_table}

    <div class="kv">
      <div><span>Purpose</span><span>{esc(receipt["purpose"])}</span></div>
      <div><span>Related</span><span>{related}</span></div>
      <div><span>Reference</span><span>{esc(receipt["reference"])}</span></div>
      <div><span>Transaction ID</span><span>{esc(receipt["transaction_id"])}</span></div>
      <div><span>Payment method</span><span>{esc(receipt["payment_method"])}</span></div>
      <div><span>Date paid</span><span>{esc(receipt["paid_at"].strftime("%d %b %Y, %H:%M") if receipt["paid_at"] else "-")}</span></div>
    </div>

    <p class="foot">
      This receipt is an acknowledgement of payment received. It is generated
      electronically and is valid without a signature.
    </p>
  </div>

  <div class="actions">
    <button onclick="window.print()">Print / Save as PDF</button>
  </div>
</body>
</html>"""
