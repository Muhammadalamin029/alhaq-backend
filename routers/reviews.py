from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc
from typing import List, Optional
from uuid import UUID

from db.session import get_db
from core.auth import role_required
from core.model import Review, Product, Profile, Order, OrderItem, Car, Property, GeneralAgreement
from schemas.review import (
    ReviewCreate,
    ReviewUpdate,
    ReviewResponse,
    ProductReviewsResponse,
    ReviewSingleResponse,
    ProductRatingStats,
    ProductRatingStatsResponse
)
from core.system_settings_service import system_settings_service

router = APIRouter()


def _review_to_response(
    review: Review,
    product_name: Optional[str] = None,
    car_name: Optional[str] = None,
    property_name: Optional[str] = None,
) -> ReviewResponse:
    """Map a Review ORM row to its API response, resolving the display name of
    whichever asset (product, car or property) it belongs to."""
    resolved_product_name = product_name or (review.product.name if review.product else None)
    resolved_car_name = car_name or (f"{review.car.brand} {review.car.model}" if review.car else None)
    resolved_property_name = property_name or (review.property.title if review.property else None)
    return ReviewResponse(
        id=review.id,
        product_id=review.product_id,
        product_name=resolved_product_name,
        car_id=review.car_id,
        car_name=resolved_car_name,
        property_id=review.property_id,
        property_name=resolved_property_name,
        rating=review.rating,
        comment=review.comment,
        created_at=review.created_at,
        updated_at=review.updated_at,
        user=review.user,
    )


@router.get("/product/{product_id}", response_model=ProductReviewsResponse)
async def get_product_reviews(
    product_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Get all reviews for a specific product"""

    # Check if product exists
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    # Get reviews with pagination
    offset = (page - 1) * limit
    reviews_query = (
        db.query(Review)
        .options(joinedload(Review.user))
        .filter(Review.product_id == product_id)
        .order_by(desc(Review.created_at))
    )

    total_reviews = reviews_query.count()
    reviews = reviews_query.offset(offset).limit(limit).all()

    return ProductReviewsResponse(
        success=True,
        message="Product reviews retrieved successfully",
        data=[_review_to_response(r, product_name=product.name) for r in reviews],
        meta={
            "page": page,
            "limit": limit,
            "total": total_reviews,
            "total_pages": (total_reviews + limit - 1) // limit
        }
    )


@router.get("/product/{product_id}/stats", response_model=ProductRatingStatsResponse)
async def get_product_rating_stats(
    product_id: UUID,
    db: Session = Depends(get_db)
):
    """Get rating statistics for a product"""

    # Check if product exists
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    # Get rating statistics
    stats = (
        db.query(
            func.avg(Review.rating).label('avg_rating'),
            func.count(Review.id).label('total_reviews')
        )
        .filter(Review.product_id == product_id)
        .first()
    )

    # Get rating distribution
    rating_dist = (
        db.query(Review.rating, func.count(Review.id))
        .filter(Review.product_id == product_id)
        .group_by(Review.rating)
        .all()
    )

    rating_distribution = {i: 0 for i in range(1, 6)}
    for rating, count in rating_dist:
        rating_distribution[rating] = count

    return ProductRatingStatsResponse(
        success=True,
        message="Product rating statistics retrieved successfully",
        data=ProductRatingStats(
            average_rating=float(stats.avg_rating or 0),
            total_reviews=stats.total_reviews or 0,
            rating_distribution=rating_distribution
        )
    )


@router.get("/car/{car_id}", response_model=ProductReviewsResponse)
async def get_car_reviews(
    car_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Get all reviews for a specific car listing"""
    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Car not found")

    offset = (page - 1) * limit
    reviews_query = (
        db.query(Review)
        .options(joinedload(Review.user))
        .filter(Review.car_id == car_id)
        .order_by(desc(Review.created_at))
    )

    total_reviews = reviews_query.count()
    reviews = reviews_query.offset(offset).limit(limit).all()
    car_name = f"{car.brand} {car.model}"

    return ProductReviewsResponse(
        success=True,
        message="Car reviews retrieved successfully",
        data=[_review_to_response(r, car_name=car_name) for r in reviews],
        meta={
            "page": page,
            "limit": limit,
            "total": total_reviews,
            "total_pages": (total_reviews + limit - 1) // limit
        }
    )


@router.get("/car/{car_id}/stats", response_model=ProductRatingStatsResponse)
async def get_car_rating_stats(
    car_id: UUID,
    db: Session = Depends(get_db)
):
    """Get rating statistics for a car listing"""
    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Car not found")

    stats = (
        db.query(
            func.avg(Review.rating).label('avg_rating'),
            func.count(Review.id).label('total_reviews')
        )
        .filter(Review.car_id == car_id)
        .first()
    )

    rating_dist = (
        db.query(Review.rating, func.count(Review.id))
        .filter(Review.car_id == car_id)
        .group_by(Review.rating)
        .all()
    )

    rating_distribution = {i: 0 for i in range(1, 6)}
    for rating, count in rating_dist:
        rating_distribution[rating] = count

    return ProductRatingStatsResponse(
        success=True,
        message="Car rating statistics retrieved successfully",
        data=ProductRatingStats(
            average_rating=float(stats.avg_rating or 0),
            total_reviews=stats.total_reviews or 0,
            rating_distribution=rating_distribution
        )
    )


@router.get("/property/{property_id}", response_model=ProductReviewsResponse)
async def get_property_reviews(
    property_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Get all reviews for a specific property listing"""
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    offset = (page - 1) * limit
    reviews_query = (
        db.query(Review)
        .options(joinedload(Review.user))
        .filter(Review.property_id == property_id)
        .order_by(desc(Review.created_at))
    )

    total_reviews = reviews_query.count()
    reviews = reviews_query.offset(offset).limit(limit).all()

    return ProductReviewsResponse(
        success=True,
        message="Property reviews retrieved successfully",
        data=[_review_to_response(r, property_name=prop.title) for r in reviews],
        meta={
            "page": page,
            "limit": limit,
            "total": total_reviews,
            "total_pages": (total_reviews + limit - 1) // limit
        }
    )


@router.get("/property/{property_id}/stats", response_model=ProductRatingStatsResponse)
async def get_property_rating_stats(
    property_id: UUID,
    db: Session = Depends(get_db)
):
    """Get rating statistics for a property listing"""
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    stats = (
        db.query(
            func.avg(Review.rating).label('avg_rating'),
            func.count(Review.id).label('total_reviews')
        )
        .filter(Review.property_id == property_id)
        .first()
    )

    rating_dist = (
        db.query(Review.rating, func.count(Review.id))
        .filter(Review.property_id == property_id)
        .group_by(Review.rating)
        .all()
    )

    rating_distribution = {i: 0 for i in range(1, 6)}
    for rating, count in rating_dist:
        rating_distribution[rating] = count

    return ProductRatingStatsResponse(
        success=True,
        message="Property rating statistics retrieved successfully",
        data=ProductRatingStats(
            average_rating=float(stats.avg_rating or 0),
            total_reviews=stats.total_reviews or 0,
            rating_distribution=rating_distribution
        )
    )


@router.post("/", response_model=ReviewSingleResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    review_data: ReviewCreate,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Create a new product, car or property review (customers only)"""
    system_settings_service.require_verified_email_for_user(db, user["id"], "create a review")

    if review_data.product_id:
        product = db.query(Product).filter(Product.id == review_data.product_id).first()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

        has_purchased = (
            db.query(OrderItem)
            .join(Order)
            .filter(
                Order.buyer_id == user["id"],
                OrderItem.product_id == review_data.product_id,
                Order.status.in_(["delivered"])  # Only delivered orders
            )
            .first()
        )
        if not has_purchased:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only review products you have purchased and received"
            )

        existing_review = db.query(Review).filter(
            Review.user_id == user["id"],
            Review.product_id == review_data.product_id
        ).first()
        if existing_review:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You have already reviewed this product")

    elif review_data.car_id:
        car = db.query(Car).filter(Car.id == review_data.car_id).first()
        if not car:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Car not found")

        has_purchased = (
            db.query(GeneralAgreement)
            .filter(
                GeneralAgreement.user_id == user["id"],
                GeneralAgreement.asset_type == "automotive",
                GeneralAgreement.asset_id == review_data.car_id,
                GeneralAgreement.status == "completed",
            )
            .first()
        )
        if not has_purchased:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only review cars you have fully purchased"
            )

        existing_review = db.query(Review).filter(
            Review.user_id == user["id"],
            Review.car_id == review_data.car_id
        ).first()
        if existing_review:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You have already reviewed this car")

    else:
        prop = db.query(Property).filter(Property.id == review_data.property_id).first()
        if not prop:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

        has_purchased = (
            db.query(GeneralAgreement)
            .filter(
                GeneralAgreement.user_id == user["id"],
                GeneralAgreement.asset_type == "property",
                GeneralAgreement.asset_id == review_data.property_id,
                GeneralAgreement.status == "completed",
            )
            .first()
        )
        if not has_purchased:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only review properties you have fully purchased"
            )

        existing_review = db.query(Review).filter(
            Review.user_id == user["id"],
            Review.property_id == review_data.property_id
        ).first()
        if existing_review:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You have already reviewed this property")

    new_review = Review(
        user_id=user["id"],
        product_id=review_data.product_id,
        car_id=review_data.car_id,
        property_id=review_data.property_id,
        rating=review_data.rating,
        comment=review_data.comment
    )

    db.add(new_review)
    db.commit()
    db.refresh(new_review)

    # Load the review with user, product, car and property
    review_with_user = (
        db.query(Review)
        .options(joinedload(Review.user), joinedload(Review.product), joinedload(Review.car), joinedload(Review.property))
        .filter(Review.id == new_review.id)
        .first()
    )

    return ReviewSingleResponse(
        success=True,
        message="Review created successfully",
        data=_review_to_response(review_with_user),
    )


@router.put("/{review_id}", response_model=ReviewSingleResponse)
async def update_review(
    review_id: UUID,
    review_data: ReviewUpdate,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Update an existing review (only by the review author)"""

    review = (
        db.query(Review)
        .options(joinedload(Review.user), joinedload(Review.product), joinedload(Review.car), joinedload(Review.property))
        .filter(
            Review.id == review_id,
            Review.user_id == user["id"]
        )
        .first()
    )

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found or you don't have permission to update it"
        )

    # Update review fields
    update_data = review_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(review, field, value)

    db.commit()
    db.refresh(review)

    return ReviewSingleResponse(
        success=True,
        message="Review updated successfully",
        data=_review_to_response(review),
    )


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: UUID,
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    """Delete a review (by author or admin)"""

    review = db.query(Review).filter(Review.id == review_id).first()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )

    # Check permissions
    if user["role"] != "admin" and review.user_id != user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this review"
        )

    db.delete(review)
    db.commit()
    return None


@router.get("/my-reviews", response_model=ProductReviewsResponse)
async def get_my_reviews(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Get all reviews by the current user"""

    offset = (page - 1) * limit
    reviews_query = (
        db.query(Review)
        .options(joinedload(Review.user), joinedload(Review.product), joinedload(Review.car), joinedload(Review.property))
        .filter(Review.user_id == user["id"])
        .order_by(desc(Review.created_at))
    )

    total_reviews = reviews_query.count()
    reviews = reviews_query.offset(offset).limit(limit).all()

    return ProductReviewsResponse(
        success=True,
        message="Your reviews retrieved successfully",
        data=[_review_to_response(review) for review in reviews],
        meta={
            "page": page,
            "limit": limit,
            "total": total_reviews,
            "total_pages": (total_reviews + limit - 1) // limit
        }
    )
