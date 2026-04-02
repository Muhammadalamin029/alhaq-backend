from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from db.session import get_db
from core.model import SellerProfile, Product, Order, OrderItem
from schemas.seller import SellerProfileResponse
from core.automotive_service import automotive_service
from core.property_service import property_service
from schemas.automotive import CarResponse
from schemas.property import PropertyResponse
from .seller import SellerStatsResponse

router = APIRouter(tags=["Public"])

@router.get("/sellers", response_model=dict)
def get_public_sellers(db: Session = Depends(get_db)):
    """Get verified sellers for public directory/featured sections"""
    sellers = (
        db.query(SellerProfile)
        .filter(
            SellerProfile.kyc_status == "approved",
            SellerProfile.seller_type.isnot(None)
        )
        .order_by(desc(SellerProfile.created_at))
        .limit(10)
        .all()
    )
    
    seller_list = []
    for seller in sellers:
        # Avoid circular import, we just dump the basics or use a lightweight schema
        seller_list.append({
            "id": str(seller.id),
            "business_name": seller.business_name,
            "description": seller.description,
            "seller_type": seller.seller_type,
            "total_products": seller.total_products,
            "kyc_status": seller.kyc_status
        })

    return {
        "success": True,
        "message": "Sellers fetched successfully",
        "data": seller_list
    }

@router.get("/automotive/featured", response_model=dict)
def get_public_featured_cars(db: Session = Depends(get_db)):
    """Get featured/available cars"""
    cars = automotive_service.list_cars(db, status="available", max_price=None, min_price=None, seller_id=None)
    # limit to top 10 for featured
    cars = cars[:10]
    return {
        "success": True,
        "message": "Featured cars fetched successfully",
        "data": [CarResponse.model_validate(c).model_dump() for c in cars]
    }

@router.get("/properties/featured", response_model=dict)
def get_public_featured_properties(db: Session = Depends(get_db)):
    """Get featured/available properties"""
    properties = property_service.list_properties(db, status="available")
    # limit to top 10 for featured
    properties = properties[:10]
    return {
        "success": True,
        "message": "Featured properties fetched successfully",
        "data": [PropertyResponse.model_validate(p).model_dump() for p in properties]
    }

@router.get("/sellers/{seller_id}", response_model=dict)
def get_public_seller(seller_id: str, db: Session = Depends(get_db)):
    """Get a single verified seller for the public store page"""
    from uuid import UUID
    
    try:
        seller_uuid = UUID(seller_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid seller ID format")
        
    seller = (
        db.query(SellerProfile)
        .filter(SellerProfile.id == seller_uuid, SellerProfile.kyc_status == "approved")
        .first()
    )
    
    if not seller:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Seller not found")
        
    return {
        "success": True,
        "message": "Seller fetched successfully",
        "data": {
            "id": str(seller.id),
            "business_name": seller.business_name,
            "description": seller.description,
            "seller_type": seller.seller_type,
            "total_products": seller.total_products,
            "kyc_status": seller.kyc_status,
            "created_at": seller.created_at.isoformat() if seller.created_at else None
        }
    }

@router.get("/sellers/{seller_id}/inventory", response_model=dict)
def get_public_seller_inventory(seller_id: str, db: Session = Depends(get_db)):
    """Get the correct inventory items according to seller type"""
    from uuid import UUID
    try:
        seller_uuid = UUID(seller_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid seller ID format")

    seller = db.query(SellerProfile).filter(SellerProfile.id == seller_uuid).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    items = []
    seller_type = seller.seller_type or "retailer"

    if seller_type == "car_dealer":
        cars = automotive_service.list_cars(db, status="available", seller_id=seller_uuid)
        items = [CarResponse.model_validate(c).model_dump() for c in cars]
    elif seller_type == "real_agent":
        properties = property_service.list_properties(db, status="available", seller_id=seller_uuid)
        items = [PropertyResponse.model_validate(p).model_dump() for p in properties]
    elif seller_type == "phone_dealer":
        from core.phone_service import phone_service
        from schemas.phone import PhoneResponse
        phones = phone_service.list_phones(db, seller_id=seller_uuid)
        items = [PhoneResponse.model_validate(p).model_dump() for p in phones]
    else:
        # Default to retailer
        query = db.query(Product).filter(Product.seller_id == seller_uuid, Product.status == "active")
        db_items = query.all()
        # manual mapping to avoid importing full product schema here
        for p in db_items:
            items.append({
                "id": str(p.id),
                "name": p.name,
                "price": float(p.price),
                "stock_quantity": p.stock_quantity,
                "category_id": str(p.category_id) if p.category_id else None,
                "images": [{"image_url": img.image_url} for img in p.images] if p.images else [],
                "created_at": p.created_at.isoformat() if p.created_at else None
            })

    return {
        "success": True,
        "message": "Inventory fetched successfully",
        "data": {
            "type": seller_type,
            "items": items,
            "item_count": len(items)
        }
    }
