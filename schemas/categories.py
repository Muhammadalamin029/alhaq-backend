from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime


# Curated set of icon keys a category can be tagged with. Kept in sync with
# the frontend's icon registry (src/lib/categoryIcons.ts).
CATEGORY_ICON_PATTERN = (
    "^(general|electronics|gadgets|fashion|home|gaming|books|beauty|health|"
    "sports|toys|food|accessories|office|pets)$"
)


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, strip_whitespace=True)
    description: Optional[str] = Field(None, max_length=1000, strip_whitespace=True)
    icon: Optional[str] = Field(None, pattern=CATEGORY_ICON_PATTERN)


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, strip_whitespace=True)
    description: Optional[str] = Field(None, max_length=1000, strip_whitespace=True)
    icon: Optional[str] = Field(None, pattern=CATEGORY_ICON_PATTERN)


class CategoryResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    created_at: datetime
    product_count: Optional[int] = 0

    class Config:
        from_attributes = True
