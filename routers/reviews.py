from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc
from typing import List
from uuid import UUID

from db.session import get_db
from core.auth import role_required
from core.model import Review, Product, Profile, Order, OrderItem
from schemas.review import (
    ReviewCreate, 
    ReviewUpdate, 
    ReviewResponse, 
    ProductReviewsResponse, 
    ReviewSingleResponse,
    ProductRatingStats,
    ProductRatingStatsResponse
)

router = APIRouter()


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
        data=[ReviewResponse.model_validate(review) for review in reviews],
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


@router.post("/", response_model=ReviewSingleResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    review_data: ReviewCreate,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Create a new product review (customers only)"""
    
    # Check if product exists
    product = db.query(Product).filter(Product.id == review_data.product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    # Check if user has purchased this product
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
    
    # Check if user already reviewed this product
    existing_review = db.query(Review).filter(
        Review.user_id == user["id"],
        Review.product_id == review_data.product_id
    ).first()
    
    if existing_review:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already reviewed this product"
        )
    
    # Create new review
    new_review = Review(
        user_id=user["id"],
        product_id=review_data.product_id,
        rating=review_data.rating,
        comment=review_data.comment
    )
    
    db.add(new_review)
    db.commit()
    db.refresh(new_review)
    
    # Load the review with user data
    review_with_user = (
        db.query(Review)
        .options(joinedload(Review.user))
        .filter(Review.id == new_review.id)
        .first()
    )
    
    return ReviewSingleResponse(
        success=True,
        message="Review created successfully",
        data=ReviewResponse.model_validate(review_with_user)
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
        .options(joinedload(Review.user))
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
        data=ReviewResponse.model_validate(review)
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
        .options(joinedload(Review.user))
        .filter(Review.user_id == user["id"])
        .order_by(desc(Review.created_at))
    )
    
    total_reviews = reviews_query.count()
    reviews = reviews_query.offset(offset).limit(limit).all()
    
    return ProductReviewsResponse(
        success=True,
        message="Your reviews retrieved successfully",
        data=[ReviewResponse.model_validate(review) for review in reviews],
        meta={
            "page": page,
            "limit": limit,
            "total": total_reviews,
            "total_pages": (total_reviews + limit - 1) // limit
        }
    )
