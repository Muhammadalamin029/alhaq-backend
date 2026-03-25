from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
from typing import List, Optional
from fastapi import HTTPException
from core.model import Property, AssetImage, RealEstateSessionRequest, SellerProfile, PropertyUnit, GeneralInspection
from schemas.property import PropertyCreate, PropertyUpdate, SessionRequestCreate

class PropertyService:
    def create_property(self, db: Session, seller_id: UUID, property_data: PropertyCreate) -> Property:
        new_property = Property(
            seller_id=seller_id,
            title=property_data.title,
            description=property_data.description,
            price=property_data.price,
            location=property_data.location,
            listing_type=property_data.listing_type,
            buildings_count=property_data.buildings_count or 1,
            status="available"
        )
        db.add(new_property)
        db.flush()

        # Create Property Units
        if property_data.units:
            for u in property_data.units:
                unit = PropertyUnit(
                    property_id=new_property.id,
                    unit_name=u.unit_name or "Unit",
                    unit_number=u.unit_number,
                    status="available"
                )
                db.add(unit)
        else:
            num_units = property_data.buildings_count or 1
            for i in range(num_units):
                unit = PropertyUnit(
                    property_id=new_property.id,
                    unit_name=f"Unit {i+1}" if num_units > 1 else "Main Unit",
                    status="available"
                )
                db.add(unit)

        if property_data.images:
            for img_data in property_data.images:
                img = AssetImage(
                    property_id=new_property.id,
                    image_url=img_data.image_url
                )
                db.add(img)

        db.commit()
        db.refresh(new_property)
        return new_property

    def list_properties(self, db: Session, seller_id: UUID = None, status: str = "available") -> List[Property]:
        query = db.query(Property)
        if seller_id:
            query = query.filter(Property.seller_id == seller_id)
        if status:
            query = query.filter(Property.status == status)
        return query.order_by(Property.created_at.desc()).all()

    def get_property(self, db: Session, property_id: UUID) -> Optional[Property]:
        return db.query(Property).filter(Property.id == property_id).first()

    def update_property(self, db: Session, property_id: UUID, seller_id: UUID, update_data: PropertyUpdate) -> Property:
        prop = db.query(Property).filter(Property.id == property_id, Property.seller_id == seller_id).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found or unauthorized")
        
        update_dict = update_data.model_dump(exclude_unset=True)
        
        if "images" in update_dict:
            # Remove existing images
            db.query(AssetImage).filter(AssetImage.property_id == property_id).delete()
            
            # Add new images
            images_data = update_dict.pop("images")
            if images_data:
                for img_data in images_data:
                    img = AssetImage(
                        property_id=property_id,
                        image_url=img_data["image_url"] if isinstance(img_data, dict) else img_data.image_url
                    )
                    db.add(img)

        for key, value in update_dict.items():
            setattr(prop, key, value)
            
        db.commit()
        db.refresh(prop)
        return prop

    def create_session_request(self, db: Session, user_id: UUID, data: SessionRequestCreate) -> RealEstateSessionRequest:
        new_request = RealEstateSessionRequest(
            user_id=user_id,
            title=data.title,
            location=data.location,
            description=data.description,
            proposed_price=data.proposed_price,
            property_details=data.property_details,
            buildings_count=data.buildings_count or 1,
            status="pending",
            units_data=[u.dict() for u in data.units] if data.units else None
        )
        db.add(new_request)
        db.flush()

        if data.images:
            for img_data in data.images:
                img = AssetImage(
                    session_request_id=new_request.id,
                    image_url=img_data.image_url
                )
                db.add(img)

        db.commit()
        db.refresh(new_request)
        return new_request

    def list_session_requests(self, db: Session, user_id: UUID = None) -> List[RealEstateSessionRequest]:
        query = db.query(RealEstateSessionRequest)
        if user_id:
            query = query.filter(RealEstateSessionRequest.user_id == user_id)
        return query.order_by(RealEstateSessionRequest.created_at.desc()).all()

    def update_session_status(self, db: Session, request_id: UUID, status: str, notes: str = None) -> RealEstateSessionRequest:
        req = db.query(RealEstateSessionRequest).filter(RealEstateSessionRequest.id == request_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Session request not found")
        
        req.status = status
        if notes:
            if req.property_details:
                req.property_details += f"\nAdmin Notes: {notes}"
            else:
                req.property_details = f"Admin Notes: {notes}"
        
        # If status is 'acquired', we might want to convert the reserved Property to available.
        # However, following the new flow, the GeneralAgreement completion handles ownership logic.
        # But if we just update the text manually:
        db.commit()
        db.refresh(req)
        return req

    def accept_session_request(self, db: Session, request_id: UUID, admin_id: UUID, inspection_date: datetime, notes: str = None) -> RealEstateSessionRequest:
        req = db.query(RealEstateSessionRequest).filter(RealEstateSessionRequest.id == request_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Session request not found")
            
        if req.status != "pending":
            raise HTTPException(status_code=400, detail="Only pending requests can be accepted")

        # Look up the seller's SellerProfile (Property.seller_id requires seller_profiles.id)
        seller_profile = db.query(SellerProfile).filter(SellerProfile.id == req.user_id).first()
        if not seller_profile:
            raise HTTPException(status_code=400, detail="Submitting user does not have a seller profile")

        # 1. Create Property stub for the inspection pipeline
        new_property = Property(
            seller_id=seller_profile.id,
            title=f"[ACQUISITION] {req.title or 'Property'}",
            description=req.description,
            price=req.proposed_price or 0,
            location=req.location,
            buildings_count=req.buildings_count or 1,
            status="pending_inspection",
            listing_type="sale",
            acquisition_session_id=req.id
        )
        db.add(new_property)
        db.flush()

        # Create Property Units for acquisition
        if req.units_data:
            for u_data in req.units_data:
                unit = PropertyUnit(
                    property_id=new_property.id,
                    unit_name=u_data.get("unit_name") or "Building",
                    unit_number=u_data.get("unit_number"),
                    status="pending_inspection"
                )
                db.add(unit)
        else:
            num_units = req.buildings_count or 1
            for i in range(num_units):
                unit = PropertyUnit(
                    property_id=new_property.id,
                    unit_name=f"Building {i+1}" if num_units > 1 else "Main Building",
                    status="pending_inspection"
                )
                db.add(unit)

        # Copy Images
        for img in req.images:
            new_img = AssetImage(property_id=new_property.id, image_url=img.image_url)
            db.add(new_img)

        # 2. Schedule General Inspection — admin acts as the buyer (user_id),
        #    property seller profile is the seller_id
        inspection = GeneralInspection(
            seller_id=seller_profile.id,
            user_id=admin_id,
            asset_type="property",
            asset_id=new_property.id,
            inspection_date=inspection_date,
            agreed_price=req.proposed_price,
            status="scheduled",
            acquisition_session_id=req.id
        )
        db.add(inspection)

        # 3. Update Session Status
        req.status = "inspecting"
        if notes:
            if req.property_details:
                req.property_details += f"\nAdmin Notes: {notes}"
            else:
                req.property_details = f"Admin Notes: {notes}"

        db.commit()
        db.refresh(req)
        return req

    def list_internal_inventory(self, db: Session) -> List[Property]:
        # Internal inventory properties are those starting with [ACQUIRED] or held by platform
        # For now, let's filter by title or another flag if we had one.
        # Ideally we'd have an 'is_internal' flag.
        return db.query(Property).filter(Property.status == "acquired").all()

property_service = PropertyService()
