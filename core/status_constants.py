from __future__ import annotations

from typing import Final

# ---------------- Orders ----------------
ORDER_STATUS_PENDING: Final[str] = "pending"
ORDER_STATUS_PROCESSING: Final[str] = "processing"
ORDER_STATUS_PAID: Final[str] = "paid"
ORDER_STATUS_SHIPPED: Final[str] = "shipped"
ORDER_STATUS_DELIVERED: Final[str] = "delivered"
ORDER_STATUS_CANCELLED: Final[str] = "cancelled"

ORDER_STATUSES: Final[tuple[str, ...]] = (
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PROCESSING,
    ORDER_STATUS_PAID,
    ORDER_STATUS_SHIPPED,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_CANCELLED,
)

# A conservative definition of “revenue orders” if needed.
ORDER_REVENUE_STATUSES: Final[tuple[str, ...]] = (
    ORDER_STATUS_PAID,
    ORDER_STATUS_SHIPPED,
    ORDER_STATUS_DELIVERED,
)

# ---------------- Agreements ----------------
AGREEMENT_STATUS_PENDING_REVIEW: Final[str] = "pending_review"
AGREEMENT_STATUS_PENDING_DEPOSIT: Final[str] = "pending_deposit"
AGREEMENT_STATUS_ACTIVE: Final[str] = "active"
AGREEMENT_STATUS_COMPLETED: Final[str] = "completed"
AGREEMENT_STATUS_DEFAULTED: Final[str] = "defaulted"
AGREEMENT_STATUS_CANCELLED: Final[str] = "cancelled"

AGREEMENT_STATUSES: Final[tuple[str, ...]] = (
    AGREEMENT_STATUS_PENDING_REVIEW,
    AGREEMENT_STATUS_PENDING_DEPOSIT,
    AGREEMENT_STATUS_ACTIVE,
    AGREEMENT_STATUS_COMPLETED,
    AGREEMENT_STATUS_DEFAULTED,
    AGREEMENT_STATUS_CANCELLED,
)

AGREEMENT_PENDING_STATUSES: Final[tuple[str, ...]] = (
    AGREEMENT_STATUS_PENDING_REVIEW,
    AGREEMENT_STATUS_PENDING_DEPOSIT,
)

# ---------------- Inspections ----------------
INSPECTION_STATUS_SCHEDULED: Final[str] = "scheduled"
INSPECTION_STATUS_CONFIRMED: Final[str] = "confirmed"
INSPECTION_STATUS_COMPLETED: Final[str] = "completed"
INSPECTION_STATUS_REJECTED: Final[str] = "rejected"
INSPECTION_STATUS_AGREEMENT_PENDING: Final[str] = "agreement_pending"
INSPECTION_STATUS_AGREEMENT_ACCEPTED: Final[str] = "agreement_accepted"

INSPECTION_STATUSES: Final[tuple[str, ...]] = (
    INSPECTION_STATUS_SCHEDULED,
    INSPECTION_STATUS_CONFIRMED,
    INSPECTION_STATUS_COMPLETED,
    INSPECTION_STATUS_REJECTED,
    INSPECTION_STATUS_AGREEMENT_PENDING,
    INSPECTION_STATUS_AGREEMENT_ACCEPTED,
)

INSPECTION_PENDING_STATUSES: Final[tuple[str, ...]] = (
    INSPECTION_STATUS_SCHEDULED,
    INSPECTION_STATUS_CONFIRMED,
)

