"""Shared delivery-fee resolution.

Checkout and referral reward orders must agree on how a delivery fee is
calculated. Keeping the rule in one place prevents the two flows from drifting.
"""

from decimal import Decimal
from typing import Optional

from core.model import Address
from core.system_settings_service import system_settings_service


def resolve_delivery_fee(db, address: Optional[Address]) -> Decimal:
    """Return the delivery fee for an address.

    An address whose state has an active configured price wins; otherwise the
    store-wide base delivery price applies. Missing state/price safely falls
    back to the base price.
    """
    settings = system_settings_service.get_or_create_settings(db)

    state = getattr(address, "delivery_state", None)
    if state and state.is_active and state.delivery_price is not None:
        return Decimal(str(state.delivery_price))

    return Decimal(str(settings.base_delivery_price or 0))
