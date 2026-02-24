from __future__ import annotations

import hashlib
import html
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.services.catalog.attributes_service import eav_service

ATTRIBUTE_FIELDS: List[str] = [
    "jewelry_type",
    "material",
    "length",
    "size",
    "cz_color",
    "design",
    "crystal_color",
    "color",
    "gauge",
    "size_in_pack",
    "rack",
    "height",
    "packing_option",
    "pincher_size",
    "ring_size",
    "quantity_in_bulk",
    "opal_color",
    "threading",
    "outer_diameter",
    "pearl_color",
]

SEARCH_KEYWORD_FIELDS: List[str] = [
    "jewelry_type",
    "material",
    "gauge",
    "threading",
    "length",
    "size",
    "color",
]

SEARCH_SYNONYMS = {
    "titanium g23": ["g23", "implant grade", "implant-grade", "implant"],
    "steel": ["surgical steel", "stainless steel", "316l"],
    "gold": ["14k gold", "18k gold"],
    "silver": ["sterling silver"],
    "internal": ["internally threaded"],
    "external": ["externally threaded"],
}

MATERIAL_SYNONYMS = {
    "g23": "Titanium G23",
    "titanium g23": "Titanium G23",
    "implant grade": "Titanium G23",
    "implant-grade": "Titanium G23",
    "implant": "Titanium G23",
    "titanium": "Titanium",
    "surgical steel": "Steel",
    "stainless steel": "Steel",
    "316l": "Steel",
    "316l steel": "Steel",
    "steel": "Steel",
    "gold": "Gold",
    "silver": "Silver",
    "niobium": "Niobium",
}

THREADING_SYNONYMS = {
    "internal": "Internal",
    "internally threaded": "Internal",
    "external": "External",
    "externally threaded": "External",
    "threadless": "Threadless",
}

JEWELRY_TYPE_SYNONYMS = {
    "labret stud": "Labret",
    "labrets": "Labret",
    "barbells": "Barbell",
    "rings": "Ring",
    "studs": "Stud",
    "tunnels": "Tunnel",
    "plugs": "Plug",
}


class ProductAttributeSyncService:
    @staticmethod
    def _normalize_search_text(text: str) -> str:
        if not text:
            return ""
        normalized = html.unescape(str(text))
        normalized = normalized.lower()
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _normalize_keyword(self, value: Any) -> str:
        if value is None:
            return ""
        token = str(value).strip()
        if not token:
            return ""
        return self._normalize_search_text(token)

    @staticmethod
    def _normalize_material(value: str) -> str:
        lowered = value.strip().lower()
        if "g23" in lowered:
            return "Titanium G23"
        return MATERIAL_SYNONYMS.get(lowered, value.strip())

    @staticmethod
    def _normalize_gauge(value: str) -> str:
        lowered = value.strip().lower()
        match = re.search(r"\b(\d{1,2})\s*(?:g|gauge)\b", lowered)
        if match:
            return f"{match.group(1)}g"
        if lowered.endswith("g") and lowered[:-1].isdigit():
            return lowered
        return value.strip()

    @staticmethod
    def _normalize_threading(value: str) -> str:
        lowered = value.strip().lower()
        return THREADING_SYNONYMS.get(lowered, value.strip())

    @staticmethod
    def _normalize_jewelry_type(value: str) -> str:
        lowered = value.strip().lower()
        return JEWELRY_TYPE_SYNONYMS.get(lowered, value.strip())

    def normalize_attribute_value(self, key: str, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if key == "material":
                return self._normalize_material(text)
            if key == "gauge":
                return self._normalize_gauge(text)
            if key == "threading":
                return self._normalize_threading(text)
            if key == "jewelry_type":
                return self._normalize_jewelry_type(text)
            return text
        return value

    def normalize_attributes(self, attributes: Mapping[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        for key, raw_value in (attributes or {}).items():
            if not key:
                continue
            val = self.normalize_attribute_value(str(key), raw_value)
            if val is None:
                continue
            normalized[str(key)] = val
        return normalized

    def merge_attributes(
        self,
        *,
        current: Optional[Mapping[str, Any]],
        updates: Optional[Mapping[str, Any]],
        drop_empty: bool = True,
    ) -> Dict[str, Any]:
        merged = dict(current or {})
        for key, raw_value in (updates or {}).items():
            norm_key = str(key)
            normalized = self.normalize_attribute_value(norm_key, raw_value)
            if normalized is None:
                if drop_empty:
                    merged.pop(norm_key, None)
                continue
            merged[norm_key] = normalized
        return merged

    @staticmethod
    def _expand_search_terms(values: Sequence[Any]) -> List[str]:
        expanded: List[str] = []
        seen: set[str] = set()
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            for token in [text, *re.split(r"[^A-Za-z0-9]+", text)]:
                clean = token.strip()
                if not clean:
                    continue
                key = clean.lower()
                if key in seen:
                    continue
                seen.add(key)
                expanded.append(clean)
        return expanded

    def _build_search_synonyms(self, attributes: Mapping[str, Any]) -> List[str]:
        synonyms: List[str] = []
        for key in SEARCH_KEYWORD_FIELDS:
            value = attributes.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            canonical = value.strip().lower()
            synonyms.extend(SEARCH_SYNONYMS.get(canonical, []))
            if key == "gauge" and canonical.endswith("g"):
                synonyms.append(f"{canonical[:-1]} gauge")
        return synonyms

    def _build_search_keywords(
        self,
        *,
        display_name: str,
        sku: str,
        legacy_skus: Sequence[str],
        attributes: Mapping[str, Any],
        manual_keywords: Optional[Sequence[str]] = None,
    ) -> List[str]:
        tokens: List[str] = []

        def add(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, list):
                for item in value:
                    add(item)
                return
            token = self._normalize_keyword(value)
            if token:
                tokens.append(token)

        add(display_name)
        add(sku)
        add(list(legacy_skus or []))
        for key in SEARCH_KEYWORD_FIELDS:
            add(attributes.get(key))
        for item in manual_keywords or []:
            add(item)

        seen: set[str] = set()
        deduped: List[str] = []
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            deduped.append(token)
        return deduped

    def build_search_document(
        self,
        *,
        display_name: str,
        sku: str,
        object_id: Optional[str],
        description: Optional[str],
        legacy_skus: Sequence[str],
        attributes: Mapping[str, Any],
        manual_keywords: Optional[Sequence[str]] = None,
        attribute_columns: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        columns = list(attribute_columns or ATTRIBUTE_FIELDS)
        synonyms = self._build_search_synonyms(attributes)
        parts: List[Any] = [
            display_name,
            sku,
            object_id,
            description,
            *(legacy_skus or []),
            *synonyms,
            *(manual_keywords or []),
        ]
        for key in columns:
            value = attributes.get(key)
            if value is not None:
                parts.append(value)

        expanded = self._expand_search_terms(parts)
        search_text = self._normalize_search_text(" ".join(expanded))
        search_hash = hashlib.sha256(search_text.encode("utf-8")).hexdigest()
        search_keywords = self._build_search_keywords(
            display_name=display_name,
            sku=sku,
            legacy_skus=legacy_skus,
            attributes=attributes,
            manual_keywords=manual_keywords,
        )
        return {
            "search_text": search_text,
            "search_hash": search_hash,
            "search_keywords": search_keywords,
        }

    async def apply_dual_canonical(
        self,
        *,
        db: AsyncSession,
        product: Product,
        attribute_updates: Mapping[str, Any],
        drop_empty: bool = True,
    ) -> Dict[str, Any]:
        remove_keys: List[str] = []
        for key, raw_value in (attribute_updates or {}).items():
            normalized = self.normalize_attribute_value(str(key), raw_value)
            if normalized is None and drop_empty:
                remove_keys.append(str(key))
        merged = self.merge_attributes(
            current=product.attributes or {},
            updates=attribute_updates,
            drop_empty=drop_empty,
        )
        product.attributes = merged
        eav_payload: Dict[str, Any] = dict(merged)
        for key in remove_keys:
            eav_payload[key] = None
        await eav_service.upsert_product_attributes(
            db,
            product_id=product.id,
            attributes=eav_payload,
            drop_empty=drop_empty,
        )
        return merged

    def recompute_product_search_fields(
        self,
        *,
        product: Product,
        manual_keywords: Optional[Sequence[str]] = None,
        attribute_columns: Optional[Sequence[str]] = None,
    ) -> bool:
        payload = self.build_search_document(
            display_name=product.master_code or product.sku,
            sku=product.sku,
            object_id=product.object_id,
            description=product.description,
            legacy_skus=product.legacy_sku or [],
            attributes=product.attributes or {},
            manual_keywords=manual_keywords,
            attribute_columns=attribute_columns,
        )
        changed = (
            payload["search_text"] != (product.search_text or "")
            or payload["search_hash"] != (product.search_hash or "")
            or payload["search_keywords"] != (product.search_keywords or [])
        )
        product.search_text = payload["search_text"]
        product.search_hash = payload["search_hash"]
        product.search_keywords = payload["search_keywords"]
        return changed


product_attribute_sync_service = ProductAttributeSyncService()
