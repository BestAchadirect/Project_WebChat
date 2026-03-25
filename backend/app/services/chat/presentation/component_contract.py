from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.schemas.chat import ChatComponent, ChatResponse, ProductCard


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
            text = str(component["data"].get(key) or "").strip()
            if text:
                return text
    return ""


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
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            out.append(text)
    return out


def assistant_text_from_response(response: ChatResponse) -> str:
    text = assistant_text_from_components(getattr(response, "components", []))
    if text:
        return text
    return str(getattr(response, "reply_text", "") or "").strip()


def product_cards_from_response(response: ChatResponse) -> List[ProductCard]:
    cards = product_cards_from_components(getattr(response, "components", []))
    if cards:
        return cards
    return list(getattr(response, "product_carousel", []) or [])


def follow_up_questions_from_response(response: ChatResponse) -> List[str]:
    items = follow_up_questions_from_components(getattr(response, "components", []))
    if items:
        return items
    return []


def upsert_quick_replies_component(
    response: ChatResponse,
    questions: List[str],
    *,
    actions_by_label: Dict[str, Dict[str, Any]] | None = None,
) -> None:
    clean = [str(item or "").strip() for item in list(questions or []) if str(item or "").strip()]
    action_lookup = {
        str(label or "").strip().lower(): dict(action or {})
        for label, action in dict(actions_by_label or {}).items()
        if str(label or "").strip() and isinstance(action, dict)
    }
    updated: List[ChatComponent] = []
    for component in list(getattr(response, "components", []) or []):
        kind = _component_type(component)
        if kind == "quick_replies":
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
    if clean:
        items: List[Any] = []
        for label in clean:
            action = action_lookup.get(label.lower())
            if action and str(action.get("action") or "").strip():
                payload = action.get("payload")
                item: Dict[str, Any] = {
                    "label": label,
                    "action": str(action.get("action") or "").strip(),
                }
                if isinstance(payload, dict) and payload:
                    item["payload"] = dict(payload)
                items.append(item)
                continue
            items.append(label)
        updated.append(ChatComponent(type="quick_replies", data={"items": items}))
    response.components = updated
