from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.services.chat.parsing.attribute_normalization import (
    clean_attribute_filters as shared_clean_attribute_filters,
    normalize_attribute_value as shared_normalize_attribute_value,
    normalize_gauge_token as shared_normalize_gauge_token,
    normalize_measurement_token as shared_normalize_measurement_token,
)
from app.services.chat.parsing.llm_attribute_extractor import (
    DetailQueryInferenceResult,
    infer_detail_query,
)
from app.services.chat.parsing.parser_rule_types import ParserRuleSet, empty_rule_set
from app.utils.synonym_rules import resolve_attribute_conflicts

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
    def _finalize_parsed_detail(
        *,
        requested_fields: List[str],
        attribute_filters: Dict[str, str],
        wants_image: bool,
        semantic_hints: List[str],
        clarify_focus: str,
        confidence: float,
        allowed_attribute_filters: Sequence[str] | None = None,
    ) -> DetailQuery:
        filtered_fields: List[str] = []
        for raw in list(requested_fields or []):
            field = str(raw or "").strip().lower()
            if field in ALLOWED_DETAIL_FIELD_SET and field not in filtered_fields:
                filtered_fields.append(field)
        clean_filters = DetailQueryParser.clean_attribute_filters(
            attribute_filters,
            allowed_attribute_filters=allowed_attribute_filters,
        )
        clean_filters = resolve_attribute_conflicts(clean_filters)
        if confidence < 0.55:
            filtered_fields = []
            clean_filters = {}
            semantic_hints = []
            wants_image = False
            clarify_focus = clarify_focus or "detail_request_needs_specific_product"
        is_detail_request = bool(filtered_fields or wants_image)
        return DetailQuery(
            requested_fields=filtered_fields,
            attribute_filters=clean_filters,
            wants_image=wants_image,
            is_detail_request=is_detail_request,
            semantic_hints=list(semantic_hints or []),
            clarify_focus=str(clarify_focus or ""),
        )

    @classmethod
    def build_from_inference(
        cls,
        *,
        inference: DetailQueryInferenceResult,
        parser_rules: Optional[ParserRuleSet] = None,
    ) -> DetailQuery:
        return cls._finalize_parsed_detail(
            requested_fields=list(inference.requested_fields or []),
            attribute_filters=dict(inference.attribute_filters or {}),
            wants_image=bool(inference.wants_image),
            semantic_hints=list(inference.semantic_hints or []),
            clarify_focus=str(inference.clarify_focus or ""),
            confidence=float(inference.confidence or 0.0),
            allowed_attribute_filters=list((parser_rules or cls._EMPTY_RULE_SET).allowed_attribute_filters),
        )

    @classmethod
    async def parse_async(
        cls,
        *,
        user_text: str,
        nlu_data: Dict[str, Any],
        alias_map: Optional[Dict[str, Dict[str, str]]] = None,
        parser_rules: Optional[ParserRuleSet] = None,
    ) -> DetailQuery:
        inference = await infer_detail_query(
            user_text=user_text,
            workflow=str((nlu_data or {}).get("workflow") or "catalog"),
            alias_map=alias_map,
            parser_rules=parser_rules,
            existing_filters=(nlu_data or {}).get("attribute_filters"),
        )
        return cls.build_from_inference(inference=inference, parser_rules=parser_rules)
