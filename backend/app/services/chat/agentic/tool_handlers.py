from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple, TypeVar

from app.schemas.chat import ProductCard

ALLOWED_PRODUCT_FILTERS = {
    "min_price",
    "max_price",
    "stock_status",
    "category",
    "material",
    "jewelry_type",
    "color",
}

_T = TypeVar("_T")


def normalize_product_filters(filters: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = dict(filters or {})
    clean: Dict[str, Any] = {}
    for key, value in payload.items():
        if key not in ALLOWED_PRODUCT_FILTERS:
            continue
        if value is None:
            continue
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                continue
            clean[key] = trimmed
        else:
            clean[key] = value
    return clean


def product_card_matches_filters(card: ProductCard, filters: Dict[str, Any]) -> bool:
    if not filters:
        return True

    attributes = card.attributes or {}
    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    stock_status = filters.get("stock_status")
    category = filters.get("category")
    material = filters.get("material")
    jewelry_type = filters.get("jewelry_type")
    color = filters.get("color")

    if min_price is not None:
        try:
            if float(card.price) < float(min_price):
                return False
        except Exception:
            return False
    if max_price is not None:
        try:
            if float(card.price) > float(max_price):
                return False
        except Exception:
            return False

    if stock_status is not None:
        desired = str(stock_status).strip().lower()
        actual = str(card.stock_status or "").strip().lower()
        if desired and desired != actual:
            return False

    for key, expected in (
        ("category", category),
        ("material", material),
        ("jewelry_type", jewelry_type),
        ("color", color),
    ):
        if expected is None:
            continue
        actual = str(attributes.get(key) or "").strip().lower()
        if actual != str(expected).strip().lower():
            return False

    return True


def paginate_items(
    items: Sequence[_T],
    *,
    page: int,
    page_size: int,
    max_items: int,
) -> Tuple[List[_T], int, int, int]:
    total_items = len(items)
    total_pages = max(1, ((total_items - 1) // page_size) + 1) if total_items > 0 else 1
    safe_page = min(page, total_pages)
    start = (safe_page - 1) * page_size
    end = start + page_size
    page_items = list(items[start:end])
    if len(page_items) > max_items:
        page_items = page_items[:max_items]
    return page_items, total_items, safe_page, total_pages
