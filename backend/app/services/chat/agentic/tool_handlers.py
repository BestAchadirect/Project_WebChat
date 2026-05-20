from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple, TypeVar

from app.schemas.chat import ProductCard
from app.services.chat.text_normalization import normalize_user_text as _normalize_text
from app.services.chat.parsing.search_policy import ALLOWED_PRODUCT_FILTERS, normalize_filter_map
from app.services.chat.retrieval.product_detail_resolver import ProductDetailResolver

_T = TypeVar("_T")


def normalize_product_filters(filters: Dict[str, Any] | None) -> Dict[str, Any]:
    return normalize_filter_map(filters, allowed_keys=ALLOWED_PRODUCT_FILTERS)


def product_card_matches_filters(card: ProductCard, filters: Dict[str, Any]) -> bool:
    if not filters:
        return True

    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    stock_status = filters.get("stock_status")
    category = filters.get("category")
    body_part = filters.get("body_part")
    feature = filters.get("feature")
    presentation_type = filters.get("presentation_type")
    material = filters.get("material")
    jewelry_type = filters.get("jewelry_type")
    color = filters.get("color")
    theme = filters.get("theme")

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
        desired = _normalize_text(stock_status)
        actual = _normalize_text(card.stock_status)
        if desired and desired != actual:
            return False

    for key, expected in (
        ("category", category),
        ("body_part", body_part),
        ("feature", feature),
        ("presentation_type", presentation_type),
        ("material", material),
        ("jewelry_type", jewelry_type),
        ("color", color),
        ("theme", theme),
    ):
        if expected is None:
            continue
        if not ProductDetailResolver._match_filter(card, key=key, expected=str(expected)):
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
    safe_page_size = max(1, min(int(page_size), int(max_items)))
    total_pages = max(1, ((total_items - 1) // safe_page_size) + 1) if total_items > 0 else 1
    safe_page = min(max(1, int(page)), total_pages)
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    page_items = list(items[start:end])
    return page_items, total_items, safe_page, total_pages
