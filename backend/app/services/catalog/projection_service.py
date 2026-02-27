from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.product_search_projection import ProductSearchProjection
from app.services.catalog.attributes_service import eav_service
from app.services.catalog.attribute_sync_service import product_attribute_sync_service


class ProductProjectionSyncService:
    _MATERIAL_FALLBACK_TOKENS: Dict[str, List[str]] = {
        "Titanium G23": ["titanium g23", "g23", "implant grade", "implant-grade", "implant"],
        "Titanium": ["titanium"],
        "Steel": ["surgical steel", "stainless steel", "316l", "steel"],
        "Gold": ["gold"],
        "Silver": ["silver"],
        "Niobium": ["niobium"],
        "Acrylic": ["acrylic"],
    }
    _JEWELRY_TYPE_FALLBACK_TOKENS: Dict[str, List[str]] = {
        "Barbell": ["barbell", "barbells"],
        "Circular Barbell": ["circular barbell", "horseshoe"],
        "Labret": ["labret", "labrets"],
        "Ring": ["ring", "rings"],
        "Stud": ["stud", "studs"],
        "Tunnel": ["tunnel", "tunnels"],
        "Plug": ["plug", "plugs"],
    }

    @staticmethod
    def _norm(value: Any) -> str:
        text = str(value or "").strip().lower()
        return re.sub(r"\s+", " ", text)

    @staticmethod
    def _merge_attrs(base_attrs: Optional[Mapping[str, Any]], eav_attrs: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        attrs = dict(base_attrs or {})
        for key, value in dict(eav_attrs or {}).items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            attrs[str(key)] = value
        return attrs

    @classmethod
    def _infer_from_search_text(cls, *, search_text: str, token_map: Dict[str, List[str]]) -> Optional[str]:
        text = cls._norm(search_text)
        if not text:
            return None
        candidates: List[tuple[str, str]] = []
        for label, tokens in token_map.items():
            for token in tokens:
                needle = cls._norm(token)
                if needle:
                    candidates.append((needle, label))

        # Prefer more specific phrases (e.g. "circular barbell" before "barbell").
        for needle, label in sorted(candidates, key=lambda item: len(item[0]), reverse=True):
            if needle in text:
                return label
        return None

    @classmethod
    def _normalize_material(cls, value: Any) -> str:
        normalized = product_attribute_sync_service.normalize_attribute_value("material", value)
        return cls._norm(normalized)

    @classmethod
    def _normalize_jewelry_type(cls, value: Any) -> str:
        normalized = product_attribute_sync_service.normalize_attribute_value("jewelry_type", value)
        return cls._norm(normalized)

    @classmethod
    def _normalize_gauge(cls, value: Any) -> str:
        normalized = product_attribute_sync_service.normalize_attribute_value("gauge", value)
        return cls._norm(normalized)

    @classmethod
    def _normalize_threading(cls, value: Any) -> str:
        normalized = product_attribute_sync_service.normalize_attribute_value("threading", value)
        return cls._norm(normalized)

    @classmethod
    def _normalize_color(cls, value: Any) -> str:
        return cls._norm(value)

    @classmethod
    def _build_projection_row(
        cls,
        *,
        product: Product,
        eav_attrs: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        attrs = cls._merge_attrs(product.attributes, eav_attrs)
        search_text_norm = cls._norm(getattr(product, "search_text", None))

        material_norm = cls._normalize_material(attrs.get("material"))
        if not material_norm:
            inferred = cls._infer_from_search_text(
                search_text=search_text_norm,
                token_map=cls._MATERIAL_FALLBACK_TOKENS,
            )
            material_norm = cls._norm(inferred)

        jewelry_type_norm = cls._normalize_jewelry_type(attrs.get("jewelry_type") or attrs.get("type"))
        if not jewelry_type_norm:
            inferred = cls._infer_from_search_text(
                search_text=search_text_norm,
                token_map=cls._JEWELRY_TYPE_FALLBACK_TOKENS,
            )
            jewelry_type_norm = cls._norm(inferred)

        return {
            "product_id": product.id,
            "sku_norm": cls._norm(product.sku),
            "material_norm": material_norm or None,
            "jewelry_type_norm": jewelry_type_norm or None,
            "gauge_norm": cls._normalize_gauge(attrs.get("gauge")) or None,
            "threading_norm": cls._normalize_threading(attrs.get("threading")) or None,
            "color_norm": cls._normalize_color(attrs.get("color")) or None,
            "opal_color_norm": cls._normalize_color(attrs.get("opal_color")) or None,
            "search_text_norm": search_text_norm or None,
            "stock_status_norm": cls._norm(getattr(getattr(product, "stock_status", None), "value", product.stock_status)),
            "is_active": bool(getattr(product, "is_active", True)),
            "updated_at": getattr(product, "updated_at", None) or datetime.utcnow(),
            "created_at": getattr(product, "created_at", None) or datetime.utcnow(),
        }

    async def sync_products_by_ids(
        self,
        db: AsyncSession,
        *,
        product_ids: Sequence[Any],
    ) -> int:
        ids = [item for item in dict.fromkeys([pid for pid in list(product_ids or []) if pid])]
        if not ids:
            return 0

        stmt = select(Product).where(Product.id.in_(ids))
        result = await db.execute(stmt)
        products = list(result.scalars().all())
        if not products:
            return 0

        attr_map = await eav_service.get_product_attributes(db, [p.id for p in products])
        rows = [
            self._build_projection_row(
                product=product,
                eav_attrs=attr_map.get(product.id),
            )
            for product in products
        ]
        if not rows:
            return 0

        insert_stmt = pg_insert(ProductSearchProjection).values(rows)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["product_id"],
            set_={
                "sku_norm": insert_stmt.excluded.sku_norm,
                "material_norm": insert_stmt.excluded.material_norm,
                "jewelry_type_norm": insert_stmt.excluded.jewelry_type_norm,
                "gauge_norm": insert_stmt.excluded.gauge_norm,
                "threading_norm": insert_stmt.excluded.threading_norm,
                "color_norm": insert_stmt.excluded.color_norm,
                "opal_color_norm": insert_stmt.excluded.opal_color_norm,
                "search_text_norm": insert_stmt.excluded.search_text_norm,
                "stock_status_norm": insert_stmt.excluded.stock_status_norm,
                "is_active": insert_stmt.excluded.is_active,
                "updated_at": insert_stmt.excluded.updated_at,
            },
        )
        await db.execute(upsert_stmt)
        return len(rows)

    async def sync_products(
        self,
        db: AsyncSession,
        *,
        products: Iterable[Product],
    ) -> int:
        ids = [getattr(product, "id", None) for product in list(products or [])]
        return await self.sync_products_by_ids(db, product_ids=ids)


product_projection_sync_service = ProductProjectionSyncService()
