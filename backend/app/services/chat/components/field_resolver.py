from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Sequence, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, StockStatus
from app.models.product_attribute import AttributeDefinition, ProductAttributeValue
from app.services.chat.components.cache import RedisComponentCache, stable_cache_key
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.registry import ComponentRegistry
from app.services.chat.components.types import ComponentType


class FieldDependencyResolver:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _to_uuid_list(ids: Sequence[Any]) -> List[UUID]:
        out: List[UUID] = []
        seen = set()
        for raw in ids:
            if raw is None:
                continue
            uid = raw if isinstance(raw, UUID) else UUID(str(raw))
            if uid in seen:
                continue
            seen.add(uid)
            out.append(uid)
        return out

    @staticmethod
    def _build_canonical_from_product(product: Product) -> CanonicalProduct:
        attrs = dict(getattr(product, "attributes", {}) or {})
        material = attrs.get("material")
        gauge = attrs.get("gauge")
        stock_status_raw = str(getattr(product, "stock_status", "") or "")
        if isinstance(getattr(product, "stock_status", None), StockStatus):
            stock_status_raw = getattr(product, "stock_status").value
        return CanonicalProduct(
            product_id=product.id,
            sku=str(product.sku or ""),
            title=str(getattr(product, "name", "") or ""),
            price=Decimal(str(getattr(product, "price", 0.0) or 0.0)),
            currency=str(getattr(product, "currency", "USD") or "USD"),
            in_stock=str(stock_status_raw).lower() == "in_stock",
            stock_qty=getattr(product, "stock_qty", None),
            material=str(material) if material is not None else None,
            gauge=str(gauge) if gauge is not None else None,
            image_url=(str(getattr(product, "image_url", "")) if getattr(product, "image_url", None) else None),
            attributes=attrs,
            product_url=(str(getattr(product, "product_url", "")) if getattr(product, "product_url", None) else None),
        )

    async def resolve(
        self,
        *,
        product_ids: Sequence[Any],
        component_types: List[ComponentType],
        redis_cache: RedisComponentCache | None = None,
        cache_key_prefix: str = "chat:components:canonical",
        cache_ttl_seconds: int = 900,
    ) -> Tuple[List[CanonicalProduct], Dict[str, Any]]:
        ordered_ids = self._to_uuid_list(product_ids)
        union_required_fields = ComponentRegistry.required_fields_for(component_types)
        if not ordered_ids:
            return [], {
                "field_union_size": len(union_required_fields),
                "union_required_fields": sorted(union_required_fields),
                "enrichment_used": False,
                "db_round_trips": 0,
                "redis_cache_hits": 0,
            }

        by_id: Dict[UUID, CanonicalProduct] = {}
        missing_ids: List[UUID] = []
        redis_hits = 0
        db_round_trips = 0

        if redis_cache is not None:
            for uid in ordered_ids:
                key = stable_cache_key(f"{cache_key_prefix}:item", {"product_id": str(uid)})
                payload = await redis_cache.get_json(key)
                if isinstance(payload, dict):
                    try:
                        by_id[uid] = CanonicalProduct.from_cache_payload(payload)
                        redis_hits += 1
                        continue
                    except Exception:
                        pass
                missing_ids.append(uid)
        else:
            missing_ids = list(ordered_ids)

        if missing_ids:
            stmt = select(Product).where(Product.id.in_(missing_ids))
            result = await self.db.execute(stmt)
            products = list(result.scalars().all())
            db_round_trips += 1
            for product in products:
                canonical = self._build_canonical_from_product(product)
                by_id[canonical.product_id] = canonical

            if redis_cache is not None:
                for canonical in by_id.values():
                    key = stable_cache_key(f"{cache_key_prefix}:item", {"product_id": str(canonical.product_id)})
                    await redis_cache.set_json(key, canonical.to_cache_payload(), cache_ttl_seconds)

        needs_full_spec = "full_spec_fields" in union_required_fields
        needs_material = "material" in union_required_fields and any(not c.material for c in by_id.values())
        needs_gauge = "gauge" in union_required_fields and any(not c.gauge for c in by_id.values())
        enrichment_used = bool(needs_full_spec or needs_material or needs_gauge)

        if enrichment_used and by_id:
            enrich_stmt = (
                select(ProductAttributeValue.product_id, AttributeDefinition.name, ProductAttributeValue.value)
                .join(AttributeDefinition, AttributeDefinition.id == ProductAttributeValue.attribute_id)
                .where(ProductAttributeValue.product_id.in_(list(by_id.keys())))
            )
            enrich_rows = (await self.db.execute(enrich_stmt)).all()
            db_round_trips += 1
            for row in enrich_rows:
                product_id = row.product_id
                if product_id not in by_id:
                    continue
                name = str(row.name or "").strip()
                if not name:
                    continue
                value = row.value
                canonical = by_id[product_id]
                if value is None:
                    continue
                canonical.attributes[name] = value
                if name == "material" and not canonical.material:
                    canonical.material = str(value)
                if name == "gauge" and not canonical.gauge:
                    canonical.gauge = str(value)

            if redis_cache is not None:
                for canonical in by_id.values():
                    key = stable_cache_key(f"{cache_key_prefix}:item", {"product_id": str(canonical.product_id)})
                    await redis_cache.set_json(key, canonical.to_cache_payload(), cache_ttl_seconds)

        ordered_products = [by_id[uid] for uid in ordered_ids if uid in by_id]
        return ordered_products, {
            "field_union_size": len(union_required_fields),
            "union_required_fields": sorted(union_required_fields),
            "enrichment_used": enrichment_used,
            "db_round_trips": db_round_trips,
            "redis_cache_hits": redis_hits,
        }

