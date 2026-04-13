"""Render legal document structure to escaped HTML for storage and public display."""

from html import escape

from schemas.legal_document import LegalStructure


def structure_to_html(structure: LegalStructure) -> str:
    parts: list[str] = []
    for sec in structure.sections:
        parts.append(f"<h2>{escape(sec.title)}</h2>")
        for sub in sec.subsections:
            if sub.title and sub.title.strip():
                parts.append(f"<h3>{escape(sub.title.strip())}</h3>")
            if sub.items:
                lis = "".join(f"<li>{escape(t)}</li>" for t in sub.items if t is not None)
                if lis:
                    parts.append(f"<ul>{lis}</ul>")
    return "".join(parts)
