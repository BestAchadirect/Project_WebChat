from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from fastapi import HTTPException

from app.core.config import settings
from app.services.catalog.attribute_sync_service import product_attribute_sync_service
from app.services.catalog.category_taxonomy_service import category_taxonomy_service
from app.services.imports.products.parser import parse_bool, parse_int, parse_stock_status


class KlevuMappingMixin:
    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).replace("\x00", " ").strip()
        return re.sub(r"\s+", " ", text)

    @classmethod
    def _as_str(cls, value: Any) -> str:
        return cls._clean_text(value)

    @classmethod
    def _first_non_empty(cls, *values: Any) -> str:
        for value in values:
            text = cls._clean_text(value)
            if text:
                return text
        return ""

    @classmethod
    def _normalize_image_url(cls, value: Any) -> str:
        url = cls._clean_text(value)
        if not url:
            return ""
        return re.sub(r"/wholesale1_t/", "/wholesale1_b/", url, flags=re.IGNORECASE)

    @staticmethod
    def _parse_optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = KlevuMappingMixin._clean_text(value)
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @classmethod
    def _normalize_currency(cls, value: Any) -> Optional[str]:
        text = cls._clean_text(value).upper()
        return text or None

    @classmethod
    def _split_compound_sku(cls, raw_sku: str) -> tuple[str, str]:
        text = cls._clean_text(raw_sku)
        if not text:
            return "", ""
        if ";;;;" not in text:
            return "", text
        parts = [cls._clean_text(part) for part in text.split(";;;;") if cls._clean_text(part)]
        if not parts:
            return "", ""
        parent_clean = parts[0]
        for token in parts:
            if token.upper().endswith("-000000"):
                return parent_clean, token
        return parent_clean, parts[-1]

    @classmethod
    def _derive_master_code(
        cls,
        *,
        record: Mapping[str, Any],
        parent_sku: str,
        canonical_sku: str,
    ) -> str:
        explicit = cls._first_non_empty(record.get("master_code"), record.get("masterCode"))
        if explicit:
            return explicit
        if parent_sku:
            return parent_sku
        if canonical_sku.upper().endswith("-000000"):
            base = cls._clean_text(canonical_sku[:-7]).strip("-_ ")
            if base:
                return base
        grouped = cls._first_non_empty(
            record.get("parentSku"),
            record.get("groupId"),
            record.get("itemGroupId"),
        )
        if grouped:
            return grouped
        if "-" in canonical_sku:
            prefix = canonical_sku.split("-", 1)[0].strip()
            if prefix:
                return prefix
        return canonical_sku

    @staticmethod
    def _parse_iso_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return str(value)

    @staticmethod
    def _normalize_klevu_category(value: Any) -> Optional[str]:
        return category_taxonomy_service.normalize_category_string(value)

    @staticmethod
    def _normalize_category_value(value: Any) -> Optional[str]:
        return category_taxonomy_service.normalize_category_string(value)

    @classmethod
    def _resolve_object_id_for_upsert(
        cls,
        *,
        current_object_id: Any,
        incoming_object_id: Any,
        incoming_klevu_id: Any,
    ) -> Optional[str]:
        current = cls._clean_text(current_object_id) or None
        incoming_object = cls._clean_text(incoming_object_id) or None
        incoming_klevu = cls._clean_text(incoming_klevu_id) or None

        if incoming_object:
            return incoming_object
        if current and incoming_klevu and current == incoming_klevu:
            return None
        return current

    @classmethod
    def _is_simple_parent_sku(cls, sku: Any) -> bool:
        text = cls._clean_text(sku).upper()
        return bool(text) and text.endswith("-000000")

    @classmethod
    def _normalize_identity_fields(
        cls,
        *,
        sku: Any,
        klevu_id: Any,
        object_id: Any,
    ) -> tuple[Optional[str], Optional[str]]:
        normalized_klevu = cls._clean_text(klevu_id) or None
        normalized_object = cls._clean_text(object_id) or None

        if cls._is_simple_parent_sku(sku):
            if normalized_object and not normalized_klevu:
                normalized_klevu = normalized_object
                normalized_object = None
            elif normalized_object and normalized_klevu and normalized_object == normalized_klevu:
                normalized_object = None

        return normalized_klevu, normalized_object

    @staticmethod
    def _extract_attributes(record: Mapping[str, Any]) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {}
        source_map = {
            "body_part": "body_part",
            "bodyPart": "body_part",
            "feature": "feature",
            "presentation_type": "presentation_type",
            "presentationType": "presentation_type",
            "material": "material",
            "material_name": "material",
            "materialName": "material",
            "jewelry_type": "jewelry_type",
            "jewelryType": "jewelry_type",
            "jewellery_type": "jewelry_type",
            "color": "color",
            "colour": "color",
            "gauge": "gauge",
            "theme": "theme",
            "threading": "threading",
            "length": "length",
            "size": "size",
            "opal_color": "opal_color",
            "opalColor": "opal_color",
            "outer_diameter": "outer_diameter",
            "outerDiameter": "outer_diameter",
            "cz_color": "cz_color",
            "czColor": "cz_color",
            "crystal_color": "crystal_color",
            "crystalColor": "crystal_color",
            "pearl_color": "pearl_color",
            "pearlColor": "pearl_color",
            "design": "design",
            "rack": "rack",
            "height": "height",
            "packing_option": "packing_option",
            "packingOption": "packing_option",
            "pincher_size": "pincher_size",
            "pincherSize": "pincher_size",
            "ring_size": "ring_size",
            "ringSize": "ring_size",
            "size_in_pack": "size_in_pack",
            "sizeInPack": "size_in_pack",
            "quantity_in_bulk": "quantity_in_bulk",
            "quantityInBulk": "quantity_in_bulk",
            "category": "category",
        }
        for source_key, target_key in source_map.items():
            value = record.get(source_key)
            if value is None:
                continue
            if target_key == "category":
                text = KlevuMappingMixin._normalize_category_value(value) or ""
            else:
                text = KlevuMappingMixin._clean_text(value)
            if text:
                attrs[target_key] = text
        if "category" not in attrs:
            normalized_category = KlevuMappingMixin._normalize_klevu_category(record.get("klevu_category"))
            if normalized_category:
                attrs["category"] = normalized_category
        return attrs

    @classmethod
    def _collect_legacy_skus(
        cls,
        *,
        record: Mapping[str, Any],
        canonical_sku: str,
    ) -> List[str]:
        values: List[str] = []
        legacy_raw = cls._clean_text(record.get("legacy_sku"))
        if legacy_raw:
            for token in re.split(r"[|,]", legacy_raw):
                normalized = cls._clean_text(token)
                if normalized:
                    values.append(normalized)
        seen: set[str] = set()
        deduped: List[str] = []
        for item in values:
            lowered = item.lower()
            if lowered in seen or item == canonical_sku or ";;;;" in item:
                continue
            seen.add(lowered)
            deduped.append(item)
        return deduped

    def _build_payload(self, *, api_key: str, limit: int, offset: int) -> Dict[str, Any]:
        search_settings: Dict[str, Any] = {
            "query": {"term": "*"},
            "typeOfRecords": ["KLEVU_PRODUCT"],
            "sortOrder": "updatedAt:desc",
            "limit": int(limit),
            "offset": int(offset),
        }
        if bool(getattr(settings, "KLEVU_SYNC_DISABLE_GROUPING", True)):
            search_settings["searchPrefs"] = ["disableGrouping"]
        return {
            "context": {"apiKeys": [api_key]},
            "recordQueries": [
                {
                    "id": "klevu_products_sync",
                    "typeOfRequest": "SEARCH",
                    "settings": search_settings,
                }
            ],
        }

    def _ensure_payload_size(self, payload: Mapping[str, Any], max_bytes: int) -> None:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > int(max_bytes):
            raise HTTPException(
                status_code=400,
                detail=f"Klevu payload too large ({len(encoded)} bytes > {max_bytes} bytes).",
            )

    @staticmethod
    def _extract_records(response_json: Mapping[str, Any]) -> List[Dict[str, Any]]:
        queries = response_json.get("recordQueries")
        if isinstance(queries, list):
            for query in queries:
                if isinstance(query, Mapping) and isinstance(query.get("records"), list):
                    return [dict(r) for r in query["records"] if isinstance(r, Mapping)]
        query_results = response_json.get("queryResults")
        if isinstance(query_results, list):
            for query in query_results:
                if isinstance(query, Mapping) and isinstance(query.get("records"), list):
                    return [dict(r) for r in query["records"] if isinstance(r, Mapping)]
        return []

    def _record_to_payload(self, record: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        raw_sku = self._first_non_empty(
            record.get("sku"),
            record.get("SKU"),
            record.get("itemCode"),
            record.get("item_code"),
        )
        if not raw_sku:
            return None

        parent_sku, canonical_sku = self._split_compound_sku(raw_sku)
        if not canonical_sku:
            return None

        title = self._first_non_empty(
            record.get("name"),
            record.get("title"),
            record.get("productName"),
            canonical_sku,
        )
        description = self._clean_text(record.get("shortDesc"))
        master_code = self._derive_master_code(
            record=record,
            parent_sku=parent_sku,
            canonical_sku=canonical_sku,
        )
        object_id = self._first_non_empty(
            record.get("object_id"),
            record.get("objectId"),
        ) or None
        klevu_id = self._first_non_empty(
            record.get("klevu_id"),
            record.get("klevuId"),
            record.get("id"),
            record.get("itemId"),
        ) or None
        klevu_id, object_id = self._normalize_identity_fields(
            sku=canonical_sku,
            klevu_id=klevu_id,
            object_id=object_id,
        )

        price = self._parse_optional_float(
            self._first_non_empty(record.get("price"), record.get("salePrice"), record.get("listPrice"))
        )
        currency = self._normalize_currency(
            self._first_non_empty(
                record.get("currency"),
                record.get("currencyCode"),
                record.get("baseCurrency"),
                getattr(settings, "BASE_CURRENCY", "USD"),
            )
        ) or "USD"
        stock_qty = parse_int(
            self._first_non_empty(
                record.get("stock_qty"),
                record.get("stockQty"),
                record.get("quantity"),
                record.get("qty"),
            )
        )
        stock_status = parse_stock_status(
            self._first_non_empty(
                record.get("stock_status"),
                record.get("stockStatus"),
                record.get("inStock"),
                record.get("in_stock"),
                record.get("availability"),
            )
        )
        if stock_status is None:
            if stock_qty is not None:
                stock_status = "in_stock" if stock_qty > 0 else "out_of_stock"
            else:
                stock_status = "in_stock"

        image_url = self._normalize_image_url(
            self._first_non_empty(
                record.get("base_image"),
                record.get("baseImage"),
                record.get("image"),
                record.get("image_url"),
                record.get("thumbnail"),
                record.get("thumbnailImage"),
            )
        )
        product_url = self._first_non_empty(
            record.get("url"),
            record.get("product_url"),
            record.get("link"),
        )
        visibility = parse_bool(self._first_non_empty(record.get("visibility"), record.get("visible")))
        is_featured = parse_bool(self._first_non_empty(record.get("is_featured"), record.get("featured")))
        priority = parse_int(self._first_non_empty(record.get("priority"), record.get("rank"), record.get("sort_order")))

        attributes = self._extract_attributes(record)
        if raw_sku != canonical_sku:
            attributes["source_raw_sku"] = raw_sku
        attributes = product_attribute_sync_service.normalize_attributes(attributes)
        legacy_sku = self._collect_legacy_skus(
            record=record,
            canonical_sku=canonical_sku,
        )

        updated_at = self._parse_iso_datetime(
            self._first_non_empty(record.get("updatedAt"), record.get("updated_at"), record.get("lastUpdatedAt"))
        )

        return {
            "raw_sku": raw_sku,
            "sku": canonical_sku,
            "master_code": master_code,
            "title": title,
            "description": description or None,
            "klevu_id": klevu_id,
            "object_id": object_id,
            "price": price,
            "currency": currency,
            "stock_status": stock_status,
            "stock_qty": stock_qty,
            "image_url": image_url or None,
            "product_url": product_url or None,
            "attributes": attributes,
            "legacy_sku": legacy_sku,
            "visibility": visibility,
            "is_featured": is_featured,
            "priority": priority,
            "updated_at": updated_at,
        }
