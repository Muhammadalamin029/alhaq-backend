"""Discount helpers for products — single source of truth.

Base `price` is the original price and is never mutated by a sale.
A product is on sale iff discount_percent > 0 and now is inside the
optional [starts_at, ends_at] window (blank = open-ended).
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union

MAX_DISCOUNT_PERCENT = Decimal("90")

Number = Union[int, float, Decimal, str]


def _to_decimal(value: Optional[Number]) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_on_sale(
    discount_percent: Optional[Number],
    starts_at: Optional[datetime] = None,
    ends_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> bool:
    pct = _to_decimal(discount_percent)
    if pct is None or pct <= 0:
        return False
    current = _as_aware(now) or datetime.now(timezone.utc)
    start = _as_aware(starts_at)
    end = _as_aware(ends_at)
    if start is not None and current < start:
        return False
    if end is not None and current > end:
        return False
    return True


def effective_price(
    price: Number,
    discount_percent: Optional[Number] = None,
    starts_at: Optional[datetime] = None,
    ends_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> Decimal:
    base = _to_decimal(price) or Decimal("0")
    if not is_on_sale(discount_percent, starts_at, ends_at, now):
        return base.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    pct = _to_decimal(discount_percent) or Decimal("0")
    sale = base * (Decimal("1") - pct / Decimal("100"))
    return sale.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def effective_price_expr(product_table):
    """SQL expression for the sale-aware price (filters/sorting)."""
    from sqlalchemy import case, func
    from sqlalchemy.sql import and_

    pct = product_table.discount_percent
    active = and_(
        pct.isnot(None),
        pct > 0,
        (product_table.discount_starts_at.is_(None))
        | (func.current_timestamp() >= product_table.discount_starts_at),
        (product_table.discount_ends_at.is_(None))
        | (func.current_timestamp() <= product_table.discount_ends_at),
    )
    return case(
        (active, product_table.price * (1 - pct / 100)),
        else_=product_table.price,
    )


def percent_from_sale_price(price: Number, sale_price: Number) -> Optional[Decimal]:
    base = _to_decimal(price)
    sale = _to_decimal(sale_price)
    if base is None or sale is None or base <= 0 or sale <= 0 or sale >= base:
        return None
    pct = (Decimal("1") - sale / base) * Decimal("100")
    return pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sale_price_from_percent(price: Number, discount_percent: Number) -> Optional[Decimal]:
    base = _to_decimal(price)
    pct = _to_decimal(discount_percent)
    if base is None or pct is None or base <= 0 or pct <= 0:
        return None
    sale = base * (Decimal("1") - pct / Decimal("100"))
    return sale.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_discount(
    price: Number,
    discount_percent: Optional[Number] = None,
    sale_price: Optional[Number] = None,
) -> Optional[Decimal]:
    """Resolve admin input (percent and/or sale price) to a single percent.

    sale_price wins when both are given. Returns None for "no discount".
    Raises ValueError on invalid combinations.
    """
    base = _to_decimal(price)
    if base is None or base <= 0:
        raise ValueError("Base price must be greater than 0")

    pct = _to_decimal(discount_percent) if discount_percent not in (None, "") else None
    sale = _to_decimal(sale_price) if sale_price not in (None, "") else None

    if sale is not None:
        if sale <= 0:
            raise ValueError("Sale price must be greater than 0")
        if sale >= base:
            raise ValueError("Sale price must be lower than the original price")
        pct = percent_from_sale_price(base, sale)

    if pct is None:
        return None
    if pct <= 0:
        raise ValueError("Discount percent must be greater than 0")
    if pct > MAX_DISCOUNT_PERCENT:
        raise ValueError(f"Discount percent cannot exceed {MAX_DISCOUNT_PERCENT}%")
    return pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_window(
    starts_at: Optional[datetime],
    ends_at: Optional[datetime],
) -> None:
    if starts_at is not None and ends_at is not None:
        if _as_aware(ends_at) <= _as_aware(starts_at):  # type: ignore[operator]
            raise ValueError("Discount end must be after discount start")
