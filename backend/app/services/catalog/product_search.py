from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from collections import OrderedDict
import json
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.product import Product, ProductEmbedding, StockStatus
from app.models.product_attribute import ProductAttributeValue
from app.models.product_search_projection import ProductSearchProjection
from app.schemas.chat import ProductCard
from app.services.catalog.attributes_service import eav_service


@dataclass
class ProductSearchResult:
    cards: List[ProductCard]
    distances: List[float]
    best_distance: Optional[float]
    distance_by_id: Dict[str, float]
    product_ids: List[Any] = field(default_factory=list)


@dataclass(frozen=True)
class _StructuredCacheEntry:
    payload: Dict[str, Any]
    expires_at: float


class CatalogProductSearchService:
    """Shared product retrieval service for chat and agentic tools."""

    _MATERIAL_FALLBACK_TOKENS: Dict[str, List[str]] = {
        "Titanium G23": ["titanium g23", "g23", "implant grade", "implant-grade"],
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

    def __init__(self, db: AsyncSession):
        self.db = db
        self.last_metrics: Dict[str, float] = {
            "vector_search_ms": 0.0,
            "db_product_lookup_ms": 0.0,
        }
        self.last_meta: Dict[str, Any] = {
            "structured_query_cache_hit": False,
        }
        self._structured_cache_hits = 0
        self._structured_cache_misses = 0
        self._structured_cache: OrderedDict[str, _StructuredCacheEntry] = OrderedDict()
        self._structured_cache_lock = threading.Lock()

    def _reset_metrics(self) -> None:
        self.last_metrics = {
            "vector_search_ms": 0.0,
            "db_product_lookup_ms": 0.0,
        }
        self.last_meta = {
            "structured_query_cache_hit": False,
        }

    def _add_metric(self, key: str, elapsed_ms: float) -> None:
        current = float(self.last_metrics.get(key, 0.0) or 0.0)
        self.last_metrics[key] = current + max(0.0, float(elapsed_ms))

    @staticmethod
    def _normalize_filter_map(attribute_filters: Optional[Dict[str, str]]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key, value in (attribute_filters or {}).items():
            clean_key = str(key or "").strip().lower()
            clean_value = str(value or "").strip()
            if not clean_key or not clean_value:
                continue
            out[clean_key] = clean_value
        return out

    @staticmethod
    def _normalize_filter_value(value: str) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _like_condition(column, expected_norm: str):
        return func.lower(func.coalesce(column, "")).like(f"%{expected_norm}%")

    @classmethod
    def _projection_filter_condition(cls, *, key: str, expected_norm: str):
        if not expected_norm:
            return None
        if key == "material":
            return or_(
                cls._like_condition(ProductSearchProjection.material_norm, expected_norm),
                cls._like_condition(ProductSearchProjection.search_text_norm, expected_norm),
            )
        if key == "jewelry_type":
            return cls._like_condition(ProductSearchProjection.jewelry_type_norm, expected_norm)
        if key == "gauge":
            return func.lower(func.coalesce(ProductSearchProjection.gauge_norm, "")) == expected_norm
        if key == "threading":
            return func.lower(func.coalesce(ProductSearchProjection.threading_norm, "")) == expected_norm
        if key == "color":
            return or_(
                cls._like_condition(ProductSearchProjection.color_norm, expected_norm),
                cls._like_condition(ProductSearchProjection.opal_color_norm, expected_norm),
                cls._like_condition(ProductSearchProjection.search_text_norm, expected_norm),
            )
        return cls._like_condition(ProductSearchProjection.search_text_norm, expected_norm)

    @staticmethod
    def _structured_cache_key(
        *,
        sku_token: Optional[str],
        attribute_filters: Dict[str, str],
        limit: int,
        candidate_cap: int,
        catalog_version: str,
        read_mode: str,
    ) -> str:
        payload = {
            "sku_token": str(sku_token or "").strip().lower(),
            "attribute_filters": attribute_filters,
            "limit": int(limit),
            "candidate_cap": int(candidate_cap),
            "catalog_version": str(catalog_version or "").strip().lower(),
            "read_mode": str(read_mode or "").strip().lower(),
        }
        raw = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        return raw

    def _structured_cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        if not bool(getattr(settings, "CHAT_STRUCTURED_QUERY_CACHE_ENABLED", True)):
            self._structured_cache_misses += 1
            return None
        now = time.time()
        with self._structured_cache_lock:
            entry = self._structured_cache.get(key)
            if entry is None:
                self._structured_cache_misses += 1
                return None
            if entry.expires_at and entry.expires_at < now:
                self._structured_cache.pop(key, None)
                self._structured_cache_misses += 1
                return None
            self._structured_cache.move_to_end(key)
            self._structured_cache_hits += 1
            return dict(entry.payload)

    def _structured_cache_set(self, key: str, payload: Dict[str, Any]) -> None:
        if not bool(getattr(settings, "CHAT_STRUCTURED_QUERY_CACHE_ENABLED", True)):
            return
        max_items = max(1, int(getattr(settings, "CHAT_STRUCTURED_QUERY_CACHE_MAX_ITEMS", 2000)))
        ttl_seconds = max(1, int(getattr(settings, "CHAT_STRUCTURED_QUERY_CACHE_TTL_SECONDS", 600)))
        expires_at = time.time() + float(ttl_seconds)
        with self._structured_cache_lock:
            self._structured_cache[key] = _StructuredCacheEntry(payload=dict(payload), expires_at=expires_at)
            self._structured_cache.move_to_end(key)
            while len(self._structured_cache) > max_items:
                self._structured_cache.popitem(last=False)

    def structured_cache_stats(self) -> Dict[str, Any]:
        with self._structured_cache_lock:
            size = len(self._structured_cache)
        total = int(self._structured_cache_hits + self._structured_cache_misses)
        hit_rate = float(self._structured_cache_hits / total) if total > 0 else 0.0
        return {
            "size": int(size),
            "hits": int(self._structured_cache_hits),
            "misses": int(self._structured_cache_misses),
            "hit_rate": round(hit_rate, 4),
        }

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

        search_text = str(getattr(product, "search_text", "") or "").lower()
        if not str(attrs.get("material") or "").strip():
            inferred_material = self._infer_from_search_text(
                search_text=search_text,
                token_map=self._MATERIAL_FALLBACK_TOKENS,
            )
            if inferred_material:
                attrs["material"] = inferred_material

        if not str(attrs.get("jewelry_type") or attrs.get("type") or "").strip():
            inferred_type = self._infer_from_search_text(
                search_text=search_text,
                token_map=self._JEWELRY_TYPE_FALLBACK_TOKENS,
            )
            if inferred_type:
                attrs["jewelry_type"] = inferred_type

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
    def _infer_from_search_text(
        *,
        search_text: str,
        token_map: Dict[str, List[str]],
    ) -> Optional[str]:
        text = str(search_text or "").strip().lower()
        if not text:
            return None
        for label, tokens in token_map.items():
            for token in tokens:
                needle = str(token or "").strip().lower()
                if needle and needle in text:
                    return label
        return None

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
        self._reset_metrics()
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
        vector_started = time.perf_counter()
        result = await self.db.execute(stmt)
        rows = result.all()
        self._add_metric("vector_search_ms", (time.perf_counter() - vector_started) * 1000.0)
        if not rows:
            return ProductSearchResult(cards=[], distances=[], best_distance=None, distance_by_id={})

        raw_distances = [float(distance) for _product, distance in rows]
        best_distance = min(raw_distances) if raw_distances else None

        ranked_rows: List[Tuple[Product, float]] = [
            (product, float(distance)) for product, distance in rows[:limit]
        ]
        lookup_started = time.perf_counter()
        cards = await self._cards_from_products([product for product, _distance in ranked_rows])
        self._add_metric("db_product_lookup_ms", (time.perf_counter() - lookup_started) * 1000.0)
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
        self._reset_metrics()
        for raw in candidates:
            candidate = self._clean_code_candidate(str(raw or ""))
            if not candidate:
                continue

            sku_started = time.perf_counter()
            sku_stmt = (
                select(Product)
                .where(Product.sku.ilike(candidate))
                .where(Product.is_active.is_(True))
                .limit(1)
            )
            sku_result = await self.db.execute(sku_stmt)
            self._add_metric("db_product_lookup_ms", (time.perf_counter() - sku_started) * 1000.0)
            sku_product = sku_result.scalar_one_or_none()
            if sku_product:
                cards_started = time.perf_counter()
                cards = await self._cards_from_products([sku_product])
                self._add_metric("db_product_lookup_ms", (time.perf_counter() - cards_started) * 1000.0)
                card_id = str(cards[0].id)
                return ProductSearchResult(
                    cards=cards,
                    distances=[0.0],
                    best_distance=0.0,
                    distance_by_id={card_id: 0.0},
                )

            master_started = time.perf_counter()
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
            self._add_metric("db_product_lookup_ms", (time.perf_counter() - master_started) * 1000.0)
            master_product = master_result.scalar_one_or_none()
            if not master_product:
                continue

            if master_product.group_id:
                variants_started = time.perf_counter()
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
                self._add_metric("db_product_lookup_ms", (time.perf_counter() - variants_started) * 1000.0)
                variants = list(variants_result.scalars().all())
            else:
                variants = [master_product]

            cards_started = time.perf_counter()
            cards = await self._cards_from_products(variants[: max(limit * 2, limit)])
            self._add_metric("db_product_lookup_ms", (time.perf_counter() - cards_started) * 1000.0)
            dist_map = {str(card.id): 0.0 for card in cards}
            return ProductSearchResult(
                cards=cards,
                distances=[0.0 for _ in cards[:5]],
                best_distance=0.0,
                distance_by_id=dist_map,
            )

        precheck_db_ms = float(self.last_metrics.get("db_product_lookup_ms", 0.0) or 0.0)
        result = await self.vector_search(query_embedding=query_embedding, limit=limit)
        vector_db_ms = float(self.last_metrics.get("db_product_lookup_ms", 0.0) or 0.0)
        self.last_metrics["db_product_lookup_ms"] = precheck_db_ms + vector_db_ms
        return result

    async def structured_search(
        self,
        *,
        sku_token: Optional[str],
        attribute_filters: Optional[Dict[str, str]],
        limit: int = 10,
        candidate_cap: Optional[int] = None,
        catalog_version: Optional[str] = None,
        return_ids_only: bool = False,
    ) -> tuple[ProductSearchResult, Dict[str, Any]]:
        self._reset_metrics()
        clean_filters = self._normalize_filter_map(attribute_filters)
        cap = max(50, int(candidate_cap or getattr(settings, "CHAT_STRUCTURED_CANDIDATE_CAP", 300)))
        clean_sku = self._clean_code_candidate(str(sku_token or ""))
        catalog_ver = str(catalog_version or getattr(settings, "CHAT_CATALOG_VERSION", "v1"))
        projection_read_enabled = bool(getattr(settings, "CHAT_PROJECTION_READ_ENABLED", False))
        read_mode = "projection" if projection_read_enabled else "eav"

        cache_key = self._structured_cache_key(
            sku_token=clean_sku,
            attribute_filters=clean_filters,
            limit=limit,
            candidate_cap=cap,
            catalog_version=catalog_ver,
            read_mode=read_mode,
        )
        cached_payload = self._structured_cache_get(cache_key)
        if isinstance(cached_payload, dict):
            cached_product_ids = [item for item in list(cached_payload.get("product_ids", []) or []) if item]
            cached_cards = [] if return_ids_only else [ProductCard(**item) for item in list(cached_payload.get("cards", []) or [])]
            distance_by_id = {str(card.id): 0.0 for card in cached_cards}
            cached_projection_hit = bool(cached_payload.get("projection_hit", False))
            cached_projection_ms = float(cached_payload.get("projection_lookup_ms", 0.0) or 0.0)
            cached_resolved_mode = str(cached_payload.get("structured_read_mode") or read_mode)
            self.last_meta["structured_query_cache_hit"] = True
            return (
                ProductSearchResult(
                    cards=cached_cards,
                    distances=[0.0 for _ in cached_cards[:5]],
                    best_distance=0.0 if cached_cards else None,
                    distance_by_id=distance_by_id,
                    product_ids=cached_product_ids,
                ),
                {
                    "structured_query_cache_hit": True,
                    "structured_candidate_cap": cap,
                    "structured_filter_count": len(clean_filters),
                    "structured_used_sku": bool(clean_sku),
                    "projection_hit": cached_projection_hit,
                    "projection_lookup_ms": cached_projection_ms,
                    "structured_read_mode": cached_resolved_mode,
                },
            )

        candidates: List[Product] = []
        projection_hit = False
        projection_lookup_ms = 0.0
        resolved_mode = "eav"

        if projection_read_enabled:
            projection_started = time.perf_counter()
            try:
                projection_stmt = (
                    select(Product)
                    .join(ProductSearchProjection, ProductSearchProjection.product_id == Product.id)
                    .where(Product.is_active.is_(True))
                    .where(ProductSearchProjection.is_active.is_(True))
                )
                if clean_sku:
                    projection_stmt = projection_stmt.where(
                        func.lower(ProductSearchProjection.sku_norm) == clean_sku.lower()
                    )

                for key, expected in clean_filters.items():
                    expected_norm = self._normalize_filter_value(expected)
                    condition = self._projection_filter_condition(key=key, expected_norm=expected_norm)
                    if condition is not None:
                        projection_stmt = projection_stmt.where(condition)

                projection_stmt = projection_stmt.order_by(
                    case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                    Product.created_at.desc(),
                ).limit(max(1, min(cap, 2000)))
                projection_result = await self.db.execute(projection_stmt)
                candidates = list(projection_result.scalars().all())
                projection_hit = bool(candidates)
                resolved_mode = "projection" if projection_hit else "projection_fallback_eav"
            except Exception:
                candidates = []
                projection_hit = False
                resolved_mode = "projection_unavailable_fallback_eav"
            finally:
                projection_lookup_ms = (time.perf_counter() - projection_started) * 1000.0
                self._add_metric("db_product_lookup_ms", projection_lookup_ms)

        lookup_started = time.perf_counter()
        if not candidates and clean_sku:
            sku_stmt = (
                select(Product)
                .where(func.lower(Product.sku) == clean_sku.lower())
                .where(Product.is_active.is_(True))
                .limit(max(1, int(limit)))
            )
            sku_result = await self.db.execute(sku_stmt)
            candidates = list(sku_result.scalars().all())

        if not candidates and clean_filters:
            definitions = await eav_service.get_definitions_by_name(self.db, list(clean_filters.keys()))
            if len(definitions) == len(clean_filters):
                first_key = "material" if "material" in clean_filters else sorted(clean_filters.keys())[0]
                first_def = definitions[first_key]
                first_value = clean_filters[first_key]
                first_value_norm = self._normalize_filter_value(first_value)
                material_fallback_used = False
                candidate_stmt = (
                    select(ProductAttributeValue.product_id)
                    .where(ProductAttributeValue.attribute_id == first_def.id)
                    .where(func.lower(func.coalesce(ProductAttributeValue.value, "")) == first_value_norm)
                    .limit(cap)
                )
                candidate_ids = [row[0] for row in (await self.db.execute(candidate_stmt)).all()]
                if first_key == "material" and not candidate_ids and first_value_norm:
                    material_fallback_stmt = (
                        select(Product.id)
                        .where(Product.is_active.is_(True))
                        .where(func.lower(func.coalesce(Product.search_text, "")).like(f"%{first_value_norm}%"))
                        .limit(cap)
                    )
                    candidate_ids = [row[0] for row in (await self.db.execute(material_fallback_stmt)).all()]
                    material_fallback_used = bool(candidate_ids)

                if candidate_ids:
                    if len(clean_filters) > 1:
                        conditions = []
                        filtered_count = 0
                        for name, expected in clean_filters.items():
                            if material_fallback_used and name == "material":
                                continue
                            definition = definitions.get(name)
                            if not definition:
                                conditions = []
                                break
                            expected_norm = self._normalize_filter_value(expected)
                            conditions.append(
                                and_(
                                    ProductAttributeValue.attribute_id == definition.id,
                                    func.lower(func.coalesce(ProductAttributeValue.value, "")) == expected_norm,
                                )
                            )
                            filtered_count += 1
                        if conditions:
                            refined_subq = (
                                select(ProductAttributeValue.product_id)
                                .where(ProductAttributeValue.product_id.in_(candidate_ids))
                                .where(or_(*conditions))
                                .group_by(ProductAttributeValue.product_id)
                                .having(
                                    func.count(func.distinct(ProductAttributeValue.attribute_id))
                                    == filtered_count
                                )
                                .subquery()
                            )
                            product_stmt = (
                                select(Product)
                                .where(Product.id.in_(select(refined_subq.c.product_id)))
                                .where(Product.is_active.is_(True))
                                .order_by(
                                    case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                                    Product.created_at.desc(),
                                )
                                .limit(max(1, int(limit)))
                            )
                            if material_fallback_used and first_value_norm:
                                product_stmt = product_stmt.where(
                                    func.lower(func.coalesce(Product.search_text, "")).like(f"%{first_value_norm}%")
                                )
                            product_result = await self.db.execute(product_stmt)
                            candidates = list(product_result.scalars().all())
                        else:
                            product_stmt = (
                                select(Product)
                                .where(Product.id.in_(candidate_ids))
                                .where(Product.is_active.is_(True))
                                .order_by(
                                    case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                                    Product.created_at.desc(),
                                )
                                .limit(max(1, int(limit)))
                            )
                            if material_fallback_used and first_value_norm:
                                product_stmt = product_stmt.where(
                                    func.lower(func.coalesce(Product.search_text, "")).like(f"%{first_value_norm}%")
                                )
                            product_result = await self.db.execute(product_stmt)
                            candidates = list(product_result.scalars().all())
                    else:
                        product_stmt = (
                            select(Product)
                            .where(Product.id.in_(candidate_ids))
                            .where(Product.is_active.is_(True))
                            .order_by(
                                case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                                Product.created_at.desc(),
                            )
                            .limit(max(1, int(limit)))
                        )
                        if material_fallback_used and first_value_norm:
                            product_stmt = product_stmt.where(
                                func.lower(func.coalesce(Product.search_text, "")).like(f"%{first_value_norm}%")
                            )
                        product_result = await self.db.execute(product_stmt)
                        candidates = list(product_result.scalars().all())
        self._add_metric("db_product_lookup_ms", (time.perf_counter() - lookup_started) * 1000.0)

        product_ids = [product.id for product in candidates[: max(1, int(limit))]]
        cards: List[ProductCard] = []
        distance_by_id: Dict[str, float] = {}
        if not return_ids_only:
            cards_started = time.perf_counter()
            cards = await self._cards_from_products(candidates)
            self._add_metric("db_product_lookup_ms", (time.perf_counter() - cards_started) * 1000.0)
            distance_by_id = {str(card.id): 0.0 for card in cards}

        payload = {
            "cards": [card.dict() for card in cards],
            "product_ids": [str(pid) for pid in product_ids],
            "projection_hit": projection_hit,
            "projection_lookup_ms": round(float(projection_lookup_ms), 2),
            "structured_read_mode": resolved_mode if projection_read_enabled else "eav",
        }
        self._structured_cache_set(cache_key, payload)

        return (
            ProductSearchResult(
                cards=cards,
                distances=[0.0 for _ in cards[:5]],
                best_distance=0.0 if cards else None,
                distance_by_id=distance_by_id,
                product_ids=product_ids,
            ),
            {
                "structured_query_cache_hit": False,
                "structured_candidate_cap": cap,
                "structured_filter_count": len(clean_filters),
                "structured_used_sku": bool(clean_sku),
                "projection_hit": projection_hit,
                "projection_lookup_ms": round(float(projection_lookup_ms), 2),
                "structured_read_mode": resolved_mode if projection_read_enabled else "eav",
            },
        )

    async def structured_count(
        self,
        *,
        sku_token: Optional[str],
        attribute_filters: Optional[Dict[str, str]],
    ) -> int:
        clean_filters = self._normalize_filter_map(attribute_filters)
        clean_sku = self._clean_code_candidate(str(sku_token or ""))
        projection_read_enabled = bool(getattr(settings, "CHAT_PROJECTION_READ_ENABLED", False))

        if projection_read_enabled:
            try:
                projection_stmt = (
                    select(func.count(func.distinct(Product.id)))
                    .select_from(Product)
                    .join(ProductSearchProjection, ProductSearchProjection.product_id == Product.id)
                    .where(Product.is_active.is_(True))
                    .where(ProductSearchProjection.is_active.is_(True))
                )
                if clean_sku:
                    projection_stmt = projection_stmt.where(
                        func.lower(ProductSearchProjection.sku_norm) == clean_sku.lower()
                    )
                for key, expected in clean_filters.items():
                    condition = self._projection_filter_condition(
                        key=key,
                        expected_norm=self._normalize_filter_value(expected),
                    )
                    if condition is not None:
                        projection_stmt = projection_stmt.where(condition)
                result = await self.db.execute(projection_stmt)
                return int(result.scalar() or 0)
            except Exception:
                pass

        if clean_sku:
            stmt = (
                select(func.count(Product.id))
                .where(Product.is_active.is_(True))
                .where(func.lower(Product.sku) == clean_sku.lower())
            )
            result = await self.db.execute(stmt)
            return int(result.scalar() or 0)

        if clean_filters:
            definitions = await eav_service.get_definitions_by_name(self.db, list(clean_filters.keys()))
            if len(definitions) != len(clean_filters):
                return 0

            first_key = "material" if "material" in clean_filters else sorted(clean_filters.keys())[0]
            first_def = definitions[first_key]
            first_value_norm = self._normalize_filter_value(clean_filters[first_key])
            candidate_stmt = (
                select(ProductAttributeValue.product_id)
                .where(ProductAttributeValue.attribute_id == first_def.id)
                .where(func.lower(func.coalesce(ProductAttributeValue.value, "")) == first_value_norm)
            )
            candidate_ids = [row[0] for row in (await self.db.execute(candidate_stmt)).all()]
            material_fallback_used = False
            if first_key == "material" and not candidate_ids and first_value_norm:
                material_fallback_stmt = (
                    select(Product.id)
                    .where(Product.is_active.is_(True))
                    .where(func.lower(func.coalesce(Product.search_text, "")).like(f"%{first_value_norm}%"))
                )
                candidate_ids = [row[0] for row in (await self.db.execute(material_fallback_stmt)).all()]
                material_fallback_used = bool(candidate_ids)
            if not candidate_ids:
                return 0

            if len(clean_filters) == 1:
                stmt = (
                    select(func.count(Product.id))
                    .where(Product.id.in_(candidate_ids))
                    .where(Product.is_active.is_(True))
                )
                if material_fallback_used and first_value_norm:
                    stmt = stmt.where(func.lower(func.coalesce(Product.search_text, "")).like(f"%{first_value_norm}%"))
                result = await self.db.execute(stmt)
                return int(result.scalar() or 0)

            conditions = []
            filtered_count = 0
            for name, expected in clean_filters.items():
                if material_fallback_used and name == "material":
                    continue
                definition = definitions.get(name)
                if not definition:
                    return 0
                expected_norm = self._normalize_filter_value(expected)
                conditions.append(
                    and_(
                        ProductAttributeValue.attribute_id == definition.id,
                        func.lower(func.coalesce(ProductAttributeValue.value, "")) == expected_norm,
                    )
                )
                filtered_count += 1

            if not conditions:
                return 0

            refined_subq = (
                select(ProductAttributeValue.product_id)
                .where(ProductAttributeValue.product_id.in_(candidate_ids))
                .where(or_(*conditions))
                .group_by(ProductAttributeValue.product_id)
                .having(func.count(func.distinct(ProductAttributeValue.attribute_id)) == filtered_count)
                .subquery()
            )
            stmt = (
                select(func.count(Product.id))
                .where(Product.id.in_(select(refined_subq.c.product_id)))
                .where(Product.is_active.is_(True))
            )
            if material_fallback_used and first_value_norm:
                stmt = stmt.where(func.lower(func.coalesce(Product.search_text, "")).like(f"%{first_value_norm}%"))
            result = await self.db.execute(stmt)
            return int(result.scalar() or 0)

        stmt = select(func.count(Product.id)).where(Product.is_active.is_(True))
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

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
