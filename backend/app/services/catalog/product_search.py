from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.product import Product, ProductEmbedding, StockStatus
from app.schemas.chat import ProductCard
from app.services.catalog.attributes_service import eav_service


@dataclass
class ProductSearchResult:
    cards: List[ProductCard]
    distances: List[float]
    best_distance: Optional[float]
    distance_by_id: Dict[str, float]


class CatalogProductSearchService:
    """Shared product retrieval service for chat and agentic tools."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _merge_product_attrs(
        base_attrs: Optional[Dict[str, Any]],
        eav_attrs: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        attrs = dict(base_attrs or {})
        if eav_attrs:
            for key, value in eav_attrs.items():
                if value is None:
                    continue
                attrs[key] = value
        return attrs

    def _product_to_card(
        self,
        *,
        product: Product,
        eav_attrs: Optional[Dict[str, Any]] = None,
    ) -> ProductCard:
        attrs = self._merge_product_attrs(product.attributes, eav_attrs)
        return ProductCard(
            id=product.id,
            object_id=product.object_id,
            sku=product.sku,
            legacy_sku=product.legacy_sku or [],
            name=product.name,
            description=product.description,
            price=product.price,
            currency=product.currency,
            stock_status=product.stock_status,
            image_url=product.image_url,
            product_url=product.product_url,
            attributes=attrs,
        )

    @staticmethod
    def _clean_code_candidate(token: str) -> str:
        return token.strip().strip(".,;:()[]{}")

    async def _cards_from_products(self, products: Sequence[Product]) -> List[ProductCard]:
        if not products:
            return []
        attr_map = await eav_service.get_product_attributes(self.db, [p.id for p in products])
        return [
            self._product_to_card(product=product, eav_attrs=attr_map.get(product.id))
            for product in products
        ]

    async def vector_search(
        self,
        *,
        query_embedding: List[float],
        limit: int = 10,
        candidate_limit: Optional[int] = None,
        candidate_multiplier: int = 3,
    ) -> ProductSearchResult:
        distance_col = ProductEmbedding.embedding.cosine_distance(query_embedding).label("distance")
        model = getattr(settings, "PRODUCT_EMBEDDING_MODEL", settings.EMBEDDING_MODEL)
        cap = max(limit, candidate_limit or 0)
        if cap <= 0:
            cap = max(limit, min(60, limit * max(1, candidate_multiplier)))

        subq = (
            select(
                ProductEmbedding.product_id.label("product_id"),
                distance_col,
            )
            .join(Product, Product.id == ProductEmbedding.product_id)
            .where(Product.is_active.is_(True))
            .where(or_(ProductEmbedding.model.is_(None), ProductEmbedding.model == model))
            .order_by(distance_col)
            .limit(cap)
            .subquery()
        )
        stmt = (
            select(Product, subq.c.distance)
            .join(subq, Product.id == subq.c.product_id)
            .order_by(
                case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                subq.c.distance,
            )
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        if not rows:
            return ProductSearchResult(cards=[], distances=[], best_distance=None, distance_by_id={})

        raw_distances = [float(distance) for _product, distance in rows]
        best_distance = min(raw_distances) if raw_distances else None

        ranked_rows: List[Tuple[Product, float]] = [
            (product, float(distance)) for product, distance in rows[:limit]
        ]
        cards = await self._cards_from_products([product for product, _distance in ranked_rows])
        distances = [distance for _product, distance in ranked_rows]
        distance_by_id = {str(product.id): distance for product, distance in ranked_rows}

        return ProductSearchResult(
            cards=cards,
            distances=distances[:5],
            best_distance=best_distance,
            distance_by_id=distance_by_id,
        )

    async def smart_search(
        self,
        *,
        query_embedding: List[float],
        candidates: Sequence[str],
        limit: int = 10,
    ) -> ProductSearchResult:
        for raw in candidates:
            candidate = self._clean_code_candidate(str(raw or ""))
            if not candidate:
                continue

            sku_stmt = (
                select(Product)
                .where(Product.sku.ilike(candidate))
                .where(Product.is_active.is_(True))
                .limit(1)
            )
            sku_result = await self.db.execute(sku_stmt)
            sku_product = sku_result.scalar_one_or_none()
            if sku_product:
                cards = await self._cards_from_products([sku_product])
                card_id = str(cards[0].id)
                return ProductSearchResult(
                    cards=cards,
                    distances=[0.0],
                    best_distance=0.0,
                    distance_by_id={card_id: 0.0},
                )

            master_stmt = (
                select(Product)
                .where(Product.is_active.is_(True))
                .where(
                    or_(
                        Product.master_code.ilike(candidate),
                        Product.name.ilike(candidate),
                    )
                )
                .limit(1)
            )
            master_result = await self.db.execute(master_stmt)
            master_product = master_result.scalar_one_or_none()
            if not master_product:
                continue

            if master_product.group_id:
                variants_stmt = (
                    select(Product)
                    .where(Product.group_id == master_product.group_id)
                    .where(Product.is_active.is_(True))
                    .order_by(
                        case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                        Product.created_at.desc(),
                    )
                )
                variants_result = await self.db.execute(variants_stmt)
                variants = list(variants_result.scalars().all())
            else:
                variants = [master_product]

            cards = await self._cards_from_products(variants[: max(limit * 2, limit)])
            dist_map = {str(card.id): 0.0 for card in cards}
            return ProductSearchResult(
                cards=cards,
                distances=[0.0 for _ in cards[:5]],
                best_distance=0.0,
                distance_by_id=dist_map,
            )

        return await self.vector_search(query_embedding=query_embedding, limit=limit)

    async def get_product_by_sku(self, sku: str) -> Optional[ProductCard]:
        candidate = self._clean_code_candidate(sku)
        if not candidate:
            return None
        stmt = (
            select(Product)
            .where(func.lower(Product.sku) == candidate.lower())
            .where(Product.is_active.is_(True))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        product = result.scalar_one_or_none()
        if not product:
            return None
        cards = await self._cards_from_products([product])
        return cards[0] if cards else None

    async def get_inventory_snapshot(self, sku: str) -> Dict[str, Any]:
        candidate = self._clean_code_candidate(sku)
        if not candidate:
            return {"found": False, "sku": sku, "source": "db"}

        stmt = (
            select(Product)
            .where(func.lower(Product.sku) == candidate.lower())
            .where(Product.is_active.is_(True))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        product = result.scalar_one_or_none()
        if not product:
            return {"found": False, "sku": candidate, "source": "db"}

        last_sync = product.last_stock_sync_at
        last_sync_at = last_sync.isoformat() if isinstance(last_sync, datetime) else None
        return {
            "found": True,
            "sku": product.sku,
            "stock_status": getattr(product.stock_status, "value", str(product.stock_status)),
            "last_stock_sync_at": last_sync_at,
            "source": "db",
        }
