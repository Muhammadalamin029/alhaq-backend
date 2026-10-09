"""Provider-agnostic product labeling from an image via LangChain.

The vision model is selected with init_chat_model("<provider>:<model>")
so switching providers is config-only:

    VISION_PROVIDER=google_genai  VISION_MODEL=gemini-2.0-flash   (default)
    VISION_PROVIDER=openai        VISION_MODEL=gpt-4o-mini        (+ langchain-openai)
    VISION_PROVIDER=anthropic     VISION_MODEL=claude-sonnet-4-6  (+ langchain-anthropic)

Images use the cross-provider standard content block
{"type": "image", "base64": ..., "mime_type": ...} and the output is a
Pydantic schema via with_structured_output, both supported by all three
providers above.
"""

import base64
import json
from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from core.config import settings
from core.logging_config import get_logger

logger = get_logger(__name__)


class ProductLabel(BaseModel):
    """Structured description of the main product visible in a photo."""

    detected_name: str = Field(
        description="Short product name a shopper would search for, "
        "including brand/model when visible (e.g. 'Nike Air Force 1', "
        "'HP EliteBook 840 laptop', 'wooden office chair'). "
        "'unknown' when no product is recognizable."
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Up to 6 single-word search keywords describing the "
        "product (type, color, material, brand).",
    )
    category_hint: Optional[str] = Field(
        default=None,
        description="Best-guess store category (e.g. electronics, fashion, "
        "furniture, automotive, real estate).",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="0-1 confidence that detected_name is correct.",
    )


LABEL_PROMPT = (
    "Identify the single main product in this photo for an online store search. "
    "Return its likely product name (brand and model if visible), "
    "up to 6 single-word search keywords, a category hint, "
    "and your confidence 0-1. "
    "If no recognizable product is visible, set detected_name to 'unknown' "
    "with confidence 0."
)


def get_vision_model():
    """Build the chat model from VISION_PROVIDER/VISION_MODEL config."""
    import os

    # Bridge .env-loaded keys into the process environment — LangChain
    # provider integrations read their API keys from env vars, and
    # pydantic-settings does not export .env values to os.environ.
    for var in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not os.environ.get(var) and getattr(settings, var, ""):
            os.environ[var] = getattr(settings, var)

    identifier = f"{settings.VISION_PROVIDER}:{settings.VISION_MODEL}"
    # Cost guards: deterministic output, tiny response budget. Gemini-only
    # extras (low media resolution) stay behind the provider check so the
    # factory keeps working for OpenAI/Anthropic-compatible providers.
    extra: dict = {"temperature": 0, "max_tokens": 256}
    if settings.VISION_PROVIDER == "google_genai":
        extra["media_resolution"] = "MEDIA_RESOLUTION_LOW"
    try:
        return init_chat_model(
            identifier,
            timeout=settings.VISION_TIMEOUT,
            max_retries=2,
            **extra,
        )
    except Exception as e:
        logger.error(f"Failed to init vision model '{identifier}': {e}")
        raise ValueError(
            f"Vision provider '{settings.VISION_PROVIDER}' is not available. "
            f"Install its LangChain integration package and set its API key. "
            f"({e})"
        )


def _message(image_b64: str, mime_type: str) -> HumanMessage:
    return HumanMessage(
        content=[
            {"type": "text", "text": LABEL_PROMPT},
            {"type": "image", "base64": image_b64, "mime_type": mime_type},
        ]
    )


def _from_plain_text(text: str) -> Optional[ProductLabel]:
    """Best-effort parse when structured output is unavailable."""
    try:
        data = json.loads(text)
        return ProductLabel.model_validate(data)
    except Exception:
        return None


def label_image_sync(image_bytes: bytes, mime_type: str) -> ProductLabel:
    """Blocking LangChain call — run in a threadpool from async code."""
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    model = get_vision_model()
    try:
        structured = model.with_structured_output(ProductLabel)
        result = structured.invoke([_message(image_b64, mime_type)])
        if isinstance(result, ProductLabel):
            return result
        return ProductLabel.model_validate(result)
    except Exception as e:
        logger.warning(f"Structured vision output failed, retrying plain: {e}")
        response = model.invoke([_message(image_b64, mime_type)])
        parsed = _from_plain_text(response.text)
        if parsed is not None:
            return parsed
        raise ValueError(f"Vision model returned an unusable response: {e}")
