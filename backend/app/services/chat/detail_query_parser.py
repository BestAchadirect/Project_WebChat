from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

ALLOWED_DETAIL_FIELDS = ("price", "stock", "image", "attributes", "name", "sku")
FIELD_ORDER = {name: idx for idx, name in enumerate(ALLOWED_DETAIL_FIELDS)}
ALLOWED_ATTRIBUTE_FILTERS = (
    "category",
    "color",
    "crystal_color",
    "cz_color",
    "design",
    "gauge",
    "height",
    "jewelry_type",
    "length",
    "material",
    "opal_color",
    "outer_diameter",
    "packing_option",
    "pearl_color",
    "pincher_size",
    "quantity_in_bulk",
    "rack",
    "ring_size",
    "size",
    "size_in_pack",
    "threading",
)
ATTRIBUTE_FILTER_ORDER = (
    "category",
    "jewelry_type",
    "design",
    "color",
    "material",
    "opal_color",
    "pearl_color",
    "crystal_color",
    "cz_color",
    "gauge",
    "length",
    "size",
    "outer_diameter",
    "ring_size",
    "height",
    "threading",
    "packing_option",
    "size_in_pack",
    "quantity_in_bulk",
    "pincher_size",
    "rack",
)

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
    r"\bcategory\b",
    r"\bdesign\b",
    r"\bshape\b",
    r"\blength\b",
    r"\bsize\b",
    r"\bouter diameter\b",
    r"\bdiameter\b",
    r"\bopal color\b",
    r"\bpearl color\b",
    r"\bcrystal color\b",
    r"\bcz color\b",
    r"\bring size\b",
    r"\brack\b",
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
    "opal",
}

_COLOR_SYNONYMS = {
    "opal color": "opal",
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
    "implant grade": "titanium g23",
    "implant-grade": "titanium g23",
    "g23": "titanium g23",
    "titanium": "titanium",
    "surgical steel": "steel",
    "stainless steel": "steel",
    "316l": "steel",
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

_CATEGORY_PATTERNS = {
    "sterilized": "sterilized",
    "sterilised": "sterilized",
}

_DESIGN_PATTERNS = {
    "heart": "heart",
    "star": "star",
    "butterfly": "butterfly",
    "disc": "disc",
    "round": "round",
    "square": "square",
    "flower": "flower",
    "moon": "moon",
    "cross": "cross",
}

_ATTRIBUTE_VALUE_PATTERNS: Dict[str, Sequence[str]] = {
    "category": (
        r"\bcategory(?: is|=| of| for| in)?\s+(?P<value>[a-z0-9][a-z0-9&/;,\- ]{1,60})\b",
    ),
    "design": (
        r"\bdesign(?: is|=| of| with)?\s+(?P<value>[a-z0-9][a-z0-9&/\- ]{1,40})\b",
        r"\bwith\s+(?P<value>[a-z0-9][a-z0-9&/\- ]{1,30})\s+design\b",
        r"\b(?P<value>[a-z0-9][a-z0-9&/\- ]{1,20})\s+shape\b",
        r"\b(?P<value>[a-z0-9][a-z0-9&/\- ]{1,20})-shaped\b",
    ),
    "length": (
        r"\blength(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches)?)\b",
        r"\b(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\s+length\b",
    ),
    "size": (
        r"\bsize(?: is|=| of)?\s+(?P<value>[a-z0-9.]+(?:\s*(?:mm|cm|in|inch|inches))?)\b",
    ),
    "outer_diameter": (
        r"\bouter diameter(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b",
        r"\b(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\s+outer diameter\b",
        r"\bdiameter(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b",
    ),
    "ring_size": (
        r"\bring size(?: is|=| of)?\s+(?P<value>[a-z0-9.]+)\b",
    ),
    "pincher_size": (
        r"\bpincher size(?: is|=| of)?\s+(?P<value>[a-z0-9.]+(?:\s*(?:mm|cm))?)\b",
    ),
    "height": (
        r"\bheight(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b",
    ),
    "packing_option": (
        r"\bpacking option(?: is|=| of)?\s+(?P<value>[a-z0-9][a-z0-9/\- ]{1,30})\b",
        r"\bpack(?:ing)?(?: option)?\s+(?P<value>[a-z0-9][a-z0-9/\- ]{1,30})\b",
    ),
    "size_in_pack": (
        r"\bsize in pack(?: is|=| of)?\s+(?P<value>[a-z0-9.]+)\b",
        r"\bpack size(?: is|=| of)?\s+(?P<value>[a-z0-9.]+)\b",
    ),
    "quantity_in_bulk": (
        r"\bquantity in bulk(?: is|=| of)?\s+(?P<value>\d{1,5})\b",
        r"\bbulk qty(?: is|=| of)?\s+(?P<value>\d{1,5})\b",
        r"\bbulk quantity(?: is|=| of)?\s+(?P<value>\d{1,5})\b",
    ),
    "rack": (
        r"\brack(?: is|=| number| no\.?)?\s+(?P<value>[a-z0-9\-]{1,20})\b",
    ),
    "opal_color": (
        r"\bopal color(?: is|=| of)?\s+(?P<value>[a-z ]{2,20})\b",
        r"\b(?P<value>[a-z ]{2,20})\s+opal\b",
    ),
    "pearl_color": (
        r"\bpearl color(?: is|=| of)?\s+(?P<value>[a-z ]{2,20})\b",
        r"\b(?P<value>[a-z ]{2,20})\s+pearl\b",
    ),
    "crystal_color": (
        r"\bcrystal color(?: is|=| of)?\s+(?P<value>[a-z ]{2,20})\b",
        r"\b(?P<value>[a-z ]{2,20})\s+crystal\b",
    ),
    "cz_color": (
        r"\bcz color(?: is|=| of)?\s+(?P<value>[a-z ]{2,20})\b",
        r"\b(?P<value>[a-z ]{2,20})\s+cz\b",
        r"\bcubic zirconia color(?: is|=| of)?\s+(?P<value>[a-z ]{2,20})\b",
    ),
}

_MEASUREMENT_KEYS = {
    "gauge",
    "length",
    "size",
    "outer_diameter",
    "height",
    "pincher_size",
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
        if mm_match and ("gauge" in text or re.fullmatch(r"\d{1,3}(?:\.\d+)?\s*mm", text)):
            return f"{mm_match.group(1)}mm"
        g_match = re.search(r"\b(\d{1,2})\s*(?:g|gauge)\b", text)
        if g_match:
            return f"{g_match.group(1)}g"
        if re.fullmatch(r"\d{1,2}g", text):
            return text
        return ""

    @staticmethod
    def normalize_measurement_token(value: str) -> str:
        text = DetailQueryParser._normalize_text(value)
        if not text:
            return ""
        match = re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*(mm|cm|in|inch|inches)\b", text)
        if match:
            unit = match.group(2)
            if unit == "inches":
                unit = "inch"
            return f"{match.group(1)}{unit}"
        if re.fullmatch(r"\d{1,3}(?:\.\d+)?", text):
            return text
        return text

    @classmethod
    def normalize_attribute_value(cls, *, key: str, value: Any) -> str:
        clean_key = str(key or "").strip().lower()
        text = cls._normalize_text(str(value or ""))
        if not clean_key or not text:
            return ""
        if clean_key == "gauge":
            return cls.normalize_gauge_token(text) or text
        if clean_key in _MEASUREMENT_KEYS:
            return cls.normalize_measurement_token(text)
        if clean_key in {"ring_size", "size_in_pack", "quantity_in_bulk", "rack"}:
            return re.sub(r"\s+", " ", text)
        if clean_key == "category":
            return re.sub(r"\s*;;\s*", ";;", text)
        if clean_key.endswith("_color"):
            return re.sub(r"^(?:in|with)\s+", "", text).strip()
        return text

    @classmethod
    def clean_attribute_filters(cls, raw_filters: Any) -> Dict[str, str]:
        if not isinstance(raw_filters, dict):
            return {}
        out: Dict[str, str] = {}
        for key, value in raw_filters.items():
            clean_key = str(key or "").strip().lower()
            if clean_key not in ALLOWED_ATTRIBUTE_FILTERS:
                continue
            clean_value = cls.normalize_attribute_value(key=clean_key, value=value)
            if clean_value:
                out[clean_key] = clean_value
        return out

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
        return DetailQueryParser.clean_attribute_filters(raw_filters)

    @classmethod
    def _extract_pattern_value(cls, *, text: str, key: str, patterns: Sequence[str]) -> str:
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = cls.normalize_attribute_value(key=key, value=match.group("value"))
            if value:
                return value
        return ""

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
        for phrase, normalized in _COLOR_SYNONYMS.items():
            if re.search(rf"\b{re.escape(phrase)}\b", text):
                attribute_filters.setdefault("color", normalized)
                break

        for category_token, normalized in _CATEGORY_PATTERNS.items():
            if re.search(rf"\b{re.escape(category_token)}\b", text):
                attribute_filters.setdefault("category", normalized)
                break

        for design_token, normalized in _DESIGN_PATTERNS.items():
            if re.search(
                rf"\b{re.escape(design_token)}(?:\s+shape|\s+design|-shaped|\s+top|\s+tops)?\b",
                text,
            ):
                attribute_filters.setdefault("design", normalized)
                break

        for key, patterns in _ATTRIBUTE_VALUE_PATTERNS.items():
            if key in attribute_filters:
                continue
            extracted = cls._extract_pattern_value(text=text, key=key, patterns=patterns)
            if extracted:
                attribute_filters[key] = extracted

        if "ring_size" in attribute_filters and attribute_filters.get("size") == attribute_filters["ring_size"]:
            attribute_filters.pop("size", None)
        if "size_in_pack" in attribute_filters and attribute_filters.get("size") == attribute_filters["size_in_pack"]:
            attribute_filters.pop("size", None)
        if "pincher_size" in attribute_filters and attribute_filters.get("size") == attribute_filters["pincher_size"]:
            attribute_filters.pop("size", None)

        deduped_fields = sorted(set(requested_fields), key=lambda field: FIELD_ORDER.get(field, 999))
        is_detail_request = bool(deduped_fields or wants_image)
        return DetailQuery(
            requested_fields=deduped_fields,
            attribute_filters=attribute_filters,
            wants_image=wants_image,
            is_detail_request=is_detail_request,
        )
