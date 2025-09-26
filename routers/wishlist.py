from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from db.session import get_db
from core.auth import role_required
from core.model import Wishlist as WishlistModel, Product
from schemas.wishlist import WishlistCreate, WishlistItemResponse, WishlistListResponse
from typing import List

router = APIRouter()


@router.get("/", response_model=WishlistListResponse)
async def list_wishlist(
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    # Only customers' wishlist is relevant; sellers/admins will still see their own if any
    q = (
        db.query(WishlistModel)
        .options(
            joinedload(WishlistModel.product)
            .joinedload(Product.seller),
        )
        .options(joinedload(WishlistModel.product).joinedload(Product.category))
        .options(joinedload(WishlistModel.product).joinedload(Product.images))
        .filter(WishlistModel.user_id == user["id"])
    )
    total = q.count()
    items = (
        q.order_by(WishlistModel.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "success": True,
        "message": "Wishlist retrieved successfully",
        "data": [WishlistItemResponse.model_validate(i) for i in items],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit,
        },
    }


@router.post("/", response_model=WishlistItemResponse, status_code=status.HTTP_201_CREATED)
async def add_to_wishlist(
    payload: WishlistCreate,
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db),
):
    # Validate product exists and is active
    product = db.query(Product).filter(Product.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Idempotent add: check if already present
    existing = (
        db.query(WishlistModel)
        .filter(
            WishlistModel.user_id == user["id"],
            WishlistModel.product_id == payload.product_id,
        )
        .first()
    )
    if existing:
        db.refresh(existing)
        return WishlistItemResponse.model_validate(existing)

    item = WishlistModel(user_id=user["id"], product_id=payload.product_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return WishlistItemResponse.model_validate(item)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_wishlist(
    product_id: str,
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db),
):
    item = (
        db.query(WishlistModel)
        .filter(
            WishlistModel.user_id == user["id"],
            WishlistModel.product_id == product_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Wishlist item not found")

    db.delete(item)
    db.commit()
    return None
