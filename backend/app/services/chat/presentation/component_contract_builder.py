from __future__ import annotations

from typing import Any, Callable, Dict, List, Sequence

from app.schemas.chat import (
    ChatComponent,
    ChatComponentType,
    ProductCard,
    assistant_message_component,
    quick_replies_component,
)
from app.services.chat.presentation import component_contract


def finalize_contract_components(
    *,
    component_list: Sequence[ChatComponent],
    assistant_text: str,
    follow_ups: Sequence[str],
    display_products: Sequence[Any],
    dedupe_follow_up_questions: Callable[..., List[str]],
    component_type_name: Callable[[Any], str],
    to_product_card: Callable[[Any], ProductCard],
) -> Dict[str, Any]:
    deduped_follow_ups = dedupe_follow_up_questions(list(follow_ups or []), limit=5)
    rebuilt_components: List[ChatComponent] = []
    clarify_present = False
    for component in list(component_list or []):
        kind = component_type_name(component)
        if kind in {"assistant_message", "quick_replies"}:
            continue
        if kind == "clarify":
            clarify_present = True
            clarify_data = dict(getattr(component, "data", {}) or {})
            rebuilt_components.append(
                ChatComponent(type=ChatComponentType.CLARIFY, data=clarify_data)
            )
            continue
        rebuilt_components.append(component)

    assistant_component = assistant_message_component(str(assistant_text or ""))
    if assistant_component is not None:
        rebuilt_components.insert(0, assistant_component)

    quick_replies = None if clarify_present else quick_replies_component(list(deduped_follow_ups or []))
    if quick_replies is not None:
        rebuilt_components.append(quick_replies)

    product_carousel = component_contract.product_cards_from_components(rebuilt_components)
    if not product_carousel and list(display_products or []):
        product_carousel = [to_product_card(item) for item in list(display_products or [])]

    return {
        "components": rebuilt_components,
        "product_carousel": product_carousel,
        "follow_up_questions": list(deduped_follow_ups or []),
    }
