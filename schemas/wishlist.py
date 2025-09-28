from pydantic import BaseModel, UUID4
from datetime import datetime
from schemas.products import ProductResponse


class WishlistCreate(BaseModel):
    product_id: UUID4


class WishlistItemResponse(BaseModel):
    id: UUID4
    user_id: UUID4
    product_id: UUID4
    created_at: datetime
    product: ProductResponse

    class Config:
        from_attributes = True


class WishlistListResponse(BaseModel):
    success: bool
    message: str
    data: list[WishlistItemResponse]
    pagination: dict
