from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

from app.core.config import settings
from app.services.chat.presentation import product_presentation


def build_show_more_follow_up(
    *,
    products: Sequence[Any],
    attribute_filters: Dict[str, str],
    result_count: int,
    display_count: int,
    display_offset: int = 0,
    pagination_has_more: Optional[bool] = None,
    display_attribute_value: Callable[[str], str],
    top_product_attributes: Callable[..., List[str]],
) -> List[str]:
    if pagination_has_more is False:
        return []
    total_results = max(0, int(result_count or 0))
    shown_results = max(0, int(display_count or 0))
    shown_offset = max(0, int(display_offset or 0))
    if total_results <= shown_results + shown_offset:
        return []

    def _label_from_key(key: str) -> str:
        raw = str((attribute_filters or {}).get(key) or "").strip()
        if raw:
            return display_attribute_value(raw)
        values = top_product_attributes(products=products, key=key, limit=1)
        return values[0] if values else ""

    material = _label_from_key("material")
    if material:
        return [f"Show more {material} jewelry"]

    jewelry_type = _label_from_key("jewelry_type")
    if jewelry_type:
        return [f"Show more {jewelry_type} options"]

    design = _label_from_key("design")
    if design:
        return [f"Show more {design} designs"]

    category = _label_from_key("category")
    if category:
        return [f"Show more {category} items"]

    return ["Show more matching items"]


def build_conversion_follow_ups(
    *,
    products: Sequence[Any],
    attribute_filters: Dict[str, str],
    user_text: str,
    needs_knowledge: bool,
    result_count: int,
    display_count: int,
    display_offset: int = 0,
    limit: int = 5,
    debug_meta: Optional[Dict[str, Any]] = None,
    top_product_attributes: Callable[..., List[str]],
    build_show_more_follow_up: Callable[..., List[str]],
    dedupe_follow_up_questions: Callable[..., List[str]],
) -> List[str]:
    del user_text
    if not bool(getattr(settings, "CHAT_CONVERSION_FOLLOW_UPS_ENABLED", True)):
        return []

    follow_ups: List[str] = []
    if "material" not in attribute_filters:
        for material in top_product_attributes(products=products, key="material", limit=2):
            follow_ups.append(f"Show {material} jewelry")
    if "jewelry_type" not in attribute_filters:
        for jewelry_type in top_product_attributes(products=products, key="jewelry_type", limit=2):
            follow_ups.append(f"Show {jewelry_type}")

    has_opal = any(
        str(dict(getattr(product, "attributes", {}) or {}).get("opal_color") or "").strip()
        for product in list(products or [])
    )
    if has_opal:
        follow_ups.append("Show opal colors")

    follow_ups.extend(
        build_show_more_follow_up(
            products=products,
            attribute_filters=attribute_filters,
            result_count=result_count,
            display_count=display_count,
            display_offset=int(display_offset or 0),
            pagination_has_more=(
                debug_meta.get("catalog_pagination_has_more")
                if isinstance(debug_meta, dict) and "catalog_pagination_has_more" in debug_meta
                else None
            ),
        )
    )

    if follow_ups and isinstance(debug_meta, dict):
        quick_reply_actions = dict(debug_meta.get("quick_reply_actions") or {})
        query_cache_key = str(
            debug_meta.get("catalog_query_cache_key")
            or debug_meta.get("catalog_pagination_query_cache_key")
            or ""
        ).strip()
        query_product_ids = [
            str(item).strip()
            for item in list(
                debug_meta.get("catalog_query_product_ids")
                or debug_meta.get("catalog_pagination_query_product_ids")
                or []
            )
            if str(item).strip()
        ]
        page_limit = int(debug_meta.get("catalog_pagination_limit") or product_presentation.PRODUCT_DISPLAY_LIMIT)
        for label in follow_ups:
            label_key = str(label or "").strip().lower()
            if not label_key.startswith("show more"):
                continue
            quick_reply_actions[label_key] = {
                "action": "catalog_pagination",
                "payload": {
                    "kind": "catalog_pagination",
                    "label": str(label or "").strip(),
                    "query_cache_key": query_cache_key,
                    "query_product_ids": list(query_product_ids),
                    "display_offset": int(display_offset or 0),
                    "display_limit": page_limit,
                },
            }
        if quick_reply_actions:
            debug_meta["quick_reply_actions"] = quick_reply_actions

    if needs_knowledge:
        follow_ups.append("How can I contact you?")
    return dedupe_follow_up_questions(follow_ups, limit=limit)


def build_pagination_exhausted_follow_ups(
    *,
    attribute_filters: Dict[str, str],
    limit: int = 3,
    display_attribute_value: Callable[[str], str],
    dedupe_follow_up_questions: Callable[..., List[str]],
) -> List[str]:
    material = display_attribute_value(str((attribute_filters or {}).get("material") or ""))
    jewelry_type = display_attribute_value(str((attribute_filters or {}).get("jewelry_type") or ""))
    suggestions: List[str] = []

    if material:
        suggestions.extend(
            [
                f"Show {material} labrets",
                f"Show {material} barbells",
                "Show 16g options",
            ]
        )
    elif jewelry_type:
        suggestions.extend(
            [
                f"Show titanium {jewelry_type}",
                f"Show gold {jewelry_type}",
                "Show 16g options",
            ]
        )
    else:
        suggestions.extend(
            [
                "Show titanium jewelry",
                "Show 16g options",
                "What other materials do you have?",
            ]
        )

    return dedupe_follow_up_questions(suggestions, limit=limit)
