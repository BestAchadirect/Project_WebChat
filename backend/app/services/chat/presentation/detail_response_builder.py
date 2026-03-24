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

HIGHLIGHT_ATTRIBUTE_ORDER = (
    "category",
    "material",
    "color",
    "design",
    "jewelry_type",
    "gauge",
    "length",
    "size",
    "outer_diameter",
    "ring_size",
    "threading",
)


@dataclass(frozen=True)
class DetailResponsePayload:
    reply_text: str
    carousel_msg: str
    follow_up_questions: List[str]
    product_carousel: List[Any]
    card_policy_reason: str


class DetailResponseBuilder:
    @staticmethod
    def _normalize_attr_key(value: object) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _format_highlight_value(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        lowered = text.lower()
        if text == lowered and any(ch.isalpha() for ch in text):
            return " ".join(part.capitalize() if part.isalpha() else part for part in text.split(" "))
        return text

    @classmethod
    def _get_attr_value(cls, card: Any, key: str) -> str:
        attrs = card.attributes or {}
        wanted = cls._normalize_attr_key(key)
        for raw_key, raw_value in attrs.items():
            if cls._normalize_attr_key(raw_key) != wanted:
                continue
            text = str(raw_value or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _label_for_key(key: str) -> str:
        return str(key or "").replace("_", " ").strip().upper()

    @classmethod
    def _extract_master_code(cls, card: Any) -> str:
        attrs = card.attributes or {}
        for raw_key, raw_value in attrs.items():
            if cls._normalize_attr_key(raw_key) != "master_code":
                continue
            value = str(raw_value or "").strip()
            if value:
                return value
        name_value = str(getattr(card, "name", "") or "").strip()
        if name_value:
            return name_value
        return str(getattr(card, "sku", "") or "").strip()

    @classmethod
    def _group_by_master(cls, display_items: List[Any]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for card in display_items:
            label = cls._extract_master_code(card)
            key = cls._normalize_attr_key(label) or str(getattr(card, "sku", "") or "").strip().lower()
            group = grouped.get(key)
            if group is None:
                group = {"master_code": label, "items": []}
                grouped[key] = group
            group["items"].append(card)
        return list(grouped.values())

    @classmethod
    def _build_attribute_focus_summary(
        cls,
        *,
        display_items: List[Any],
        attribute_filters: Dict[str, str],
    ) -> List[str]:
        highlights: List[str] = []
        seen_labels: set[str] = set()

        def add_highlight(raw_key: str, raw_value: object) -> None:
            key = cls._normalize_attr_key(raw_key)
            value = cls._format_highlight_value(raw_value)
            if not key or not value:
                return
            if key in seen_labels:
                return
            highlights.append(f"[{cls._label_for_key(key)}] {value}")
            seen_labels.add(key)

        normalized_filters = {
            cls._normalize_attr_key(key): str(value or "").strip()
            for key, value in (attribute_filters or {}).items()
            if str(value or "").strip()
        }
        for key in HIGHLIGHT_ATTRIBUTE_ORDER:
            if key in normalized_filters:
                add_highlight(key, normalized_filters[key])

        for key in HIGHLIGHT_ATTRIBUTE_ORDER:
            if key in seen_labels:
                continue
            values: List[str] = []
            for card in display_items:
                value = cls._get_attr_value(card, key)
                if not value:
                    values = []
                    break
                values.append(value)
            unique = {item.lower(): item for item in values}
            if len(unique) == 1 and values:
                add_highlight(key, values[0])
            if len(highlights) >= 4:
                break

        return highlights[:4]

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

    @staticmethod
    def _pick_group_representative(items: List[Any]) -> Any:
        if not items:
            return None
        for card in items:
            if str(getattr(card, "product_url", "") or "").strip() and str(getattr(card, "image_url", "") or "").strip():
                return card
        for card in items:
            if str(getattr(card, "product_url", "") or "").strip():
                return card
        for card in items:
            if str(getattr(card, "image_url", "") or "").strip():
                return card
        return items[0]

    @classmethod
    def _render_image_master_line(cls, *, index: int, master_code: str, representative: Any) -> str:
        image_url = str(getattr(representative, "image_url", "") or "").strip()
        if image_url:
            return f"{index}. Master code: {master_code}; Image: {image_url}"
        return f"{index}. Master code: {master_code}; Image: unavailable"

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
            return DetailResponsePayload(
                reply_text=reply,
                carousel_msg="",
                follow_up_questions=[],
                product_carousel=[],
                card_policy_reason="no_matches",
            )

        image_filtered_matches = [
            card for card in matches
            if str(getattr(card, "image_url", "") or "").strip()
        ]
        source_items = image_filtered_matches if wants_image and image_filtered_matches else matches
        requested_set = {str(field or "").strip().lower() for field in requested_fields}
        image_focus_mode = bool(wants_image) and (not requested_set or requested_set.issubset({"image"}))

        if image_focus_mode:
            grouped_source = cls._group_by_master(source_items)
            selected_groups = grouped_source[: max(1, int(max_matches))]
            display_items = [
                cls._pick_group_representative(list(group.get("items") or []))
                for group in selected_groups
            ]
            display_items = [item for item in display_items if item is not None]
            master_groups = selected_groups
            variant_count = sum(len(list(group.get("items") or [])) for group in selected_groups)
            master_count = len(master_groups)
        else:
            display_items = source_items[: max(1, int(max_matches))]
            master_groups = cls._group_by_master(display_items)
            variant_count = len(display_items)
            master_count = len(master_groups)

        if master_count == 1 and variant_count > 1:
            master_code = str(master_groups[0]["master_code"] or "").strip()
            if image_focus_mode:
                header = f"I found image links for {variant_count} variants in master code {master_code}."
            else:
                header = f"I found {variant_count} variants for master code {master_code}."
        elif master_count > 1 and variant_count > 1:
            if image_focus_mode:
                header = f"I found image links for {master_count} master codes ({variant_count} variants)."
            else:
                header = f"I found {master_count} master styles ({variant_count} variants)."
        else:
            header = (
                "I found 1 matching product."
                if variant_count == 1
                else f"I found {variant_count} matching products."
            )
        attribute_focus_mode = bool(requested_set) and requested_set.issubset({"attributes"})

        lines: List[str] = [header]
        if attribute_focus_mode:
            highlights = cls._build_attribute_focus_summary(
                display_items=display_items,
                attribute_filters=attribute_filters,
            )
            if highlights:
                lines.append("Key details: " + " | ".join(highlights))

            top_masters = [str(group.get("master_code") or "").strip() for group in master_groups]
            top_masters = [code for code in top_masters if code]
            if top_masters:
                if len(top_masters) == 1:
                    lines.append(f"Top master code: [MASTER] {top_masters[0]}")
                else:
                    lines.append(
                        "Top master codes: "
                        + ", ".join([f"[MASTER] {code}" for code in top_masters[:4]])
                    )
        elif image_focus_mode:
            for idx, group in enumerate(master_groups, start=1):
                master_code = str(group.get("master_code") or "").strip()
                representative = cls._pick_group_representative(list(group.get("items") or []))
                if representative is None:
                    continue
                lines.append(
                    cls._render_image_master_line(
                        index=idx,
                        master_code=master_code or str(getattr(representative, "name", "") or "").strip(),
                        representative=representative,
                    )
                )
        else:
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

        show_cards = True
        if image_focus_mode:
            reason = "image_master_grouped"
        elif len(display_items) > 1:
            reason = "multiple_matches"
        else:
            reason = "single_match_text_only"
        follow_ups: List[str] = []
        carousel_msg = ""
        if show_cards:
            if master_count == 1:
                master_code = str(master_groups[0]["master_code"] or "").strip()
                variant_word = "variant" if variant_count == 1 else "variants"
                carousel_msg = (
                    f"Master code {master_code} has {variant_count} {variant_word}. "
                    "Expand to view variant details."
                )
            elif master_count > 1:
                carousel_msg = (
                    f"Showing {master_count} master styles ({variant_count} variants). "
                    "Expand a style to view variant details."
                )

        return DetailResponsePayload(
            reply_text=reply_text,
            carousel_msg=carousel_msg,
            follow_up_questions=follow_ups,
            product_carousel=display_items,
            card_policy_reason=reason,
        )
