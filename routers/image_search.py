import asyncio
import hashlib
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from core.config import settings
from core.logging_config import get_logger, log_error
from core.products import product_service
from core.redis_cache import RedisCache
from core.vision import ProductLabel, label_image_sync
from db.session import get_db
from schemas.products import ProductResponse

logger = get_logger("routers.image_search")

router = APIRouter()

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

# Largest side after downscaling — keeps vision cost/latency bounded.
MAX_SIDE_PX = 768


def _prepare_image(raw: bytes) -> bytes:
    """Validate, downscale and normalize an upload to JPEG bytes."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise HTTPException(status_code=400, detail="File is not a valid image")
    if img.format not in ("JPEG", "PNG", "WEBP"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG, PNG or WEBP images are supported",
        )
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


@router.post("/image-search")
async def image_search(
    image: UploadFile = File(..., description="Product photo to search with"),
    db: Session = Depends(get_db),
):
    if image.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Only JPEG, PNG or WEBP images are supported",
        )
    raw = await image.read()
    max_bytes = settings.IMAGE_SEARCH_MAX_MB * 1024 * 1024
    if not raw:
        raise HTTPException(status_code=400, detail="Empty image upload")
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds {settings.IMAGE_SEARCH_MAX_MB}MB limit",
        )

    prepared = _prepare_image(raw)
    cache_key = f"imglabel:{hashlib.sha256(raw).hexdigest()}"
    label: ProductLabel | None = None
    cached = await RedisCache.get(cache_key)
    if cached:
        try:
            label = ProductLabel.model_validate(cached)
            logger.debug("Image-search label cache hit")
        except Exception:
            label = None

    if label is None:
        try:
            label = await asyncio.to_thread(
                label_image_sync, prepared, "image/jpeg"
            )
        except ValueError as e:
            log_error(logger, "Vision labeling failed", e)
            raise HTTPException(
                status_code=502,
                detail="Could not analyze the image, please try again",
            )
        await RedisCache.set(
            cache_key, label.model_dump(), ttl=settings.IMAGE_SEARCH_CACHE_TTL
        )

    # Query order: detected name first, then keywords as fallback.
    queries = []
    if label.detected_name.lower() != "unknown":
        queries.append(label.detected_name)
    if label.keywords:
        queries.append(" ".join(label.keywords[:4]))

    searched_query: str | None = None
    products: list = []
    count = 0
    for q in queries:
        found, total = product_service.fetch_products(
            db=db, limit=12, page=1, search_query=q
        )
        if total:
            products, count, searched_query = found, total, q
            break
    if searched_query is None and queries:
        searched_query = queries[0]

    logger.info(
        f"Image search: detected='{label.detected_name}' "
        f"confidence={label.confidence:.2f} searched='{searched_query}' hits={count}"
    )
    return {
        "success": True,
        "message": "Image analyzed successfully",
        "detected": label.model_dump(),
        "searched_query": searched_query,
        "data": (
            [ProductResponse.with_discount(p).model_dump(mode="json") for p in products]
            if products
            else []
        ),
        "pagination": {
            "page": 1,
            "limit": 12,
            "total": count,
            "total_pages": (count + 11) // 12 if count else 0,
        },
    }
