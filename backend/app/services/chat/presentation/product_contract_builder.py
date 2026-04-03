from __future__ import annotations

from typing import Any, Callable, Dict, List, Sequence

from app.services.chat.presentation import product_presentation


def build_product_cards_contract(
    *,
    context: Any,
    mapped: Dict[str, Dict[str, Any]],
    choose: Callable[[str, Sequence[str]], str],
    build_store_overview_reply: Callable[..., str],
    build_show_more_follow_up: Callable[..., List[str]],
    build_conversion_follow_ups: Callable[..., List[str]],
) -> Dict[str, Any]:
    user_text = str(getattr(context, "user_text", "") or "").strip()
    debug = dict(getattr(context, "debug", {}) or {})
    canonical_products = list(getattr(context, "canonical_products", []) or [])
    attribute_filters = dict(getattr(context, "attribute_filters", {}) or {})
    result_count = int(getattr(context, "result_count", 0) or 0)
    workflow = str(getattr(context, "workflow", "") or "").strip()

    if bool(debug.get("detail_reply_text")):
        display_products = list(canonical_products)
    else:
        display_products, _total_unique_products = product_presentation.dedupe_products_by_master_code(
            canonical_products,
            limit=product_presentation.PRODUCT_DISPLAY_LIMIT,
        )

    follow_ups: List[str] = []
    carousel_msg = ""
    is_recommendation_view = (
        workflow.lower() == "recommendation"
        or "recommendations" in mapped
        or bool(debug.get("recommendation_ranked_count"))
    )

    if bool(debug.get("store_overview_request")):
        assistant_text = str(debug.get("store_overview_reply") or "").strip()
        if not assistant_text:
            assistant_text = build_store_overview_reply(products=display_products)
        follow_ups.extend(list(debug.get("store_overview_follow_ups") or []))
    elif bool(debug.get("detail_reply_text")):
        assistant_text = str(debug.get("detail_reply_text") or "").strip()
        carousel_msg = str(debug.get("detail_carousel_msg") or "").strip()
        follow_ups.extend(list(debug.get("detail_follow_ups") or []))
    elif is_recommendation_view:
        assistant_text = product_presentation.build_recommendation_summary_reply(
            products=display_products,
            attribute_filters=attribute_filters,
            recommendation_mode=str(debug.get("recommendation_mode_requested") or ""),
            recommendation_label=str(debug.get("recommendation_complementary_label") or ""),
            user_text=user_text,
        )
    else:
        assistant_text = product_presentation.build_product_match_reply(
            attribute_filters=attribute_filters,
            user_text=user_text,
            products=display_products,
        )

    if not carousel_msg:
        carousel_msg = choose(
            f"{workflow}:carousel",
            [
                "Matching products are shown below.",
                "These are the top matches for your request.",
                "Here are the products that best fit your request.",
            ],
        )

    if bool(debug.get("catalog_pagination_requested")):
        assistant_text = choose(
            "catalog:pagination",
            [
                "Here are more matching products from your search.",
                "I found more matching products from the same search.",
                "Here are more options from your search.",
            ],
        )

    if not bool(debug.get("store_overview_request")):
        pagination_offset = int(debug.get("catalog_pagination_offset", 0) or 0)
        pagination_has_more = (
            debug.get("catalog_pagination_has_more")
            if "catalog_pagination_has_more" in debug
            else None
        )
        if is_recommendation_view:
            follow_ups.extend(
                build_show_more_follow_up(
                    products=display_products,
                    attribute_filters=attribute_filters,
                    result_count=result_count,
                    display_count=len(display_products or []),
                    display_offset=pagination_offset,
                    pagination_has_more=pagination_has_more,
                )
            )
        else:
            follow_ups.extend(
                build_conversion_follow_ups(
                    products=display_products,
                    attribute_filters=attribute_filters,
                    user_text=user_text,
                    needs_knowledge=bool(debug.get("workflow_needs_knowledge", False)),
                    result_count=result_count,
                    display_count=len(display_products or []),
                    display_offset=pagination_offset,
                    limit=5,
                    debug_meta=getattr(context, "debug", None),
                )
            )

    return {
        "assistant_text": str(assistant_text or ""),
        "carousel_msg": str(carousel_msg or ""),
        "display_products": list(display_products or []),
        "follow_ups": list(follow_ups or []),
    }
