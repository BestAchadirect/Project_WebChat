from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List

ALLOWED_DETAIL_FIELDS = ("price", "stock", "image", "attributes", "name", "sku")
FIELD_ORDER = {name: idx for idx, name in enumerate(ALLOWED_DETAIL_FIELDS)}

_PRICE_PATTERNS = (
    r"\bprice\b",
    r"\bcost\b",
    r"\bhow much\b",
)
_STOCK_PATTERNS = (
    r"\bstock\b",
    r"\bavailability\b",
    r"\bin stock\b",
    r"\bout of stock\b",
    r"\bavailable\b",
)
_IMAGE_PATTERNS = (
    r"\bimage\b",
    r"\bpicture\b",
    r"\bphoto\b",
    r"\bpic\b",
)
_ATTRIBUTE_PATTERNS = (
    r"\battribute\b",
    r"\battributes\b",
    r"\bspec\b",
    r"\bspecs\b",
    r"\bdetails\b",
    r"\bmaterial\b",
    r"\bcolor\b",
    r"\bgauge\b",
    r"\bthreading\b",
)

_KNOWN_COLORS = {
    "black",
    "white",
    "clear",
    "blue",
    "red",
    "green",
    "purple",
    "pink",
    "yellow",
    "orange",
    "silver",
    "gold",
    "rose gold",
}

_JEWELRY_TYPE_PATTERNS = {
    "barbell": "barbell",
    "circular barbell": "circular barbell",
    "labret": "labret",
    "ring": "ring",
    "plug": "plug",
    "tunnel": "tunnel",
    "stud": "stud",
}

_MATERIAL_PATTERNS = {
    "titanium g23": "titanium g23",
    "titanium": "titanium",
    "steel": "steel",
    "gold": "gold",
    "silver": "silver",
    "niobium": "niobium",
    "acrylic": "acrylic",
}

_THREADING_PATTERNS = {
    "internal": "internal",
    "externally threaded": "external",
    "external": "external",
    "threadless": "threadless",
}


@dataclass(frozen=True)
class DetailQuery:
    requested_fields: List[str]
    attribute_filters: Dict[str, str]
    wants_image: bool
    is_detail_request: bool


class DetailQueryParser:
    @staticmethod
    def _normalize_text(value: str) -> str:
        lowered = (value or "").strip().lower()
        lowered = re.sub(r"\s+", " ", lowered)
        return lowered

    @staticmethod
    def normalize_gauge_token(value: str) -> str:
        text = DetailQueryParser._normalize_text(value)
        if not text:
            return ""
        mm_match = re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*mm\b", text)
        if mm_match:
            return f"{mm_match.group(1)}mm"
        g_match = re.search(r"\b(\d{1,2})\s*(?:g|gauge)\b", text)
        if g_match:
            return f"{g_match.group(1)}g"
        if re.fullmatch(r"\d{1,2}g", text):
            return text
        return ""

    @staticmethod
    def _clean_nlu_fields(raw_fields: Any) -> List[str]:
        if not isinstance(raw_fields, list):
            return []
        clean: List[str] = []
        for item in raw_fields:
            field = str(item or "").strip().lower()
            if field in ALLOWED_DETAIL_FIELDS and field not in clean:
                clean.append(field)
        return clean

    @staticmethod
    def _clean_nlu_filters(raw_filters: Any) -> Dict[str, str]:
        if not isinstance(raw_filters, dict):
            return {}
        out: Dict[str, str] = {}
        for key, value in raw_filters.items():
            k = str(key or "").strip().lower()
            v = str(value or "").strip()
            if not k or not v:
                continue
            if k == "gauge":
                v = DetailQueryParser.normalize_gauge_token(v)
            out[k] = v
        return out

    @classmethod
    def parse(cls, *, user_text: str, nlu_data: Dict[str, Any]) -> DetailQuery:
        text = cls._normalize_text(user_text or "")
        requested_fields = cls._clean_nlu_fields((nlu_data or {}).get("requested_fields"))
        attribute_filters = cls._clean_nlu_filters((nlu_data or {}).get("attribute_filters"))
        wants_image = bool((nlu_data or {}).get("wants_image", False))

        for pattern in _PRICE_PATTERNS:
            if re.search(pattern, text):
                requested_fields.append("price")
                break
        for pattern in _STOCK_PATTERNS:
            if re.search(pattern, text):
                requested_fields.append("stock")
                break
        for pattern in _IMAGE_PATTERNS:
            if re.search(pattern, text):
                requested_fields.append("image")
                wants_image = True
                break
        for pattern in _ATTRIBUTE_PATTERNS:
            if re.search(pattern, text):
                requested_fields.append("attributes")
                break

        gauge = cls.normalize_gauge_token(text)
        if gauge and (gauge.endswith("g") or gauge.endswith("mm")):
            attribute_filters.setdefault("gauge", gauge)

        for jewelry_type, normalized in _JEWELRY_TYPE_PATTERNS.items():
            if re.search(rf"\b{re.escape(jewelry_type)}s?\b", text):
                attribute_filters.setdefault("jewelry_type", normalized)

        for material, normalized in _MATERIAL_PATTERNS.items():
            if re.search(rf"\b{re.escape(material)}\b", text):
                attribute_filters.setdefault("material", normalized)

        for threading, normalized in _THREADING_PATTERNS.items():
            if re.search(rf"\b{re.escape(threading)}\b", text):
                attribute_filters.setdefault("threading", normalized)

        for color in sorted(_KNOWN_COLORS, key=lambda value: -len(value)):
            if re.search(rf"\b{re.escape(color)}\b", text):
                attribute_filters.setdefault("color", color)
                break

        deduped_fields = sorted(set(requested_fields), key=lambda field: FIELD_ORDER.get(field, 999))
        is_detail_request = bool(deduped_fields or attribute_filters or wants_image)
        return DetailQuery(
            requested_fields=deduped_fields,
            attribute_filters=attribute_filters,
            wants_image=wants_image,
            is_detail_request=is_detail_request,
        )
