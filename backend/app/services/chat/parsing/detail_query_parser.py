from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.services.chat.parsing.attribute_normalization import (
    clean_attribute_filters as shared_clean_attribute_filters,
    normalize_attribute_value as shared_normalize_attribute_value,
    normalize_gauge_token as shared_normalize_gauge_token,
    normalize_lexical_alias_map as shared_normalize_lexical_alias_map,
    normalize_measurement_token as shared_normalize_measurement_token,
    normalize_text as shared_normalize_text,
)
from app.services.chat.parsing.parser_rule_types import ParserRuleSet, empty_rule_set

ALLOWED_DETAIL_FIELDS = ("price", "stock", "image", "attributes", "name", "sku")
ALLOWED_DETAIL_FIELD_SET = set(ALLOWED_DETAIL_FIELDS)
FIELD_ORDER = {name: idx for idx, name in enumerate(ALLOWED_DETAIL_FIELDS)}


@dataclass(frozen=True)
class DetailQuery:
    requested_fields: List[str]
    attribute_filters: Dict[str, str]
    wants_image: bool
    is_detail_request: bool
    semantic_hints: List[str] = field(default_factory=list)
    clarify_focus: str = ""


class DetailQueryParser:
    _EMPTY_RULE_SET = empty_rule_set()
    _OPAL_FALLBACK_ATTRIBUTES = ("stone", "opal_color", "color")
    _BASIC_PRODUCT_FILTER_PATTERNS = {
        "jewelry_type": (
            (r"\blabrets?\b", "labret"),
            (r"\bbarbells?\b", "barbell"),
            (r"\brings?\b", "ring"),
            (r"\bhoops?\b", "ring"),
            (r"\bplugs?\b", "plug"),
            (r"\btunnels?\b", "tunnel"),
            (r"\bstuds?\b", "stud"),
        ),
        "material": (
            (r"\btitanium\b", "titanium"),
            (r"\bsteel\b", "steel"),
            (r"\bgold\b", "gold"),
            (r"\bsilver\b", "silver"),
            (r"\bniobium\b", "niobium"),
            (r"\bacrylic\b", "acrylic"),
        ),
    }

    @staticmethod
    def _normalize_text(value: str) -> str:
        return shared_normalize_text(value)

    @staticmethod
    def normalize_gauge_token(value: str) -> str:
        return shared_normalize_gauge_token(value)

    @staticmethod
    def normalize_measurement_token(value: str) -> str:
        return shared_normalize_measurement_token(value)

    @classmethod
    def normalize_attribute_value(
        cls,
        *,
        key: str,
        value: Any,
        alias_map: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> str:
        return shared_normalize_attribute_value(key=key, value=value, alias_map=alias_map)

    @classmethod
    def clean_attribute_filters(
        cls,
        raw_filters: Any,
        *,
        alias_map: Optional[Dict[str, Dict[str, str]]] = None,
        allowed_attribute_filters: Optional[Sequence[str]] = None,
    ) -> Dict[str, str]:
        return shared_clean_attribute_filters(
            raw_filters,
            alias_map=alias_map,
            allowed_attribute_filters=allowed_attribute_filters,
        )

    @staticmethod
    def _clean_nlu_fields(raw_fields: Any) -> List[str]:
        if not isinstance(raw_fields, list):
            return []
        clean: List[str] = []
        for item in raw_fields:
            field = str(item or "").strip().lower()
            if field in ALLOWED_DETAIL_FIELD_SET and field not in clean:
                clean.append(field)
        return clean

    @staticmethod
    def _clean_nlu_filters(
        raw_filters: Any,
        *,
        alias_map: Optional[Dict[str, Dict[str, str]]] = None,
        allowed_attribute_filters: Optional[Sequence[str]] = None,
    ) -> Dict[str, str]:
        return DetailQueryParser.clean_attribute_filters(
            raw_filters,
            alias_map=alias_map,
            allowed_attribute_filters=allowed_attribute_filters,
        )

    @classmethod
    def _build_detection_alias_map(
        cls,
        alias_map: Optional[Dict[str, Dict[str, str]]],
    ) -> Dict[str, Dict[str, str]]:
        return shared_normalize_lexical_alias_map(dict(alias_map or {}))

    @classmethod
    def _extract_alias_match(
        cls,
        *,
        text: str,
        attribute: str,
        alias_map: Dict[str, Dict[str, str]],
    ) -> str:
        bucket = dict(alias_map.get(attribute, {}) or {})
        if not bucket:
            return ""
        terms = sorted(bucket.keys(), key=lambda value: (-len(value), value))
        for term in terms:
            normalized_term = cls._normalize_text(term)
            if not normalized_term or len(normalized_term) < 2:
                continue
            if re.search(rf"\b{re.escape(normalized_term)}\b", text):
                canonical = str(bucket.get(term) or "").strip().lower()
                if canonical:
                    return canonical
        return ""

    @classmethod
    def _extract_pattern_value(
        cls,
        *,
        text: str,
        key: str,
        patterns: Sequence[str],
        alias_map: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> str:
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = cls.normalize_attribute_value(
                key=key,
                value=match.group("value"),
                alias_map=alias_map,
            )
            if value:
                return value
        return ""

    @classmethod
    def _maybe_infer_opal_filter(
        cls,
        *,
        text: str,
        attribute_filters: Dict[str, str],
        alias_map: Dict[str, Dict[str, str]],
        allowed_attribute_filters: Sequence[str],
    ) -> None:
        if any(key in attribute_filters for key in cls._OPAL_FALLBACK_ATTRIBUTES):
            return
        if not re.search(r"\bopal\b", text):
            return

        allowed = {
            str(item or "").strip().lower()
            for item in list(allowed_attribute_filters or [])
            if str(item or "").strip()
        }

        for attribute in cls._OPAL_FALLBACK_ATTRIBUTES:
            if allowed and attribute not in allowed:
                continue
            bucket = dict(alias_map.get(attribute, {}) or {})
            if not bucket:
                continue
            canonical = str(bucket.get("opal") or "").strip().lower()
            if not canonical:
                for _, candidate in bucket.items():
                    candidate_norm = str(candidate or "").strip().lower()
                    if candidate_norm == "opal":
                        canonical = candidate_norm
                        break
            if canonical:
                normalized = cls.normalize_attribute_value(key=attribute, value=canonical, alias_map=alias_map) or canonical
                attribute_filters[attribute] = normalized
                return

        # Safe fallback when opal exists in text but alias coverage is incomplete.
        for attribute in ("opal_color", "color"):
            if allowed and attribute not in allowed:
                continue
            normalized = cls.normalize_attribute_value(key=attribute, value="opal", alias_map=alias_map) or "opal"
            attribute_filters[attribute] = normalized
            return

    @classmethod
    def _maybe_infer_sterilization_filter(
        cls,
        *,
        text: str,
        attribute_filters: Dict[str, str],
        alias_map: Dict[str, Dict[str, str]],
        allowed_attribute_filters: Sequence[str],
    ) -> None:
        if "finish" in attribute_filters:
            existing = cls._normalize_text(str(attribute_filters.get("finish") or ""))
            if existing in {"sterilized", "sterilised", "sterilization", "sterilisation", "sterile"}:
                attribute_filters["finish"] = "sterilized"
            return

        allowed = {
            str(item or "").strip().lower()
            for item in list(allowed_attribute_filters or [])
            if str(item or "").strip()
        }
        if allowed and "finish" not in allowed:
            return

        if not re.search(
            r"\b(?:steriliz(?:ed|e)|sterilis(?:ed|e)|pre[- ]?steriliz(?:ed|e)|sterile)\b",
            text,
        ):
            return

        normalized = cls.normalize_attribute_value(key="finish", value="sterilized", alias_map=alias_map) or "sterilized"
        attribute_filters["finish"] = normalized

    @classmethod
    def _prune_ambiguous_finish_filter(
        cls,
        *,
        text: str,
        attribute_filters: Dict[str, str],
    ) -> None:
        finish_value = cls._normalize_text(str(attribute_filters.get("finish") or ""))
        if finish_value != "sterilized":
            return
        has_ambiguous_sterilization = bool(re.search(r"\b(?:sterilization|sterilisation)\b", text))
        has_explicit_finish_value = bool(
            re.search(r"\b(?:steriliz(?:ed|e)|sterilis(?:ed|e)|pre[- ]?steriliz(?:ed|e)|sterile)\b", text)
        )
        if has_ambiguous_sterilization and not has_explicit_finish_value:
            attribute_filters.pop("finish", None)

    @classmethod
    def _maybe_infer_basic_product_filters(
        cls,
        *,
        text: str,
        attribute_filters: Dict[str, str],
        alias_map: Dict[str, Dict[str, str]],
    ) -> None:
        for key, pattern_map in cls._BASIC_PRODUCT_FILTER_PATTERNS.items():
            if key in attribute_filters:
                continue
            for pattern, canonical in pattern_map:
                if not re.search(pattern, text):
                    continue
                normalized = cls.normalize_attribute_value(key=key, value=canonical, alias_map=alias_map) or canonical
                if normalized:
                    attribute_filters[key] = normalized
                    break

    @staticmethod
    def _append_requested_field_if_matched(
        *,
        text: str,
        patterns: Sequence[str],
        field: str,
        requested_fields: List[str],
    ) -> None:
        for pattern in patterns:
            if re.search(pattern, text):
                requested_fields.append(field)
                break

    @classmethod
    def parse(
        cls,
        *,
        user_text: str,
        nlu_data: Dict[str, Any],
        alias_map: Optional[Dict[str, Dict[str, str]]] = None,
        parser_rules: Optional[ParserRuleSet] = None,
    ) -> DetailQuery:
        active_rules = parser_rules or cls._EMPTY_RULE_SET
        detection_alias_map = cls._build_detection_alias_map(alias_map)
        text = cls._normalize_text(user_text or "")
        requested_fields = cls._clean_nlu_fields((nlu_data or {}).get("requested_fields"))
        attribute_filters = cls._clean_nlu_filters(
            (nlu_data or {}).get("attribute_filters"),
            alias_map=detection_alias_map,
            allowed_attribute_filters=list(active_rules.allowed_attribute_filters),
        )
        wants_image = bool((nlu_data or {}).get("wants_image", False))

        requested_patterns = dict(active_rules.requested_field_patterns or {})
        cls._append_requested_field_if_matched(
            text=text,
            patterns=list(requested_patterns.get("price", [])),
            field="price",
            requested_fields=requested_fields,
        )
        cls._append_requested_field_if_matched(
            text=text,
            patterns=list(requested_patterns.get("stock", [])),
            field="stock",
            requested_fields=requested_fields,
        )
        before_image_count = len(requested_fields)
        cls._append_requested_field_if_matched(
            text=text,
            patterns=list(requested_patterns.get("image", [])),
            field="image",
            requested_fields=requested_fields,
        )
        if len(requested_fields) > before_image_count:
            wants_image = True
        cls._append_requested_field_if_matched(
            text=text,
            patterns=list(requested_patterns.get("attributes", [])),
            field="attributes",
            requested_fields=requested_fields,
        )

        gauge = cls.normalize_gauge_token(text)
        if gauge and (gauge.endswith("g") or gauge.endswith("mm")):
            attribute_filters.setdefault("gauge", gauge)

        for attribute in list(active_rules.detection_attribute_order or []):
            if attribute in attribute_filters:
                continue
            matched = cls._extract_alias_match(
                text=text,
                attribute=attribute,
                alias_map=detection_alias_map,
            )
            if matched:
                attribute_filters.setdefault(attribute, matched)

        for key, patterns in dict(active_rules.value_extract_patterns or {}).items():
            if key in attribute_filters:
                continue
            extracted = cls._extract_pattern_value(
                text=text,
                key=key,
                patterns=list(patterns or []),
                alias_map=detection_alias_map,
            )
            if extracted:
                attribute_filters[key] = extracted

        cls._maybe_infer_opal_filter(
            text=text,
            attribute_filters=attribute_filters,
            alias_map=detection_alias_map,
            allowed_attribute_filters=list(active_rules.allowed_attribute_filters),
        )
        cls._maybe_infer_sterilization_filter(
            text=text,
            attribute_filters=attribute_filters,
            alias_map=detection_alias_map,
            allowed_attribute_filters=list(active_rules.allowed_attribute_filters),
        )
        cls._maybe_infer_basic_product_filters(
            text=text,
            attribute_filters=attribute_filters,
            alias_map=detection_alias_map,
        )
        cls._prune_ambiguous_finish_filter(
            text=text,
            attribute_filters=attribute_filters,
        )

        if attribute_filters.get("opal_color") and attribute_filters.get("color") == "opal":
            attribute_filters.pop("color", None)

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
            semantic_hints=[],
            clarify_focus="",
        )
