from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from core.model import Car, Category, Product, Property
from db.session import get_db

router = APIRouter()

FRONTEND_URL = "https://lelstore.com"


def _url(loc: str, lastmod: datetime | None, changefreq: str, priority: str) -> str:
    parts = [
        "  <url>",
        f"    <loc>{escape(loc)}</loc>",
    ]
    if lastmod:
        parts.append(f"    <lastmod>{lastmod.date().isoformat()}</lastmod>")
    parts.extend([
        f"    <changefreq>{changefreq}</changefreq>",
        f"    <priority>{priority}</priority>",
        "  </url>",
    ])
    return "\n".join(parts)


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(db: Session = Depends(get_db)):
    urls = [
        _url(f"{FRONTEND_URL}/", None, "daily", "1.0"),
        _url(f"{FRONTEND_URL}/products", None, "daily", "0.9"),
        _url(f"{FRONTEND_URL}/automotive", None, "daily", "0.9"),
        _url(f"{FRONTEND_URL}/properties", None, "daily", "0.9"),
        _url(f"{FRONTEND_URL}/categories", None, "weekly", "0.8"),
        _url(f"{FRONTEND_URL}/about", None, "monthly", "0.6"),
        _url(f"{FRONTEND_URL}/help", None, "monthly", "0.5"),
        _url(f"{FRONTEND_URL}/faq", None, "monthly", "0.5"),
        _url(f"{FRONTEND_URL}/trust-and-safety", None, "monthly", "0.5"),
        _url(f"{FRONTEND_URL}/privacy", None, "yearly", "0.3"),
        _url(f"{FRONTEND_URL}/legal", None, "yearly", "0.3"),
    ]

    # Only public listings are included. Private/admin routes are never exposed.
    products = (
        db.query(Product)
        .filter(Product.status == "active")
        .order_by(Product.updated_at.desc())
        .all()
    )
    urls.extend(
        _url(f"{FRONTEND_URL}/products/{product.id}", product.updated_at, "weekly", "0.8")
        for product in products
    )

    cars = (
        db.query(Car)
        .filter(Car.status == "available")
        .order_by(Car.updated_at.desc())
        .all()
    )
    urls.extend(
        _url(f"{FRONTEND_URL}/automotive/{car.id}", car.updated_at, "weekly", "0.8")
        for car in cars
    )

    properties = (
        db.query(Property)
        .filter(Property.status == "available")
        .order_by(Property.updated_at.desc())
        .all()
    )
    urls.extend(
        _url(f"{FRONTEND_URL}/properties/{prop.id}", prop.updated_at, "weekly", "0.8")
        for prop in properties
    )

    categories = db.query(Category).order_by(Category.created_at.desc()).all()
    urls.extend(
        _url(f"{FRONTEND_URL}/categories/{category.id}", category.created_at, "weekly", "0.7")
        for category in categories
    )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>"
    )
    return Response(content=xml, media_type="application/xml")
