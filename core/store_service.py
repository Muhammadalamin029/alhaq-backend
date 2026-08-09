from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.model import StoreProfile


def get_store_id(db: Session) -> UUID:
    """Return the id of the single store profile (single-vendor model).

    Inventory tables (`products`, `cars`, `properties`, ...) FK `seller_id` to
    `store_profiles.id`. Now that listing/asset management is admin-only, admin
    users create/own inventory on behalf of the one store rather than as
    themselves, so callers resolve this id instead of using the acting
    admin's own user id.
    """
    store = db.query(StoreProfile).first()
    if not store:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Store profile is not configured",
        )
    return store.id
