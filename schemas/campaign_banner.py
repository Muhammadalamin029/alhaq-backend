from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CampaignBannerOut(BaseModel):
    id: str
    title: str = ""
    subtitle: Optional[str] = None
    image_url: str
    cta_text: Optional[str] = None
    cta_link: Optional[str] = None
    display_order: int = 0
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CampaignBannerCreate(BaseModel):
    title: str = Field(default="", max_length=255)
    subtitle: Optional[str] = Field(default=None, max_length=500)
    image_url: str = Field(..., description="Uploaded banner image URL (Cloudinary)")
    cta_text: Optional[str] = Field(default=None, max_length=100)
    cta_link: Optional[str] = Field(default=None, max_length=500)
    display_order: int = Field(default=0)
    is_active: bool = Field(default=True)


class CampaignBannerUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    subtitle: Optional[str] = Field(default=None, max_length=500)
    image_url: Optional[str] = None
    cta_text: Optional[str] = Field(default=None, max_length=100)
    cta_link: Optional[str] = Field(default=None, max_length=500)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


def row_to_out(row) -> CampaignBannerOut:
    return CampaignBannerOut(
        id=str(row.id),
        title=row.title or "",
        subtitle=row.subtitle,
        image_url=row.image_url,
        cta_text=row.cta_text,
        cta_link=row.cta_link,
        display_order=row.display_order or 0,
        is_active=bool(row.is_active),
        created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else None,
        updated_at=row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else None,
    )
