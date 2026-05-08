from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.schemas.chat import ChatComponent, ChatResponse, ProductCard, sanitize_assistant_text, sanitize_chat_component

FOLLOW_UP_TEXT_PLACEMENT = "after_quick_replies"


def _component_type(component: Any) -> str:
    if isinstance(component, ChatComponent):
        raw = component.type
        return str(getattr(raw, "value", raw) or "").strip().lower()
    if isinstance(component, dict):
        raw = component.get("type")
        return str(getattr(raw, "value", raw) or "").strip().lower()
    return ""


def _component_data(component: Any) -> Dict[str, Any]:
    if isinstance(component, ChatComponent):
        return dict(component.data or {})
    if isinstance(component, dict):
        raw = component.get("data")
        return dict(raw or {}) if isinstance(raw, dict) else {}
    return {}


def _normalize_components(components: Iterable[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for component in list(components or []):
        kind = _component_type(component)
        if not kind:
            continue
        out.append({"type": kind, "data": _component_data(component)})
    return out


def assistant_text_from_components(components: Iterable[Any]) -> str:
    normalized = _normalize_components(components)
    preferred = (
        ("assistant_message", "text"),
        ("knowledge_answer", "answer"),
        ("clarify", "message"),
        ("error", "message"),
    )
    for kind, key in preferred:
        for component in normalized:
            if component["type"] != kind:
                continue
            if _is_follow_up_text_payload(component["type"], component["data"]):
                continue
            text = str(component["data"].get(key) or "").strip()
            text = sanitize_assistant_text(text)
            if text:
                return text
    return ""


def _is_follow_up_text_payload(kind: str, data: Dict[str, Any]) -> bool:
    return (
        str(kind or "").strip().lower() == "assistant_message"
        and str(data.get("placement") or "").strip().lower() == FOLLOW_UP_TEXT_PLACEMENT
    )


def is_follow_up_text_component(component: Any) -> bool:
    return _is_follow_up_text_payload(_component_type(component), _component_data(component))


def _card_from_component_payload(raw: Dict[str, Any]) -> ProductCard | None:
    product_id = str(raw.get("product_id") or raw.get("id") or "").strip()
    if not product_id:
        return None
    stock_status = str(raw.get("stock_status") or "").strip().lower()
    if not stock_status:
        in_stock = raw.get("in_stock")
        if isinstance(in_stock, bool):
            stock_status = "in_stock" if in_stock else "out_of_stock"
    payload = {
        "id": product_id,
        "object_id": raw.get("object_id"),
        "sku": str(raw.get("sku") or "").strip(),
        "legacy_sku": list(raw.get("legacy_sku") or []),
        "name": str(raw.get("title") or raw.get("name") or "").strip(),
        "description": raw.get("description"),
        "price": float(raw.get("price") or 0.0),
        "currency": str(raw.get("currency") or "USD"),
        "stock_status": stock_status or None,
        "image_url": raw.get("image_url"),
        "product_url": raw.get("product_url"),
        "attributes": dict(raw.get("attributes") or {}),
    }
    if not payload["sku"] or not payload["name"]:
        return None
    try:
        return ProductCard.model_validate(payload)
    except Exception:
        return None


def product_cards_from_components(components: Iterable[Any]) -> List[ProductCard]:
    normalized = _normalize_components(components)
    cards: List[ProductCard] = []
    seen: set[str] = set()
    for component in normalized:
        kind = component["type"]
        data = component["data"]
        if kind == "product_cards":
            items = list(data.get("cards") or [])
        elif kind == "product_detail":
            product = data.get("product")
            items = [product] if isinstance(product, dict) else []
        else:
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            card = _card_from_component_payload(item)
            if card is None:
                continue
            key = str(card.id)
            if key in seen:
                continue
            seen.add(key)
            cards.append(card)
    return cards


def follow_up_questions_from_components(components: Iterable[Any]) -> List[str]:
    normalized = _normalize_components(components)
    seen: set[str] = set()
    out: List[str] = []
    for component in normalized:
        kind = component["type"]
        data = component["data"]
        if kind == "quick_replies":
            items = list(data.get("items") or data.get("questions") or [])
        elif kind == "clarify":
            items = list(data.get("suggestions") or [])
        else:
            continue
        for raw in items:
            if isinstance(raw, dict):
                text = str(raw.get("label") or raw.get("text") or raw.get("question") or raw.get("message") or "").strip()
            else:
                text = str(raw or "").strip()
            text = sanitize_assistant_text(text)
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            out.append(text)
    return out


def assistant_text_from_response(response: ChatResponse) -> str:
    return assistant_text_from_components(getattr(response, "components", []))


def product_cards_from_response(response: ChatResponse) -> List[ProductCard]:
    return product_cards_from_components(getattr(response, "components", []))


def follow_up_questions_from_response(response: ChatResponse) -> List[str]:
    items = follow_up_questions_from_components(getattr(response, "components", []))
    if items:
        return items
    return []


def _action_for_label(label: str, actions_by_label: Dict[str, Dict[str, Any]] | None) -> Dict[str, Any]:
    lookup = {
        str(raw_label or "").strip().lower(): dict(action or {})
        for raw_label, action in dict(actions_by_label or {}).items()
        if str(raw_label or "").strip() and isinstance(action, dict)
    }
    return lookup.get(str(label or "").strip().lower(), {})


def _is_pagination_follow_up(label: str, action: Dict[str, Any] | None = None) -> bool:
    action_name = str((action or {}).get("action") or "").strip().lower()
    if action_name == "catalog_pagination":
        return True
    return str(label or "").strip().lower().startswith("show more")


def pagination_follow_ups(
    questions: List[str],
    *,
    actions_by_label: Dict[str, Dict[str, Any]] | None = None,
) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in list(questions or []):
        label = str(raw or "").strip()
        if not label:
            continue
        action = _action_for_label(label, actions_by_label)
        if not _is_pagination_follow_up(label, action):
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def narrative_follow_ups(
    questions: List[str],
    *,
    actions_by_label: Dict[str, Dict[str, Any]] | None = None,
) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in list(questions or []):
        label = str(raw or "").strip()
        if not label:
            continue
        action = _action_for_label(label, actions_by_label)
        if _is_pagination_follow_up(label, action):
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def _follow_up_topic(label: str) -> str:
    text = str(label or "").strip().strip(".")
    if not text:
        return ""
    lower = text.lower()
    replacements = (
        ("show me ", ""),
        ("show ", ""),
        ("try ", ""),
        ("focus on ", ""),
    )
    for prefix, replacement in replacements:
        if lower.startswith(prefix):
            text = replacement + text[len(prefix):].strip()
            break
    if text.lower() == "how can i contact you?":
        return "contact information"
    return text.strip().rstrip("?")


def follow_up_sentence(questions: List[str], *, limit: int = 3) -> str:
    topics: List[str] = []
    seen: set[str] = set()
    for raw in list(questions or []):
        topic = _follow_up_topic(str(raw or ""))
        key = topic.lower()
        if not topic or key in seen:
            continue
        seen.add(key)
        topics.append(topic)
        if len(topics) >= max(1, int(limit or 1)):
            break
    if not topics:
        return ""
    bullets = "\n".join(f"- {topic}" for topic in topics)
    return sanitize_assistant_text(f"If you want, I can help you:\n{bullets}")


def append_follow_up_sentence(assistant_text: str, questions: List[str]) -> str:
    base = str(assistant_text or "").strip()
    sentence = follow_up_sentence(questions)
    if not sentence:
        return base
    if not base:
        return sentence
    if sentence.lower() in base.lower():
        return base
    return f"{base.rstrip()} {sentence}"


def follow_up_text_component(questions: List[str]) -> ChatComponent | None:
    sentence = follow_up_sentence(questions)
    if not sentence:
        return None
    return ChatComponent(
        type="assistant_message",
        data={
            "text": sentence,
            "placement": FOLLOW_UP_TEXT_PLACEMENT,
        },
    )


def upsert_quick_replies_component(
    response: ChatResponse,
    questions: List[str],
    *,
    actions_by_label: Dict[str, Dict[str, Any]] | None = None,
) -> None:
    clean = [str(item or "").strip() for item in list(questions or []) if str(item or "").strip()]
    clarify_present = any(_component_type(component) == "clarify" for component in list(getattr(response, "components", []) or []))
    quick_reply_labels = pagination_follow_ups(clean, actions_by_label=actions_by_label)
    narrative_labels = [] if clarify_present else narrative_follow_ups(clean, actions_by_label=actions_by_label)
    updated: List[ChatComponent] = []
    for component in list(getattr(response, "components", []) or []):
        kind = _component_type(component)
        if kind == "quick_replies":
            continue
        if is_follow_up_text_component(component):
            continue
        if kind == "assistant_message":
            updated.append(ChatComponent(type="assistant_message", data=_component_data(component)))
            continue
        if kind == "clarify":
            data = _component_data(component)
            if clean:
                data["suggestions"] = list(clean)
            elif "suggestions" in data:
                data.pop("suggestions", None)
            updated.append(ChatComponent(type="clarify", data=data))
            continue
        if isinstance(component, ChatComponent):
            updated.append(component)
        elif isinstance(component, dict):
            updated.append(
                ChatComponent(
                    type=str(component.get("type") or "").strip().lower(),
                    data=_component_data(component),
                )
            )
    if quick_reply_labels:
        items: List[Any] = []
        for label in quick_reply_labels:
            action = _action_for_label(label, actions_by_label)
            if action and str(action.get("action") or "").strip():
                payload = action.get("payload")
                item: Dict[str, Any] = {
                    "label": sanitize_assistant_text(label),
                    "action": str(action.get("action") or "").strip(),
                }
                if isinstance(payload, dict) and payload:
                    item["payload"] = dict(payload)
                items.append(item)
                continue
            items.append(
                {
                    "label": label,
                    "action": "catalog_pagination",
                    "payload": {
                        "kind": "catalog_pagination",
                        "label": sanitize_assistant_text(label),
                    },
                }
            )
        if items:
            updated.append(ChatComponent(type="quick_replies", data={"items": items}))
    follow_up_component = follow_up_text_component(narrative_labels)
    if follow_up_component is not None:
        updated.append(follow_up_component)
    response.components = [sanitize_chat_component(component) for component in updated]
