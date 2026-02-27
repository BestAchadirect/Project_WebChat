from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

FIELD_LABELS = {
    "price": "Price",
    "stock": "Stock",
    "image": "Image",
    "attributes": "Attributes",
    "name": "Name",
    "sku": "SKU",
}


@dataclass(frozen=True)
class DetailResponsePayload:
    reply_text: str
    carousel_msg: str
    follow_up_questions: List[str]
    product_carousel: List[Any]
    card_policy_reason: str


class DetailResponseBuilder:
    @staticmethod
    def _format_stock(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return "unavailable"
        normalized = text.lower().replace("stockstatus.", "")
        if normalized == "in_stock":
            return "in stock"
        if normalized == "out_of_stock":
            return "out of stock"
        return text

    @staticmethod
    def _truthy_attributes(card: Any) -> Dict[str, str]:
        attrs = card.attributes or {}
        out: Dict[str, str] = {}
        for key, value in attrs.items():
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            out[str(key)] = text
        return out

    @classmethod
    def _render_product_line(
        cls,
        *,
        index: int,
        card: Any,
        requested_fields: List[str],
        missing_fields: List[str],
    ) -> str:
        parts: List[str] = []
        if "name" in requested_fields:
            parts.append(f"Name: {card.name}")
        parts.append(f"SKU: {card.sku}")
        if "price" in requested_fields:
            if card.price is None:
                parts.append("Price: unavailable")
            else:
                parts.append(f"Price: {card.price} {card.currency}")
        if "stock" in requested_fields:
            parts.append(f"Stock: {cls._format_stock(card.stock_status)}")
        if "image" in requested_fields:
            parts.append(f"Image: {card.image_url}" if card.image_url else "Image: unavailable")
        if "attributes" in requested_fields:
            attrs = cls._truthy_attributes(card)
            if attrs:
                rendered = ", ".join([f"{key}={value}" for key, value in sorted(attrs.items())])
                parts.append(f"Attributes: {rendered}")
            else:
                parts.append("Attributes: unavailable")
        if missing_fields:
            labels = [FIELD_LABELS.get(field, field) for field in missing_fields]
            parts.append("Missing: " + ", ".join(labels))
        return f"{index}. " + "; ".join(parts)

    @classmethod
    def build_detail_reply(
        cls,
        *,
        matches: List[Any],
        requested_fields: List[str],
        attribute_filters: Dict[str, str],
        missing_fields_by_product: Dict[str, List[str]],
        wants_image: bool,
        max_matches: int,
    ) -> DetailResponsePayload:
        if not matches:
            reply = "I couldn't find a product that matches those details."
            if attribute_filters:
                filters_text = ", ".join([f"{k}={v}" for k, v in sorted(attribute_filters.items())])
                reply += f" Checked filters: {filters_text}."
            follow_ups = [
                "Share a SKU or product code for an exact match.",
                "Try fewer filters and ask again.",
            ]
            return DetailResponsePayload(
                reply_text=reply,
                carousel_msg="",
                follow_up_questions=follow_ups,
                product_carousel=[],
                card_policy_reason="no_matches",
            )

        display_items = matches[: max(1, int(max_matches))]
        header = (
            f"I found {len(display_items)} matching product."
            if len(display_items) == 1
            else f"I found {len(display_items)} matching products."
        )
        lines: List[str] = [header]
        for idx, card in enumerate(display_items, start=1):
            missing = missing_fields_by_product.get(str(card.id), [])
            lines.append(
                cls._render_product_line(
                    index=idx,
                    card=card,
                    requested_fields=requested_fields,
                    missing_fields=missing,
                )
            )
        reply_text = "\n".join(lines)

        if wants_image:
            show_cards = True
            reason = "image_requested"
        elif len(display_items) > 1:
            show_cards = True
            reason = "multiple_matches"
        else:
            show_cards = False
            reason = "single_match_text_only"

        follow_ups: List[str] = []
        if len(display_items) > 1:
            follow_ups.append("Tell me the SKU for exact item details.")
        if wants_image and any(not card.image_url for card in display_items):
            follow_ups.append("Some items have no image. Ask for price/stock instead.")

        return DetailResponsePayload(
            reply_text=reply_text,
            carousel_msg="Matching products are shown below." if show_cards else "",
            follow_up_questions=follow_ups,
            product_carousel=display_items if show_cards else [],
            card_policy_reason=reason,
        )
