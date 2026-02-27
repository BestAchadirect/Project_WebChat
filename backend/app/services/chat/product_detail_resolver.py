from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from app.services.chat.detail_query_parser import ALLOWED_DETAIL_FIELDS, DetailQueryParser


@dataclass(frozen=True)
class DetailMatch:
    card: Any
    matched_filter_count: int
    total_filter_count: int
    distance: float
    exact_code_match: bool
    missing_fields: List[str]


@dataclass(frozen=True)
class DetailResolutionResult:
    matches: List[Any]
    match_details: List[DetailMatch]
    missing_fields_by_product: Dict[str, List[str]]
    requested_fields: List[str]
    attribute_filters: Dict[str, str]
    has_exact_match: bool


class ProductDetailResolver:
    @staticmethod
    def _normalize(value: object) -> str:
        text = str(value or "").strip().lower()
        return re.sub(r"\s+", " ", text)

    @staticmethod
    def _normalize_stock(value: object) -> str:
        return ProductDetailResolver._normalize(value).replace("stockstatus.", "")

    @staticmethod
    def _is_in_stock(value: object) -> bool:
        normalized = ProductDetailResolver._normalize_stock(value)
        return normalized == "in_stock"

    @staticmethod
    def _field_is_missing(card: Any, field: str) -> bool:
        if field == "price":
            return card.price is None
        if field == "stock":
            return not str(card.stock_status or "").strip()
        if field == "image":
            return not str(card.image_url or "").strip()
        if field == "attributes":
            attrs = card.attributes or {}
            truthy = {
                key: value
                for key, value in attrs.items()
                if value is not None and str(value).strip()
            }
            return len(truthy) == 0
        if field == "name":
            return not str(card.name or "").strip()
        if field == "sku":
            return not str(card.sku or "").strip()
        return False

    @classmethod
    def _missing_fields(cls, card: Any, requested_fields: List[str]) -> List[str]:
        missing: List[str] = []
        for field in requested_fields:
            if cls._field_is_missing(card, field):
                missing.append(field)
        return missing

    @classmethod
    def _match_filter(cls, card: Any, *, key: str, expected: str) -> bool:
        attrs = card.attributes or {}
        expected_norm = cls._normalize(expected)
        if not expected_norm:
            return True

        if key == "gauge":
            expected_gauge = DetailQueryParser.normalize_gauge_token(expected_norm)
            actual_gauge = DetailQueryParser.normalize_gauge_token(str(attrs.get("gauge") or ""))
            return bool(actual_gauge) and actual_gauge == expected_gauge

        if key == "jewelry_type":
            actual = cls._normalize(attrs.get("jewelry_type") or attrs.get("type") or "")
            return bool(actual) and expected_norm in actual

        if key in {"material", "threading", "color"}:
            actual = cls._normalize(attrs.get(key) or "")
            return bool(actual) and expected_norm in actual

        if key == "sku":
            return cls._normalize(card.sku) == expected_norm

        if key == "name":
            return expected_norm in cls._normalize(card.name)

        actual = cls._normalize(attrs.get(key) or "")
        return bool(actual) and expected_norm in actual

    @classmethod
    def _filter_match_counts(
        cls,
        card: Any,
        *,
        attribute_filters: Dict[str, str],
    ) -> tuple[int, int]:
        if not attribute_filters:
            return 0, 0
        matched = 0
        total = 0
        for key, expected in attribute_filters.items():
            total += 1
            if cls._match_filter(card, key=key, expected=expected):
                matched += 1
        return matched, total

    @staticmethod
    def _exact_code_match(
        card: Any,
        *,
        sku_token: Optional[str],
        nlu_product_code: Optional[str],
    ) -> bool:
        sku = str(card.sku or "").strip().lower()
        object_id = str(card.object_id or "").strip().lower()
        candidates = {
            str(sku_token or "").strip().lower(),
            str(nlu_product_code or "").strip().lower(),
        }
        candidates = {candidate for candidate in candidates if candidate}
        if not candidates:
            return False
        return sku in candidates or object_id in candidates

    @classmethod
    def resolve_detail_request(
        cls,
        *,
        candidate_cards: List[Any],
        distance_by_id: Dict[str, float],
        requested_fields: List[str],
        attribute_filters: Dict[str, str],
        sku_token: Optional[str],
        nlu_product_code: Optional[str],
        max_matches: int,
        min_confidence: float,
    ) -> DetailResolutionResult:
        clean_fields = [field for field in requested_fields if field in ALLOWED_DETAIL_FIELDS]
        if not clean_fields:
            clean_fields = ["attributes"]
        clean_filters = {
            str(key).strip().lower(): str(value).strip()
            for key, value in (attribute_filters or {}).items()
            if str(key).strip() and str(value).strip()
        }

        ranked: List[DetailMatch] = []
        for card in candidate_cards:
            card_id = str(card.id)
            distance = float(distance_by_id.get(card_id, 1.0))
            matched_count, total_count = cls._filter_match_counts(
                card,
                attribute_filters=clean_filters,
            )
            exact_match = cls._exact_code_match(
                card,
                sku_token=sku_token,
                nlu_product_code=nlu_product_code,
            )
            missing = cls._missing_fields(card, clean_fields)
            ranked.append(
                DetailMatch(
                    card=card,
                    matched_filter_count=matched_count,
                    total_filter_count=total_count,
                    distance=distance,
                    exact_code_match=exact_match,
                    missing_fields=missing,
                )
            )

        full_matches = [
            item
            for item in ranked
            if item.total_filter_count == 0 or item.matched_filter_count == item.total_filter_count
        ]
        if clean_filters and full_matches:
            candidates = full_matches
        elif clean_filters:
            candidates = [item for item in ranked if item.matched_filter_count > 0]
        else:
            candidates = ranked

        candidates.sort(
            key=lambda item: (
                0 if item.exact_code_match else 1,
                -item.matched_filter_count,
                item.distance,
                0 if cls._is_in_stock(item.card.stock_status) else 1,
                str(item.card.sku or ""),
            )
        )

        selected: List[DetailMatch] = []
        for item in candidates:
            if not item.exact_code_match and not clean_filters and item.distance > float(min_confidence):
                continue
            selected.append(item)
            if len(selected) >= max(1, int(max_matches)):
                break

        missing_fields_by_product = {
            str(item.card.id): list(item.missing_fields)
            for item in selected
        }
        has_exact_match = any(item.exact_code_match for item in selected)
        return DetailResolutionResult(
            matches=[item.card for item in selected],
            match_details=selected,
            missing_fields_by_product=missing_fields_by_product,
            requested_fields=clean_fields,
            attribute_filters=clean_filters,
            has_exact_match=has_exact_match,
        )
