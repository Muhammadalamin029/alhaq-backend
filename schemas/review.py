from pydantic import BaseModel, Field, model_validator
from typing import Optional
from uuid import UUID
from datetime import datetime


class ReviewCreate(BaseModel):
    product_id: Optional[UUID] = None
    car_id: Optional[UUID] = None
    property_id: Optional[UUID] = None
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    comment: Optional[str] = Field(None, max_length=1000)

    @model_validator(mode="after")
    def exactly_one_target(self):
        targets = [self.product_id, self.car_id, self.property_id]
        if sum(1 for t in targets if t) != 1:
            raise ValueError("Provide exactly one of product_id, car_id or property_id")
        return self


class ReviewUpdate(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5, description="Rating from 1 to 5 stars")
    comment: Optional[str] = Field(None, max_length=1000)


class ReviewerInfo(BaseModel):
    id: UUID
    name: str
    
    class Config:
        from_attributes = True


class ReviewResponse(BaseModel):
    id: UUID
    product_id: Optional[UUID] = None
    product_name: Optional[str] = None
    car_id: Optional[UUID] = None
    car_name: Optional[str] = None
    property_id: Optional[UUID] = None
    property_name: Optional[str] = None
    rating: int
    comment: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    user: ReviewerInfo

    class Config:
        from_attributes = True


class ProductReviewsResponse(BaseModel):
    success: bool
    message: str
    data: list[ReviewResponse]
    meta: dict


class ReviewSingleResponse(BaseModel):
    success: bool
    message: str
    data: ReviewResponse


class ProductRatingStats(BaseModel):
    average_rating: float
    total_reviews: int
    rating_distribution: dict  # {1: count, 2: count, ...}


class ProductRatingStatsResponse(BaseModel):
    success: bool
    message: str
    data: ProductRatingStats
