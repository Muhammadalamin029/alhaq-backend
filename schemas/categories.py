from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, strip_whitespace=True)
    description: Optional[str] = Field(None, max_length=1000, strip_whitespace=True)


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, strip_whitespace=True)
    description: Optional[str] = Field(None, max_length=1000, strip_whitespace=True)


class CategoryResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True
