from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.product_attribute import AttributeDefinition, ProductAttributeValue
from app.services.chat.parsing.attribute_keys import canonicalize_filter_key
from app.services.chat.parsing.attribute_normalization import normalize_attribute_value
from app.services.chat.parsing.query_understanding import CatalogQueryUnderstanding
from app.services.chat.text_normalization import normalize_user_text

logger = logging.getLogger(__name__)

CRITICAL_ALIASES: Dict[str, Dict[str, List[str]]] = {
    "material": {
        "surgical steel": ["316l surgical steel", "316l stainless steel", "stainless steel", "surgical steel"],
        "steel": ["316l surgical steel", "316l stainless steel", "stainless steel", "steel"],
    },
    "jewelry_type": {
        "belly ring": ["navel ring", "belly ring", "belly banana"],
        "belly rings": ["navel ring", "belly ring", "belly banana"],
        "nose hoop": ["nose ring", "nostril hoop", "nose hoop"],
        "barbell": ["straight barbell", "barbell"],
        "ear stretcher": ["plug", "tunnel"],
    },
    "threading": {
        "internally threaded": ["internally threaded", "internal thread"],
        "internal thread": ["internally threaded", "internal thread"],
        "externally threaded": ["externally threaded", "external thread"],
        "external thread": ["externally threaded", "external thread"],
    },
}


@dataclass(frozen=True)
class ResolvedAttributePlan:
    resolved_hard_constraints: Dict[str, str] = field(default_factory=dict)
    unresolved_constraints: List[Dict[str, str]] = field(default_factory=list)
    resolved_soft_hints: List[str] = field(default_factory=list)
    attribute_resolution_confidence: Dict[str, float] = field(default_factory=dict)
    strictness: Dict[str, str] = field(default_factory=dict)
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_debug_dict(self) -> Dict[str, Any]:
        return {
            "resolved_hard_constraints": dict(self.resolved_hard_constraints),
            "unresolved_constraints": [dict(item) for item in self.unresolved_constraints],
            "resolved_soft_hints": list(self.resolved_soft_hints),
            "attribute_resolution_confidence": dict(self.attribute_resolution_confidence),
            "strictness": dict(self.strictness),
            **dict(self.debug or {}),
        }


def _dedupe(values: Sequence[Any]) -> List[str]:
    clean: List[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        text = normalize_user_text(str(value or ""))
        if not text or text in seen:
            continue
        seen.add(text)
        clean.append(text)
    return clean


def _constraint_items(understanding: CatalogQueryUnderstanding) -> List[tuple[str, str]]:
    constraints = understanding.hard_constraints
    items: List[tuple[str, str]] = []
    field_map = {
        "material": "material",
        "gauge": "gauge",
        "diameter": "outer_diameter",
        "length": "length",
        "color": "color",
        "threading": "threading",
        "jewelry_type": "jewelry_type",
        "category": "category",
    }
    data = constraints.model_dump(mode="json")
    for raw_key, target_key in field_map.items():
        for value in _dedupe(data.get(raw_key) or []):
            items.append((target_key, value))
    for value in _dedupe(understanding.product_type_terms):
        items.append(("jewelry_type", value))
    for value in _dedupe(understanding.category_terms):
        items.append(("category", value))
    if constraints.price:
        for key, value in _parse_price_constraint(str(constraints.price)):
            items.append((key, value))
    if constraints.stock:
        stock_value = _normalize_stock_constraint(str(constraints.stock))
        if stock_value:
            items.append(("stock_status", stock_value))
    return items


def _parse_price_constraint(text: str) -> List[tuple[str, str]]:
    normalized = normalize_user_text(text)
    if not normalized:
        return []
    match = re.search(r"(?:\$|usd\s*)?(\d+(?:\.\d+)?)", normalized)
    if not match:
        return []
    value = match.group(1)
    if any(marker in normalized for marker in ("under", "below", "less than", "max", "up to", "<")):
        return [("max_price", value)]
    if any(marker in normalized for marker in ("over", "above", "more than", "min", "at least", ">")):
        return [("min_price", value)]
    return [("max_price", value)]


def _normalize_stock_constraint(text: str) -> str:
    normalized = normalize_user_text(text)
    if not normalized:
        return ""
    if any(marker in normalized for marker in ("in stock", "available", "stocked")):
        return "in_stock"
    if any(marker in normalized for marker in ("out of stock", "unavailable")):
        return "out_of_stock"
    return normalized


def _critical_alias_candidates(attribute: str, value: str) -> List[str]:
    attr = canonicalize_filter_key(attribute)
    normalized = normalize_user_text(value)
    aliases = dict(CRITICAL_ALIASES.get(attr) or {})
    out = [normalized] if normalized else []
    for alias, candidates in aliases.items():
        alias_norm = normalize_user_text(alias)
        if alias_norm and alias_norm in normalized:
            out.extend(candidates)
    return _dedupe(out)


async def _load_catalog_values(
    db: AsyncSession | Any,
    attributes: Sequence[str],
) -> Dict[str, List[Dict[str, str]]]:
    wanted = {
        canonicalize_filter_key(attribute)
        for attribute in list(attributes or [])
        if canonicalize_filter_key(attribute)
        and canonicalize_filter_key(attribute) not in {"min_price", "max_price", "stock_status", "sku"}
    }
    if not wanted or db is None or not hasattr(db, "execute"):
        return {}
    try:
        stmt = (
            select(
                AttributeDefinition.name,
                ProductAttributeValue.value,
                ProductAttributeValue.value_norm,
                func.count(Product.id).label("product_count"),
            )
            .join(ProductAttributeValue, ProductAttributeValue.attribute_id == AttributeDefinition.id)
            .join(Product, Product.id == ProductAttributeValue.product_id)
            .where(AttributeDefinition.is_enabled.is_(True))
            .where(func.lower(AttributeDefinition.name).in_(sorted(wanted)))
            .where(Product.is_active.is_(True))
            .where(ProductAttributeValue.value.isnot(None))
            .where(ProductAttributeValue.value != "")
            .group_by(AttributeDefinition.name, ProductAttributeValue.value, ProductAttributeValue.value_norm)
        )
        rows = (await db.execute(stmt)).all()
    except Exception as exc:
        logger.warning("catalog attribute resolver value lookup failed: %s", exc)
        return {}

    values: Dict[str, List[Dict[str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    for raw_attr, raw_value, raw_norm, raw_count in rows:
        attr = canonicalize_filter_key(raw_attr)
        value = str(raw_value or "").strip()
        value_norm = normalize_user_text(raw_norm or raw_value)
        if not attr or not value or not value_norm:
            continue
        key = (attr, value_norm)
        if key in seen:
            continue
        seen.add(key)
        values.setdefault(attr, []).append(
            {
                "value": value,
                "value_norm": value_norm,
                "product_count": str(int(raw_count or 0)),
            }
        )
    return values


def _resolve_against_values(
    *,
    attribute: str,
    value: str,
    catalog_values: Sequence[Mapping[str, str]],
) -> tuple[str, float, str]:
    attr = canonicalize_filter_key(attribute)
    requested_norm = normalize_attribute_value(key=attr, value=value)
    if not requested_norm:
        return "", 0.0, "empty"
    if attr in {"min_price", "max_price", "stock_status"}:
        return requested_norm, 1.0, "synthetic"

    candidates = list(catalog_values or [])
    if not candidates:
        return "", 0.0, "no_catalog_values"

    alias_terms = _critical_alias_candidates(attr, requested_norm)
    for candidate_term in alias_terms:
        candidate_norm = normalize_user_text(candidate_term)
        for row in candidates:
            row_value = str(row.get("value") or "").strip()
            row_norm = normalize_user_text(row.get("value_norm") or row_value)
            if row_norm == candidate_norm or candidate_norm in row_norm:
                return normalize_attribute_value(key=attr, value=row_value), 0.98, "critical_alias"

    for row in candidates:
        row_value = str(row.get("value") or "").strip()
        row_norm = normalize_user_text(row.get("value_norm") or row_value)
        if row_norm == requested_norm:
            return normalize_attribute_value(key=attr, value=row_value), 1.0, "exact"

    for row in candidates:
        row_value = str(row.get("value") or "").strip()
        row_norm = normalize_user_text(row.get("value_norm") or row_value)
        if requested_norm in row_norm or row_norm in requested_norm:
            return normalize_attribute_value(key=attr, value=row_value), 0.88, "normalized_contains"

    best_value = ""
    best_score = 0.0
    for row in candidates:
        row_value = str(row.get("value") or "").strip()
        row_norm = normalize_user_text(row.get("value_norm") or row_value)
        score = SequenceMatcher(None, requested_norm, row_norm).ratio()
        if score > best_score:
            best_score = score
            best_value = row_value
    if best_value and best_score >= 0.86:
        return normalize_attribute_value(key=attr, value=best_value), round(best_score, 4), "fuzzy"
    return "", round(best_score, 4), "unresolved"


def _merge_filter_value(existing: str, new_value: str) -> str:
    current = [item for item in str(existing or "").split(";;") if item.strip()]
    incoming = [item for item in str(new_value or "").split(";;") if item.strip()]
    merged: List[str] = []
    seen: set[str] = set()
    for item in current + incoming:
        text = item.strip()
        key = normalize_user_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(text)
    return ";;".join(merged)


async def resolve_catalog_attributes(
    *,
    db: AsyncSession | Any,
    understanding: CatalogQueryUnderstanding,
) -> ResolvedAttributePlan:
    raw_items = _constraint_items(understanding)
    attributes = [attribute for attribute, _value in raw_items]
    catalog_values = await _load_catalog_values(db, attributes)
    resolved: Dict[str, str] = {}
    unresolved: List[Dict[str, str]] = []
    confidence: Dict[str, float] = {}
    strictness = {
        canonicalize_filter_key(key): str(value or "").strip().lower()
        for key, value in dict(understanding.strictness or {}).items()
        if canonicalize_filter_key(key)
    }

    for raw_attribute, raw_value in raw_items:
        attribute = canonicalize_filter_key(raw_attribute)
        value = normalize_user_text(raw_value)
        if not attribute or not value:
            continue
        resolved_value, score, source = _resolve_against_values(
            attribute=attribute,
            value=value,
            catalog_values=catalog_values.get(attribute, []),
        )
        confidence[f"{attribute}:{value}"] = float(score)
        if resolved_value:
            resolved[attribute] = _merge_filter_value(resolved.get(attribute, ""), resolved_value)
            strictness.setdefault(attribute, "required")
            continue
        unresolved.append(
            {
                "attribute": attribute,
                "value": value,
                "reason": source,
                "strictness": strictness.get(attribute, "required"),
            }
        )

    soft_hints = _dedupe(understanding.soft_hints)
    debug = {
        "attribute_resolution_catalog_value_attributes": sorted(catalog_values.keys()),
        "attribute_resolution_input_count": len(raw_items),
        "attribute_resolution_resolved_count": len(resolved),
        "attribute_resolution_unresolved_count": len(unresolved),
    }
    return ResolvedAttributePlan(
        resolved_hard_constraints=resolved,
        unresolved_constraints=unresolved,
        resolved_soft_hints=soft_hints,
        attribute_resolution_confidence=confidence,
        strictness=strictness,
        debug=debug,
    )
