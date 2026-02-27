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

    @staticmethod
    def _append_unique(items: List[str], value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        if text in items:
            return
        items.append(text)

    @classmethod
    def _build_follow_ups(
        cls,
        *,
        display_items: List[Any],
        requested_fields: List[str],
        attribute_filters: Dict[str, str],
        wants_image: bool,
    ) -> List[str]:
        follow_ups: List[str] = []
        requested = {str(field or "").strip().lower() for field in requested_fields}
        first_sku = str(getattr(display_items[0], "sku", "") or "").strip() if display_items else ""
        second_sku = str(getattr(display_items[1], "sku", "") or "").strip() if len(display_items) > 1 else ""

        if len(display_items) > 1:
            if first_sku:
                cls._append_unique(follow_ups, f"Show full details for SKU {first_sku}.")
            if first_sku and second_sku:
                cls._append_unique(follow_ups, f"Compare SKU {first_sku} and SKU {second_sku}.")
            if "stock" not in requested:
                cls._append_unique(follow_ups, "Show in-stock items only.")
            if "price" not in requested:
                cls._append_unique(follow_ups, "Show prices for these items.")
            for key, label in (
                ("material", "material"),
                ("color", "color"),
                ("gauge", "gauge"),
                ("threading", "threading"),
            ):
                if key not in attribute_filters:
                    cls._append_unique(follow_ups, f"Filter these results by {label}.")
                    break
        elif first_sku:
            if "price" not in requested:
                cls._append_unique(follow_ups, f"Show price for SKU {first_sku}.")
            if "stock" not in requested:
                cls._append_unique(follow_ups, f"Show stock for SKU {first_sku}.")
            if "image" not in requested:
                cls._append_unique(follow_ups, f"Show image for SKU {first_sku}.")
            if "attributes" not in requested:
                cls._append_unique(follow_ups, f"Show specs for SKU {first_sku}.")

        if wants_image and any(not getattr(card, "image_url", None) for card in display_items):
            cls._append_unique(follow_ups, "Some items have no image. Ask for price/stock instead.")
        return follow_ups[:5]

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
            return DetailResponsePayload(
                reply_text=reply,
                carousel_msg="",
                follow_up_questions=[],
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

        follow_ups = cls._build_follow_ups(
            display_items=display_items,
            requested_fields=requested_fields,
            attribute_filters=attribute_filters,
            wants_image=wants_image,
        )

        return DetailResponsePayload(
            reply_text=reply_text,
            carousel_msg="Matching products are shown below." if show_cards else "",
            follow_up_questions=follow_ups,
            product_carousel=display_items if show_cards else [],
            card_policy_reason=reason,
        )
