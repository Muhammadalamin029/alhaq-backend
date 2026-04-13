import json
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class LegalSubsection(BaseModel):
    title: str = ""
    items: list[str] = Field(default_factory=list)


class LegalSection(BaseModel):
    title: str
    subsections: list[LegalSubsection] = Field(default_factory=list)


class LegalStructure(BaseModel):
    sections: list[LegalSection] = Field(default_factory=list)


class LegalDocumentOut(BaseModel):
    slug: str
    body_html: str | None = None
    effective_date_label: str | None = None
    effective_date: str | None = None  # YYYY-MM-DD
    structure: LegalStructure | None = None
    updated_at: str | None = None


class LegalDocumentUpdate(BaseModel):
    effective_date: Optional[date] = None
    structure: LegalStructure = Field(..., description="Sections, subsections, and list items")


def parse_structure_from_db(raw: str | None) -> LegalStructure | None:
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
        return LegalStructure.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        return None
