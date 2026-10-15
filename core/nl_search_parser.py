"""Deterministic natural-language parser for the normal product search bar.

No LLM, no network, no database access. Pure function:

    raw query -> ParsedSearch(was_nl, clean_query, category_hint,
                              min_price, max_price, sort_by, sort_order)

``was_nl`` is True only on strong signals (intent verb, price cue /
currency amount, sort hint, or a category synonym inside a longer query).
Otherwise the caller must run the raw string through the normal keyword
path unchanged.

Price understanding is Naira-aware: ``under ₦250,000``, ``below 250k``,
``between 100k and 250k``, ``from ₦100,000 to ₦250,000``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedSearch:
    was_nl: bool
    clean_query: Optional[str] = None
    category_hint: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None


# Canonical hint -> known surface phrases (lowercase). The router maps the
# hint onto a real category row (exact, plural-insensitive, substring).
CATEGORY_SYNONYMS: dict[str, list[str]] = {
    "refrigerator": [
        "double door fridge", "fridge freezer", "fridge",
        "fridges", "refrigerator", "refrigerators",
    ],
    "freezer": ["deep freezer", "chest freezer", "freezer", "freezers"],
    "television": ["smart tv", "led tv", "tv", "tvs", "television", "televisions"],
    "air conditioner": [
        "split ac", "standing ac", "air conditioner", "air conditioners",
        "airconditioner", "ac",
    ],
    "washing machine": ["washing machine", "washing machines", "washer", "washers"],
    "generator": ["power generator", "generator", "generators", "gen set", "genset"],
    "microwave": ["microwave oven", "microwave"],
    "fan": ["ceiling fan", "standing fan", "rechargeable fan", "fan", "fans"],
    "phone": [
        "mobile phone", "android phone", "smartphone", "smartphones",
        "iphone", "phone", "phones",
    ],
    "laptop": ["macbook", "laptop", "laptops", "notebook", "notebooks"],
    "sneakers": [
        "running shoes", "sneaker", "sneakers", "shoe", "shoes", "footwear",
    ],
    "watch": ["wrist watch", "wristwatch", "smart watch", "smartwatch", "watch", "watches"],
    "bag": ["hand bag", "handbag", "backpack", "luggage", "bag", "bags"],
    "sofa": ["sofa", "sofas", "couch", "couches", "settee"],
    "bed": ["bed frame", "mattress", "mattresses", "bed", "beds"],
    "dining table": ["dining set", "dining table"],
    "wardrobe": ["wardrobe", "closet"],
    "shirt": ["t-shirt", "t-shirts", "shirt", "shirts", "tee", "tees"],
    "trousers": ["trouser", "trousers", "jeans", "pants", "chinos"],
    "dress": ["dress", "dresses", "gown", "gowns"],
    "perfume": ["fragrance", "cologne", "perfume", "perfumes"],
    "car": ["vehicle", "suv", "sedan", "car", "cars"],
}

# Longest phrase first so "double door fridge" wins over "fridge".
_SORTED_SYNONYMS: list[tuple[str, str]] = sorted(
    ((phrase, hint) for hint, phrases in CATEGORY_SYNONYMS.items() for phrase in phrases),
    key=lambda item: len(item[0]),
    reverse=True,
)

_INTENT_PREFIX = re.compile(
    r"^(?:please\s+)?(?:help me\s+)?"
    r"(?:find(?:\s+me)?|show(?:\s+me)?|get(?:\s+me)?|give(?:\s+me)?"
    r"|search(?:\s+for)?|need|want|i need|i want|i'?m looking for"
    r"|i am looking for|looking for|do you have|have you got|any)"
    r"\b\s*(?:a|an|the|me|us|some|any|good|best|cheap|affordable)?\s*",
    re.IGNORECASE,
)
_LOOKING_FOR = re.compile(r"\blooking for\b\s*(?:a|an|the|some|any)?\s*", re.IGNORECASE)

_NUM = r"\d[\d,]*(?:\.\d+)?"
_SUFFIX = r"(?:\s*[kKmM]|\s+naira)?"
_CUR = r"(?:₦|NGN|N\.?)?\s*"
_AMOUNT = rf"{_CUR}(?P<num>{_NUM})(?P<suffix>{_SUFFIX})"
# Bare amount only counts with an explicit marker (₦/NGN/k/m/naira),
# so "iphone 13" is never treated as a price.
_MARKED_AMOUNT = (
    rf"(?:₦\s*(?P<num_a>{_NUM})(?P<suffix_a>{_SUFFIX})"
    rf"|NGN\s*(?P<num_b>{_NUM})(?P<suffix_b>{_SUFFIX})"
    rf"|(?P<num_c>{_NUM})(?P<suffix_c>\s*[kKmM]|\s+naira))"
)

_BETWEEN = re.compile(
    rf"\bbetween\s+{_AMOUNT}\s+(?:and|to|-|–)\s+{_CUR}(?P<num2>{_NUM})(?P<suffix2>{_SUFFIX})",
    re.IGNORECASE,
)
_FROM_TO = re.compile(
    rf"\bfrom\s+{_AMOUNT}\s+to\s+{_CUR}(?P<num2>{_NUM})(?P<suffix2>{_SUFFIX})",
    re.IGNORECASE,
)
_RANGE_DASH = re.compile(
    rf"(?P<cur1>₦|NGN)\s*(?P<num1>{_NUM})(?P<suffix1>{_SUFFIX})"
    r"\s*(?:-|–|to)\s*"
    rf"(?P<cur2>₦|NGN)?\s*(?P<num2>{_NUM})(?P<suffix2>{_SUFFIX})",
    re.IGNORECASE,
)
_MARKED_RANGE_DASH = re.compile(
    rf"(?P<num1>{_NUM})(?P<suffix1>\s*[kKmM]|\s+naira)"
    r"\s*(?:-|–|to)\s*"
    rf"(?P<num2>{_NUM})(?P<suffix2>\s*[kKmM]|\s+naira)",
    re.IGNORECASE,
)
_MAX_CUE = re.compile(
    rf"\b(?:under|below|beneath|less than|up to|upto|maximum(?: of| price)?"
    rf"|max(?: of| price)?|cheaper than|within|not more than|not above)\s+{_AMOUNT}",
    re.IGNORECASE,
)
_MIN_CUE = re.compile(
    rf"\b(?:over|above|greater than|more than|at least|atleast|minimum(?: of| price)?"
    rf"|min(?: of| price)?|from|starting from|starting at)\s+{_AMOUNT}",
    re.IGNORECASE,
)
_BARE_MARKED = re.compile(_MARKED_AMOUNT, re.IGNORECASE)

_SORT_ASC = re.compile(
    r"\b(?:cheapest|lowest prices?|most affordable|affordable|budget)\b", re.IGNORECASE
)
_SORT_DESC = re.compile(
    r"\b(?:most expensive|highest prices?|premium|costliest)\b", re.IGNORECASE
)
_SORT_NEWEST = re.compile(
    r"\b(?:newest|latest|most recent|new arrivals?)\b", re.IGNORECASE
)

_TRAILING_FILLER = re.compile(
    r"\s+(?:please|for me|for sale|near me)\s*$", re.IGNORECASE
)
_EDGE_FILLER = re.compile(
    r"^(?:for|with|in|of|and|or|me|my)\b\s+|\s+\b(?:for|with|in|of|and|or|me)\s*$",
    re.IGNORECASE,
)
_GENERIC_PRODUCT_WORD = re.compile(
    r"\bproducts?\b|\bitems?\b", re.IGNORECASE
)


def _to_float(num: str, suffix: Optional[str]) -> Optional[float]:
    try:
        value = float(num.replace(",", "").strip())
    except ValueError:
        return None
    s = (suffix or "").strip().lower()
    if s == "k":
        value *= 1_000
    elif s == "m":
        value *= 1_000_000
    return value


def _extract_prices(working: str) -> tuple[Optional[float], Optional[float], str, bool]:
    """Return (min_price, max_price, remaining_text, found_any)."""
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    found = False

    def _sub(pattern: re.Pattern[str], text: str) -> str:
        return pattern.sub(" ", text)

    m = _BETWEEN.search(working)
    if m:
        lo = _to_float(m.group("num"), m.group("suffix"))
        hi = _to_float(m.group("num2"), m.group("suffix2"))
        if lo is not None and hi is not None:
            if lo > hi:
                lo, hi = hi, lo
            min_price, max_price = lo, hi
            found = True
            working = _sub(_BETWEEN, working)
    if not found:
        m = _FROM_TO.search(working)
        if m:
            lo = _to_float(m.group("num"), m.group("suffix"))
            hi = _to_float(m.group("num2"), m.group("suffix2"))
            if lo is not None and hi is not None:
                if lo > hi:
                    lo, hi = hi, lo
                min_price, max_price = lo, hi
                found = True
                working = _sub(_FROM_TO, working)
    if not found:
        m = _RANGE_DASH.search(working) or _MARKED_RANGE_DASH.search(working)
        if m:
            lo = _to_float(m.group("num1"), m.group("suffix1"))
            hi = _to_float(m.group("num2"), m.group("suffix2"))
            if lo is not None and hi is not None:
                if lo > hi:
                    lo, hi = hi, lo
                min_price, max_price = lo, hi
                found = True
                working = _sub(_RANGE_DASH, _sub(_MARKED_RANGE_DASH, working))

    m = _MAX_CUE.search(working)
    if m:
        value = _to_float(m.group("num"), m.group("suffix"))
        if value is not None:
            if max_price is None or value < max_price:
                max_price = value
            found = True
            working = _sub(_MAX_CUE, working)

    m = _MIN_CUE.search(working)
    if m:
        value = _to_float(m.group("num"), m.group("suffix"))
        if value is not None:
            if min_price is None or value > min_price:
                min_price = value
            found = True
            working = _sub(_MIN_CUE, working)

    if not found:
        m = _BARE_MARKED.search(working)
        if m:
            num = m.group("num_a") or m.group("num_b") or m.group("num_c")
            suffix = m.group("suffix_a") or m.group("suffix_b") or m.group("suffix_c")
            value = _to_float(num, suffix) if num else None
            if value is not None:
                max_price = value
                found = True
                working = _sub(_BARE_MARKED, working)

    return min_price, max_price, working, found


def _extract_sort(working: str) -> tuple[Optional[str], Optional[str], str, bool]:
    if _SORT_ASC.search(working):
        return "price", "asc", _SORT_ASC.sub(" ", working), True
    if _SORT_DESC.search(working):
        return "price", "desc", _SORT_DESC.sub(" ", working), True
    if _SORT_NEWEST.search(working):
        return "created_at", "desc", _SORT_NEWEST.sub(" ", working), True
    return None, None, working, False


def _extract_category(working: str) -> tuple[Optional[str], str, bool]:
    lowered = working.lower()
    for phrase, hint in _SORTED_SYNONYMS:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            remaining = re.sub(
                rf"\b{re.escape(phrase)}\b", " ", working, count=1, flags=re.IGNORECASE
            )
            return hint, remaining, True
    return None, working, False


def parse_search_query(raw: Optional[str]) -> ParsedSearch:
    """Parse a raw search string. Never raises on bad input."""
    text = (raw or "").strip()
    if not text:
        return ParsedSearch(was_nl=False, clean_query=None)
    if len(text) > 200:
        return ParsedSearch(was_nl=False, clean_query=" ".join(text.split()))

    intent = bool(_INTENT_PREFIX.search(text) or _LOOKING_FOR.search(text))
    price_probe_min, price_probe_max, _, price_found = _extract_prices(text)
    _ = (price_probe_min, price_probe_max)
    _, _, _, sort_found = _extract_sort(text)
    _, _, category_found = _extract_category(text)
    tokens = len(text.split())

    was_nl = bool(
        price_found
        or intent
        or sort_found
        or (category_found and tokens > 2)
    )
    if not was_nl:
        return ParsedSearch(was_nl=False, clean_query=" ".join(text.split()))

    working = _INTENT_PREFIX.sub(" ", text)
    working = _LOOKING_FOR.sub(" ", working)
    min_price, max_price, working, _ = _extract_prices(working)
    sort_by, sort_order, working, _ = _extract_sort(working)
    category_hint, working, _ = _extract_category(working)

    working = _GENERIC_PRODUCT_WORD.sub(" ", working)
    working = _TRAILING_FILLER.sub(" ", working)
    prev = None
    while prev != working:
        prev = working
        working = _EDGE_FILLER.sub(" ", working)
    clean = " ".join(working.split()).strip(" .,!?;:'\"")
    return ParsedSearch(
        was_nl=True,
        clean_query=clean or None,
        category_hint=category_hint,
        min_price=min_price,
        max_price=max_price,
        sort_by=sort_by,
        sort_order=sort_order,
    )
