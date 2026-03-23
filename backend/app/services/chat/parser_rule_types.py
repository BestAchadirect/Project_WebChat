from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Set


@dataclass(frozen=True)
class ParserRuleSet:
    requested_field_patterns: Dict[str, List[str]]
    value_extract_patterns: Dict[str, List[str]]
    detection_attribute_order: List[str]
    allowed_attribute_filters: Set[str]


def build_rule_set(
    *,
    requested_field_patterns: Dict[str, Sequence[str]],
    value_extract_patterns: Dict[str, Sequence[str]],
    detection_attribute_order: Sequence[str],
    allowed_attribute_filters: Sequence[str],
) -> ParserRuleSet:
    return ParserRuleSet(
        requested_field_patterns={
            key: [str(item) for item in list(values or []) if str(item or "").strip()]
            for key, values in dict(requested_field_patterns or {}).items()
        },
        value_extract_patterns={
            key: [str(item) for item in list(values or []) if str(item or "").strip()]
            for key, values in dict(value_extract_patterns or {}).items()
        },
        detection_attribute_order=[
            str(item).strip().lower()
            for item in list(detection_attribute_order or [])
            if str(item or "").strip()
        ],
        allowed_attribute_filters={
            str(item).strip().lower()
            for item in list(allowed_attribute_filters or [])
            if str(item or "").strip()
        },
    )


def empty_rule_set() -> ParserRuleSet:
    return ParserRuleSet(
        requested_field_patterns={},
        value_extract_patterns={},
        detection_attribute_order=[],
        allowed_attribute_filters=set(),
    )
