from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from collections import OrderedDict
import json
import re
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.product import Product, ProductEmbedding, StockStatus
from app.models.product_attribute import ProductAttributeValue
from app.schemas.chat import ProductCard
from app.services.catalog.attributes_service import eav_service
from app.services.catalog.search_policy import uses_eav_partial_match
from app.services.chat.parsing.attribute_normalization import normalize_text
from app.services.chat.parsing.search_policy import ATTRIBUTE_KEY_ALIASES, normalize_filter_map


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


@dataclass(frozen=True)
class _AttributeFilterSlot:
    attribute_id: int
    key: str
    expected_norm: str


class CatalogProductSearchService:
    """Shared product retrieval service for chat and agentic tools."""

    _LEXICAL_NOISE_TOKENS = {
        "buy",
        "have",
        "item",
        "items",
        "jewelry",
        "need",
        "please",
        "product",
        "products",
        "show",
        "want",
    }

    _FILTER_KEY_ALIASES: Dict[str, str] = dict(ATTRIBUTE_KEY_ALIASES)

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
        return normalize_filter_map(
            attribute_filters,
            key_aliases=CatalogProductSearchService._FILTER_KEY_ALIASES,
        )

    @staticmethod
    def _normalize_filter_value(value: str) -> str:
        return normalize_text(value)

    @staticmethod
    def _split_filter_values(value: Any, *, is_multivalue: bool) -> List[Any]:
        if not is_multivalue:
            return [value]

        values: List[Any] = []

        def _collect(raw: Any) -> None:
            if raw is None:
                return
            if isinstance(raw, (list, tuple, set)):
                for nested in raw:
                    _collect(nested)
                return
            text = str(raw or "").strip()
            if not text:
                return
            if ";;" in text:
                for token in text.split(";;"):
                    _collect(token)
                return
            if ";" in text:
                for token in text.split(";"):
                    _collect(token)
                return
            values.append(text)

        _collect(value)
        return values

    @staticmethod
    def _like_condition(column, expected_norm: str):
        return func.lower(func.coalesce(column, "")).like(f"%{expected_norm}%")

    @staticmethod
    def _eav_value_expr():
        return func.coalesce(
            ProductAttributeValue.value_norm,
            func.lower(func.coalesce(ProductAttributeValue.value, "")),
        )

    @classmethod
    def _eav_filter_condition(cls, *, attribute_id: int, key: str, expected_norm: str):
        value_expr = cls._eav_value_expr()
        if uses_eav_partial_match(key):
            return and_(
                ProductAttributeValue.attribute_id == attribute_id,
                value_expr.like(f"%{expected_norm}%"),
            )
        return and_(
            ProductAttributeValue.attribute_id == attribute_id,
            value_expr == expected_norm,
        )

    @classmethod
    def _attribute_filter_slots(
        cls,
        *,
        definitions: Mapping[str, Any],
        clean_filters: Mapping[str, Any],
    ) -> List[_AttributeFilterSlot]:
        slots: List[_AttributeFilterSlot] = []
        seen: set[Tuple[int, str]] = set()
        for name, expected in dict(clean_filters or {}).items():
            definition = definitions.get(name)
            if not definition:
                continue
            is_multivalue = bool(getattr(definition, "is_multivalue", False)) or name == "category"
            for raw_value in cls._split_filter_values(expected, is_multivalue=is_multivalue):
                expected_norm = cls._normalize_filter_value(raw_value)
                if not expected_norm:
                    continue
                dedupe_key = (int(definition.id), expected_norm)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                slots.append(
                    _AttributeFilterSlot(
                        attribute_id=int(definition.id),
                        key=str(name),
                        expected_norm=expected_norm,
                    )
                )
        return slots

    @classmethod
    def _attribute_slot_exists(cls, slot: _AttributeFilterSlot):
        return (
            select(ProductAttributeValue.id)
            .where(ProductAttributeValue.product_id == Product.id)
            .where(
                cls._eav_filter_condition(
                    attribute_id=slot.attribute_id,
                    key=slot.key,
                    expected_norm=slot.expected_norm,
                )
            )
            .exists()
        )

    @staticmethod
    def _master_partition_expr():
        return func.lower(func.coalesce(Product.master_code, Product.sku))

    @staticmethod
    def _representative_rank_exprs() -> Dict[str, Any]:
        return {
            "stock_rank": case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
            "image_rank": case((func.length(func.coalesce(Product.image_url, "")) > 0, 0), else_=1),
        }

    async def _products_by_ids(self, product_ids: Sequence[Any]) -> List[Product]:
        ids = [item for item in list(product_ids or []) if item]
        if not ids:
            return []
        result = await self.db.execute(select(Product).where(Product.id.in_(ids)))
        products_by_id = {str(product.id): product for product in result.scalars().all()}
        return [products_by_id[str(product_id)] for product_id in ids if str(product_id) in products_by_id]

    async def _master_representative_product_ids(
        self,
        *,
        filter_slots: Sequence[_AttributeFilterSlot],
        limit: int,
        search_text_norm: str = "",
    ) -> List[Any]:
        slots = list(filter_slots or [])
        text_filter = str(search_text_norm or "").strip()
        if not slots and not text_filter:
            return []

        rank_exprs = self._representative_rank_exprs()
        row_number = func.row_number().over(
            partition_by=self._master_partition_expr(),
            order_by=(
                rank_exprs["stock_rank"].asc(),
                rank_exprs["image_rank"].asc(),
                Product.created_at.desc(),
                Product.sku.asc(),
            ),
        ).label("rn")
        ranked_stmt = (
            select(
                Product.id.label("product_id"),
                Product.master_code.label("master_code"),
                Product.sku.label("sku"),
                Product.created_at.label("created_at"),
                rank_exprs["stock_rank"].label("stock_rank"),
                rank_exprs["image_rank"].label("image_rank"),
                row_number,
            )
            .where(Product.is_active.is_(True))
        )
        for slot in slots:
            ranked_stmt = ranked_stmt.where(self._attribute_slot_exists(slot))
        if text_filter:
            ranked_stmt = ranked_stmt.where(
                func.lower(func.coalesce(Product.search_text, "")).like(f"%{text_filter}%")
            )

        ranked = ranked_stmt.subquery()
        stmt = (
            select(ranked.c.product_id)
            .where(ranked.c.rn == 1)
            .order_by(
                ranked.c.stock_rank.asc(),
                ranked.c.image_rank.asc(),
                ranked.c.created_at.desc(),
                ranked.c.master_code.asc(),
                ranked.c.sku.asc(),
            )
            .limit(max(1, int(limit or 1)))
        )
        result = await self.db.execute(stmt)
        return [row[0] for row in result.all()]

    async def _count_master_representatives(
        self,
        *,
        filter_slots: Sequence[_AttributeFilterSlot],
        search_text_norm: str = "",
    ) -> int:
        slots = list(filter_slots or [])
        text_filter = str(search_text_norm or "").strip()
        if not slots and not text_filter:
            return 0
        stmt = (
            select(func.count(func.distinct(self._master_partition_expr())))
            .where(Product.is_active.is_(True))
        )
        for slot in slots:
            stmt = stmt.where(self._attribute_slot_exists(slot))
        if text_filter:
            stmt = stmt.where(func.lower(func.coalesce(Product.search_text, "")).like(f"%{text_filter}%"))
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    @staticmethod
    def _structured_cache_key(
        *,
        sku_token: Optional[str],
        attribute_filters: Dict[str, str],
        limit: int,
        candidate_cap: int,
        catalog_version: str,
    ) -> str:
        payload = {
            "sku_token": str(sku_token or "").strip().lower(),
            "attribute_filters": attribute_filters,
            "limit": int(limit),
            "candidate_cap": int(candidate_cap),
            "catalog_version": str(catalog_version or "").strip().lower(),
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
            search_text=product.search_text,
        )

    @staticmethod
    def _clean_code_candidate(token: str) -> str:
        return token.strip().strip(".,;:()[]{}")

    @classmethod
    def _normalize_lookup_code(cls, token: str) -> str:
        cleaned = cls._clean_code_candidate(str(token or "")).lower()
        return re.sub(r"[^a-z0-9]+", "", cleaned)

    @classmethod
    def _significant_query_terms(cls, text: str) -> List[str]:
        normalized = normalize_text(text)
        if not normalized:
            return []
        terms: List[str] = []
        seen: set[str] = set()
        for raw in normalized.split():
            token = str(raw or "").strip().lower()
            if len(token) < 4 or token in cls._LEXICAL_NOISE_TOKENS:
                continue
            if token not in seen:
                seen.add(token)
                terms.append(token)
            if len(token) >= 7:
                prefix = token[:6]
                if prefix and prefix not in seen:
                    seen.add(prefix)
                    terms.append(prefix)
        return terms

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
            .where(ProductEmbedding.model == model)
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

    async def lexical_search(
        self,
        *,
        query_text: str,
        limit: int = 10,
        candidate_limit: Optional[int] = None,
    ) -> ProductSearchResult:
        self._reset_metrics()
        normalized_query = normalize_text(query_text)
        if not normalized_query:
            return ProductSearchResult(cards=[], distances=[], best_distance=None, distance_by_id={})

        cap = max(limit, candidate_limit or 0)
        if cap <= 0:
            cap = max(limit, min(60, limit * 4))

        document_text = func.concat_ws(
            " ",
            func.coalesce(Product.search_text, ""),
            func.coalesce(Product.description, ""),
            func.coalesce(Product.master_code, ""),
            func.coalesce(Product.sku, ""),
        )
        document = func.to_tsvector(
            "english",
            document_text,
        )
        query = func.websearch_to_tsquery("english", normalized_query)
        rank = func.ts_rank_cd(document, query).label("rank")

        stmt = (
            select(Product, rank)
            .where(Product.is_active.is_(True))
            .where(document.op("@@")(query))
            .order_by(
                case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                rank.desc(),
            )
            .limit(cap)
        )

        lexical_started = time.perf_counter()
        result = await self.db.execute(stmt)
        rows = result.all()
        self._add_metric("db_product_lookup_ms", (time.perf_counter() - lexical_started) * 1000.0)
        if not rows:
            search_blob = func.lower(document_text)
            score_expr = None
            for term in self._significant_query_terms(normalized_query):
                condition = case((search_blob.like(f"%{term}%"), 1.0), else_=0.0)
                score_expr = condition if score_expr is None else score_expr + condition
            if score_expr is not None:
                fallback_rank = score_expr.label("rank")
                fallback_stmt = (
                    select(Product, fallback_rank)
                    .where(Product.is_active.is_(True))
                    .where(fallback_rank > 0)
                    .order_by(
                        case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                        fallback_rank.desc(),
                    )
                    .limit(cap)
                )
                fallback_started = time.perf_counter()
                fallback_result = await self.db.execute(fallback_stmt)
                rows = fallback_result.all()
                self._add_metric("db_product_lookup_ms", (time.perf_counter() - fallback_started) * 1000.0)
        if not rows:
            return ProductSearchResult(cards=[], distances=[], best_distance=None, distance_by_id={})

        ranked_rows: List[Tuple[Product, float]] = [
            (product, float(score or 0.0)) for product, score in rows[:limit]
        ]
        cards_started = time.perf_counter()
        cards = await self._cards_from_products([product for product, _score in ranked_rows])
        self._add_metric("db_product_lookup_ms", (time.perf_counter() - cards_started) * 1000.0)
        score_by_id = {str(product.id): score for product, score in ranked_rows}
        scores = [score for _product, score in ranked_rows]
        best_score = max(scores) if scores else None

        return ProductSearchResult(
            cards=cards,
            distances=[],
            best_distance=best_score,
            distance_by_id=score_by_id,
        )

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

        cache_key = self._structured_cache_key(
            sku_token=clean_sku,
            attribute_filters=clean_filters,
            limit=limit,
            candidate_cap=cap,
            catalog_version=catalog_ver,
        )
        cached_payload = self._structured_cache_get(cache_key)
        if isinstance(cached_payload, dict):
            cached_product_ids = [item for item in list(cached_payload.get("product_ids", []) or []) if item]
            cached_cards = [] if return_ids_only else [ProductCard(**item) for item in list(cached_payload.get("cards", []) or [])]
            distance_by_id = {str(card.id): 0.0 for card in cached_cards}
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
                    "structured_used_master_code": False,
                },
            )

        candidates: List[Product] = []
        master_product_ids: List[Any] = []
        master_code_lookup_used = False
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

        if not candidates and clean_sku:
            master_stmt = (
                select(Product)
                .where(Product.is_active.is_(True))
                .where(func.lower(Product.master_code) == clean_sku.lower())
                .order_by(
                    case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                    Product.created_at.desc(),
                )
                .limit(1)
            )
            master_result = await self.db.execute(master_stmt)
            master_product = master_result.scalar_one_or_none()
            if master_product:
                master_code_lookup_used = True
                if master_product.group_id:
                    variants_stmt = (
                        select(Product)
                        .where(Product.group_id == master_product.group_id)
                        .where(Product.is_active.is_(True))
                        .order_by(
                            case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                            Product.created_at.desc(),
                        )
                        .limit(max(1, int(limit)))
                    )
                    variants_result = await self.db.execute(variants_stmt)
                    candidates = list(variants_result.scalars().all())
                else:
                    candidates = [master_product]

        if not candidates and clean_filters:
            definitions = await eav_service.get_definitions_by_name(self.db, list(clean_filters.keys()))
            if len(definitions) == len(clean_filters):
                filter_slots = self._attribute_filter_slots(
                    definitions=definitions,
                    clean_filters=clean_filters,
                )
                if filter_slots:
                    master_product_ids = await self._master_representative_product_ids(
                        filter_slots=filter_slots,
                        limit=max(1, int(limit)),
                    )
                    if not master_product_ids and len(filter_slots) == 1:
                        first_key = "material" if "material" in clean_filters else sorted(clean_filters.keys())[0]
                        first_value_norm = filter_slots[0].expected_norm
                        if first_key == "material" and first_value_norm:
                            master_product_ids = await self._master_representative_product_ids(
                                filter_slots=[],
                                search_text_norm=first_value_norm,
                                limit=max(1, int(limit)),
                            )
                    if master_product_ids and not return_ids_only:
                        candidates = await self._products_by_ids(master_product_ids)
                if not master_product_ids and len(filter_slots) > 1:
                    product_stmt = (
                        select(Product)
                        .where(Product.is_active.is_(True))
                        .order_by(
                            case((Product.stock_status == StockStatus.in_stock, 0), else_=1),
                            Product.created_at.desc(),
                        )
                        .limit(max(1, int(limit)))
                    )
                    for slot in filter_slots:
                        slot_subq = (
                            select(ProductAttributeValue.product_id)
                            .where(
                                self._eav_filter_condition(
                                    attribute_id=slot.attribute_id,
                                    key=slot.key,
                                    expected_norm=slot.expected_norm,
                                )
                            )
                            .subquery()
                        )
                        product_stmt = product_stmt.where(Product.id.in_(select(slot_subq.c.product_id)))
                    product_result = await self.db.execute(product_stmt)
                    candidates = list(product_result.scalars().all())
                elif not master_product_ids and len(filter_slots) == 1:
                    first_key = "material" if "material" in clean_filters else sorted(clean_filters.keys())[0]
                    first_slot = filter_slots[0]
                    first_value_norm = first_slot.expected_norm
                    material_fallback_used = False
                    candidate_stmt = (
                        select(ProductAttributeValue.product_id)
                        .where(
                            self._eav_filter_condition(
                                attribute_id=first_slot.attribute_id,
                                key=first_slot.key,
                                expected_norm=first_value_norm,
                            )
                        )
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

        product_ids = list(master_product_ids or [product.id for product in candidates[: max(1, int(limit))]])
        cards: List[ProductCard] = []
        distance_by_id: Dict[str, float] = {}
        if not return_ids_only:
            cards_started = time.perf_counter()
            cards = await self._cards_from_products(candidates)
            self._add_metric("db_product_lookup_ms", (time.perf_counter() - cards_started) * 1000.0)
            distance_by_id = {str(card.id): 0.0 for card in cards}

        payload = {
            "cards": [card.model_dump() for card in cards],
            "product_ids": [str(pid) for pid in product_ids],
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
                "structured_master_first_used": bool(master_product_ids),
                "structured_used_sku": bool(clean_sku),
                "structured_used_master_code": bool(master_code_lookup_used),
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

        if clean_sku:
            stmt = (
                select(func.count(Product.id))
                .where(Product.is_active.is_(True))
                .where(func.lower(Product.sku) == clean_sku.lower())
            )
            result = await self.db.execute(stmt)
            count = int(result.scalar() or 0)
            if count:
                return count

            master_stmt = (
                select(Product)
                .where(Product.is_active.is_(True))
                .where(func.lower(Product.master_code) == clean_sku.lower())
                .limit(1)
            )
            master_result = await self.db.execute(master_stmt)
            master_product = master_result.scalar_one_or_none()
            if not master_product:
                return 0
            if master_product.group_id:
                group_stmt = (
                    select(func.count(Product.id))
                    .where(Product.is_active.is_(True))
                    .where(Product.group_id == master_product.group_id)
                )
                group_result = await self.db.execute(group_stmt)
                return int(group_result.scalar() or 0)
            return 1

        if clean_filters:
            definitions = await eav_service.get_definitions_by_name(self.db, list(clean_filters.keys()))
            if len(definitions) != len(clean_filters):
                return 0

            filter_slots = self._attribute_filter_slots(
                definitions=definitions,
                clean_filters=clean_filters,
            )
            if not filter_slots:
                return 0

            first_key = "material" if "material" in clean_filters else sorted(clean_filters.keys())[0]
            first_slot = filter_slots[0]
            first_value_norm = first_slot.expected_norm
            material_fallback_used = False
            if first_key == "material" and first_value_norm and len(filter_slots) == 1:
                first_condition = self._eav_filter_condition(
                    attribute_id=first_slot.attribute_id,
                    key=first_slot.key,
                    expected_norm=first_value_norm,
                )
                material_exists_stmt = (
                    select(ProductAttributeValue.product_id)
                    .where(first_condition)
                    .limit(1)
                )
                material_fallback_used = (await self.db.execute(material_exists_stmt)).first() is None

            if material_fallback_used and first_value_norm:
                return await self._count_master_representatives(
                    filter_slots=[],
                    search_text_norm=first_value_norm,
                )

            return await self._count_master_representatives(filter_slots=filter_slots)

        stmt = select(func.count(func.distinct(self._master_partition_expr()))).where(Product.is_active.is_(True))
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

    async def resolve_product_reference(
        self,
        reference: str,
        *,
        max_candidates: int = 5,
    ) -> Dict[str, Any]:
        candidate = self._clean_code_candidate(reference)
        if not candidate:
            return {"status": "not_found", "reference": reference, "matched_by": ""}

        normalized_candidate = self._normalize_lookup_code(candidate)
        exact_stmt = (
            select(Product)
            .where(Product.is_active.is_(True))
            .where(
                or_(
                    func.lower(Product.sku) == candidate.lower(),
                    func.lower(Product.master_code) == candidate.lower(),
                    Product.legacy_sku.any(candidate),
                )
            )
            .limit(max(1, int(max_candidates)))
        )
        exact_result = await self.db.execute(exact_stmt)
        exact_products = list(exact_result.scalars().all())
        if len(exact_products) == 1:
            cards = await self._cards_from_products(exact_products)
            return {
                "status": "resolved",
                "reference": candidate,
                "matched_by": "direct_reference",
                "product": cards[0] if cards else None,
            }
        if len(exact_products) > 1:
            cards = await self._cards_from_products(exact_products[: max_candidates])
            return {
                "status": "ambiguous",
                "reference": candidate,
                "matched_by": "direct_reference",
                "candidates": cards,
            }

        if normalized_candidate:
            normalized_stmt = (
                select(Product)
                .where(Product.is_active.is_(True))
                .where(
                    or_(
                        func.regexp_replace(func.lower(Product.sku), r"[^a-z0-9]+", "", "g")
                        == normalized_candidate,
                        func.regexp_replace(func.lower(Product.master_code), r"[^a-z0-9]+", "", "g")
                        == normalized_candidate,
                    )
                )
                .limit(max(1, int(max_candidates)))
            )
            normalized_result = await self.db.execute(normalized_stmt)
            normalized_products = list(normalized_result.scalars().all())
            if len(normalized_products) == 1:
                cards = await self._cards_from_products(normalized_products)
                return {
                    "status": "resolved",
                    "reference": candidate,
                    "matched_by": "normalized_reference",
                    "product": cards[0] if cards else None,
                }
            if len(normalized_products) > 1:
                cards = await self._cards_from_products(normalized_products[: max_candidates])
                return {
                    "status": "ambiguous",
                    "reference": candidate,
                    "matched_by": "normalized_reference",
                    "candidates": cards,
                }

        return {"status": "not_found", "reference": candidate, "matched_by": ""}

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
