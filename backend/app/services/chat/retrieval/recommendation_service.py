import re
from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.product import ProductEmbedding
from app.schemas.chat import ProductCard
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.chat.text_normalization import normalize_user_text
import app.services.chat.presentation.product_presentation as product_presentation


@dataclass
class RecommendationExpansion:
    cards: List[ProductCard]
    product_ids: List[str]
    distance_by_id: Dict[str, float]
    source: str
    used_anchor_embedding: bool
    used_query_embedding: bool


@dataclass
class RecommendationRankResult:
    items: List[Any]
    meta: Dict[str, Any]


@dataclass(frozen=True)
class ComplementaryProfile:
    anchor_type: str
    label: str
    search_query: str
    allowed_type_tokens: tuple[str, ...]
    match_terms: tuple[str, ...]
    preferred_threading: Optional[str] = None
    preferred_gauge: Optional[str] = None


class RecommendationService:
    _PROFILE_KEYS = (
        "category",
        "jewelry_type",
        "design",
        "material",
        "color",
        "opal_color",
        "pearl_color",
        "crystal_color",
        "cz_color",
        "gauge",
        "threading",
        "length",
        "size",
        "outer_diameter",
        "ring_size",
        "height",
    )
    _TEXT_MATCH_KEYS = {
        "category",
        "jewelry_type",
        "design",
        "material",
        "color",
        "opal_color",
        "pearl_color",
        "crystal_color",
        "cz_color",
        "threading",
        "packing_option",
        "rack",
    }
    _HIGH_SIGNAL_KEYS = {
        "category",
        "jewelry_type",
        "design",
        "material",
        "color",
        "gauge",
        "length",
        "size",
        "outer_diameter",
        "ring_size",
    }
    _COMPLEMENTARY_TYPE_MAP: Dict[str, Dict[str, Any]] = {
        "labret": {
            "label": "Labret tops",
            "query": "labret tops ends threadless tops internally threaded tops externally threaded balls discs spikes attachments",
            "allowed_type_tokens": (
                "attachment",
                "attachments",
                "top",
                "tops",
                "end",
                "ends",
                "ball",
                "balls",
                "disc",
                "discs",
                "spike",
                "spikes",
            ),
            "match_terms": (
                "labret top",
                "labret tops",
                "threadless top",
                "replacement ball",
                "attachment",
                "attachments",
                "disc",
                "ball",
                "spike",
            ),
        },
        "labrets": {
            "label": "Labret tops",
            "query": "labret tops ends threadless tops internally threaded tops externally threaded balls discs spikes attachments",
            "allowed_type_tokens": (
                "attachment",
                "attachments",
                "top",
                "tops",
                "end",
                "ends",
                "ball",
                "balls",
                "disc",
                "discs",
                "spike",
                "spikes",
            ),
            "match_terms": (
                "labret top",
                "labret tops",
                "threadless top",
                "replacement ball",
                "attachment",
                "attachments",
                "disc",
                "ball",
                "spike",
            ),
        },
        "barbell": {
            "label": "Barbell attachments",
            "query": "barbell replacement balls ends spikes attachments internally threaded externally threaded threadless attachments",
            "allowed_type_tokens": (
                "attachment",
                "attachments",
                "top",
                "tops",
                "end",
                "ends",
                "ball",
                "balls",
                "spike",
                "spikes",
            ),
            "match_terms": (
                "replacement ball",
                "barbell end",
                "barbell ends",
                "attachment",
                "attachments",
                "spike",
                "ball",
            ),
        },
        "barbells": {
            "label": "Barbell attachments",
            "query": "barbell replacement balls ends spikes attachments internally threaded externally threaded threadless attachments",
            "allowed_type_tokens": (
                "attachment",
                "attachments",
                "top",
                "tops",
                "end",
                "ends",
                "ball",
                "balls",
                "spike",
                "spikes",
            ),
            "match_terms": (
                "replacement ball",
                "barbell end",
                "barbell ends",
                "attachment",
                "attachments",
                "spike",
                "ball",
            ),
        },
        "circularbarbell": {
            "label": "Barbell attachments",
            "query": "circular barbell replacement balls ends spikes attachments internally threaded externally threaded threadless attachments",
            "allowed_type_tokens": (
                "attachment",
                "attachments",
                "top",
                "tops",
                "end",
                "ends",
                "ball",
                "balls",
                "spike",
                "spikes",
            ),
            "match_terms": (
                "replacement ball",
                "barbell end",
                "barbell ends",
                "attachment",
                "attachments",
                "spike",
                "ball",
            ),
        },
        "circularbarbells": {
            "label": "Barbell attachments",
            "query": "circular barbell replacement balls ends spikes attachments internally threaded externally threaded threadless attachments",
            "allowed_type_tokens": (
                "attachment",
                "attachments",
                "top",
                "tops",
                "end",
                "ends",
                "ball",
                "balls",
                "spike",
                "spikes",
            ),
            "match_terms": (
                "replacement ball",
                "barbell end",
                "barbell ends",
                "attachment",
                "attachments",
                "spike",
                "ball",
            ),
        },
        "ring": {
            "label": "Ring beads",
            "query": "replacement balls beads closures captive ring beads closure balls",
            "allowed_type_tokens": (
                "ball",
                "balls",
                "bead",
                "beads",
                "closure",
                "closures",
            ),
            "match_terms": (
                "replacement ball",
                "bead",
                "beads",
                "closure",
                "closures",
                "captiv",
            ),
        },
        "rings": {
            "label": "Ring beads",
            "query": "replacement balls beads closures captive ring beads closure balls",
            "allowed_type_tokens": (
                "ball",
                "balls",
                "bead",
                "beads",
                "closure",
                "closures",
            ),
            "match_terms": (
                "replacement ball",
                "bead",
                "beads",
                "closure",
                "closures",
                "captiv",
            ),
        },
        "ballclosurering": {
            "label": "Ring beads",
            "query": "replacement balls beads closures captive ring beads closure balls",
            "allowed_type_tokens": (
                "ball",
                "balls",
                "bead",
                "beads",
                "closure",
                "closures",
            ),
            "match_terms": (
                "replacement ball",
                "bead",
                "beads",
                "closure",
                "closures",
                "captiv",
            ),
        },
        "ballclosurerings": {
            "label": "Ring beads",
            "query": "replacement balls beads closures captive ring beads closure balls",
            "allowed_type_tokens": (
                "ball",
                "balls",
                "bead",
                "beads",
                "closure",
                "closures",
            ),
            "match_terms": (
                "replacement ball",
                "bead",
                "beads",
                "closure",
                "closures",
                "captiv",
            ),
        },
        "captivebeadring": {
            "label": "Ring beads",
            "query": "replacement balls beads closures captive ring beads closure balls",
            "allowed_type_tokens": (
                "ball",
                "balls",
                "bead",
                "beads",
                "closure",
                "closures",
            ),
            "match_terms": (
                "replacement ball",
                "bead",
                "beads",
                "closure",
                "closures",
                "captiv",
            ),
        },
        "captivebeadrings": {
            "label": "Ring beads",
            "query": "replacement balls beads closures captive ring beads closure balls",
            "allowed_type_tokens": (
                "ball",
                "balls",
                "bead",
                "beads",
                "closure",
                "closures",
            ),
            "match_terms": (
                "replacement ball",
                "bead",
                "beads",
                "closure",
                "closures",
                "captiv",
            ),
        },
        "plug": {
            "label": "Plug accessories",
            "query": "plug accessories o-rings replacement o rings tunnel accessories",
            "allowed_type_tokens": ("accessory", "accessories", "oring", "orings"),
            "match_terms": ("o-ring", "o ring", "oring", "accessory", "replacement ring"),
        },
        "plugs": {
            "label": "Plug accessories",
            "query": "plug accessories o-rings replacement o rings tunnel accessories",
            "allowed_type_tokens": ("accessory", "accessories", "oring", "orings"),
            "match_terms": ("o-ring", "o ring", "oring", "accessory", "replacement ring"),
        },
        "tunnel": {
            "label": "Tunnel accessories",
            "query": "tunnel accessories o-rings replacement o rings plug accessories",
            "allowed_type_tokens": ("accessory", "accessories", "oring", "orings"),
            "match_terms": ("o-ring", "o ring", "oring", "accessory", "replacement ring"),
        },
        "tunnels": {
            "label": "Tunnel accessories",
            "query": "tunnel accessories o-rings replacement o rings plug accessories",
            "allowed_type_tokens": ("accessory", "accessories", "oring", "orings"),
            "match_terms": ("o-ring", "o ring", "oring", "accessory", "replacement ring"),
        },
    }

    def __init__(self, *, db: AsyncSession, catalog_search: CatalogProductSearchService):
        self.db = db
        self._catalog_search = catalog_search

    @classmethod
    def detect_mode(cls, *, user_text: str) -> str:
        return cls.resolve_mode(user_text=user_text)

    @classmethod
    def resolve_mode(
        cls,
        *,
        requested_mode: str = "",
        user_text: str = "",
        anchor_products: Sequence[Any] = (),
        attribute_filters: Optional[Dict[str, str]] = None,
    ) -> str:
        mode = str(requested_mode or "").strip().lower()
        if mode in {"similar_items", "complementary_items"}:
            return mode

        normalized_text = normalize_user_text(user_text)
        complementary_cues = (
            "what goes with",
            "goes with",
            "compatible",
            "complementary",
            "pair",
            "pairs with",
            "match",
            "matches",
            "accessory",
            "accessories",
            "attachment",
            "attachments",
        )
        if normalized_text and any(cue in normalized_text for cue in complementary_cues):
            profile = cls.build_complementary_profile(
                anchor_products=anchor_products,
                attribute_filters=attribute_filters,
            )
            if profile is not None or anchor_products:
                return "complementary_items"

        return "similar_items"

    @classmethod
    def build_complementary_profile(
        cls,
        *,
        anchor_products: Sequence[Any],
        attribute_filters: Optional[Dict[str, str]] = None,
    ) -> Optional[ComplementaryProfile]:
        anchor_type_raw = cls._context_value(
            key="jewelry_type",
            anchor_products=anchor_products,
            attribute_filters=attribute_filters,
        )
        normalized_anchor_type = cls._normalize_jewelry_type(anchor_type_raw)
        mapping = cls._COMPLEMENTARY_TYPE_MAP.get(normalized_anchor_type)
        if not mapping:
            return None

        preferred_threading = normalize_user_text(
            cls._context_value(
                key="threading",
                anchor_products=anchor_products,
                attribute_filters=attribute_filters,
            )
        ) or None
        preferred_gauge = normalize_user_text(
            cls._context_value(
                key="gauge",
                anchor_products=anchor_products,
                attribute_filters=attribute_filters,
            )
        ) or None
        query_parts = [str(mapping.get("query") or "").strip()]
        if preferred_threading:
            query_parts.append(preferred_threading)
        if preferred_gauge:
            query_parts.append(preferred_gauge)
        search_query = " ".join(part for part in query_parts if part).strip()
        return ComplementaryProfile(
            anchor_type=normalized_anchor_type,
            label=str(mapping.get("label") or "").strip(),
            search_query=search_query,
            allowed_type_tokens=tuple(str(item) for item in list(mapping.get("allowed_type_tokens") or [])),
            match_terms=tuple(str(item) for item in list(mapping.get("match_terms") or [])),
            preferred_threading=preferred_threading,
            preferred_gauge=preferred_gauge,
        )

    @classmethod
    def build_complementary_search_query(
        cls,
        *,
        anchor_products: Sequence[Any],
        attribute_filters: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        profile = cls.build_complementary_profile(
            anchor_products=anchor_products,
            attribute_filters=attribute_filters,
        )
        if profile is None:
            return None
        return profile.search_query or None

    @classmethod
    def build_complementary_label(
        cls,
        *,
        anchor_products: Sequence[Any],
        attribute_filters: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        profile = cls.build_complementary_profile(
            anchor_products=anchor_products,
            attribute_filters=attribute_filters,
        )
        if profile is None:
            return None
        return profile.label or None

    async def expand_card_candidates(
        self,
        *,
        anchor_product_ids: Sequence[Any],
        query_embedding: Optional[List[float]],
        limit: int,
    ) -> RecommendationExpansion:
        search_vector = await self._build_anchor_embedding(anchor_product_ids=anchor_product_ids)
        source = "anchor_embedding"
        used_anchor_embedding = search_vector is not None
        used_query_embedding = False

        if search_vector is None and query_embedding:
            search_vector = [float(value) for value in list(query_embedding)]
            source = "query_embedding"
            used_query_embedding = True

        if not search_vector:
            return RecommendationExpansion(
                cards=[],
                product_ids=[],
                distance_by_id={},
                source="none",
                used_anchor_embedding=False,
                used_query_embedding=False,
            )

        candidate_limit = max(int(limit or 0), product_presentation.PRODUCT_DISPLAY_LIMIT * 3)
        result = await self._catalog_search.vector_search(
            query_embedding=search_vector,
            limit=max(1, candidate_limit),
            candidate_limit=max(candidate_limit * 4, 36),
        )
        return RecommendationExpansion(
            cards=list(result.cards or []),
            product_ids=[str(card.id) for card in list(result.cards or [])],
            distance_by_id={str(key): float(value) for key, value in dict(result.distance_by_id or {}).items()},
            source=source,
            used_anchor_embedding=used_anchor_embedding,
            used_query_embedding=used_query_embedding,
        )

    def rank_product_cards(
        self,
        *,
        candidates: Sequence[ProductCard],
        attribute_filters: Optional[Dict[str, str]],
        user_text: str,
        distance_by_id: Optional[Dict[str, float]] = None,
        anchor_products: Optional[Sequence[ProductCard]] = None,
        recommendation_mode: Optional[str] = None,
        limit: int = 10,
        exclude_product_ids: Optional[Sequence[Any]] = None,
    ) -> RecommendationRankResult:
        return self._rank_candidates(
            candidates=list(candidates or []),
            attribute_filters=attribute_filters,
            user_text=user_text,
            distance_by_id=distance_by_id,
            anchor_products=list(anchor_products or []),
            recommendation_mode=recommendation_mode,
            limit=limit,
            exclude_product_ids=exclude_product_ids,
        )

    def rank_canonical_products(
        self,
        *,
        candidates: Sequence[Any],
        attribute_filters: Optional[Dict[str, str]],
        user_text: str,
        distance_by_id: Optional[Dict[str, float]] = None,
        anchor_products: Optional[Sequence[Any]] = None,
        recommendation_mode: Optional[str] = None,
        limit: Optional[int] = 10,
        exclude_product_ids: Optional[Sequence[Any]] = None,
    ) -> RecommendationRankResult:
        return self._rank_candidates(
            candidates=list(candidates or []),
            attribute_filters=attribute_filters,
            user_text=user_text,
            distance_by_id=distance_by_id,
            anchor_products=list(anchor_products or []),
            recommendation_mode=recommendation_mode,
            limit=limit,
            exclude_product_ids=exclude_product_ids,
        )

    async def _build_anchor_embedding(self, *, anchor_product_ids: Sequence[Any]) -> Optional[List[float]]:
        uuids = self._normalize_uuid_list(anchor_product_ids)
        if not uuids or not hasattr(self.db, "execute"):
            return None

        model = getattr(settings, "PRODUCT_EMBEDDING_MODEL", settings.EMBEDDING_MODEL)
        stmt = (
            select(ProductEmbedding.embedding)
            .where(ProductEmbedding.product_id.in_(uuids))
            .where(ProductEmbedding.model == model)
        )
        result = await self.db.execute(stmt)
        if result is None or not hasattr(result, "scalars"):
            return None
        rows = list(result.scalars().all())
        vectors: List[List[float]] = []
        for row in rows:
            if row is None:
                continue
            vector = [float(value) for value in list(row)]
            if vector:
                vectors.append(vector)
        if not vectors:
            return None

        dimension = len(vectors[0])
        if dimension <= 0:
            return None
        totals = [0.0] * dimension
        valid_count = 0
        for vector in vectors:
            if len(vector) != dimension:
                continue
            valid_count += 1
            for idx, value in enumerate(vector):
                totals[idx] += float(value)
        if valid_count <= 0:
            return None
        return [value / float(valid_count) for value in totals]

    def _rank_candidates(
        self,
        *,
        candidates: Sequence[Any],
        attribute_filters: Optional[Dict[str, str]],
        user_text: str,
        distance_by_id: Optional[Dict[str, float]],
        anchor_products: Sequence[Any],
        recommendation_mode: Optional[str],
        limit: int,
        exclude_product_ids: Optional[Sequence[Any]],
    ) -> RecommendationRankResult:
        clean_filters = self._clean_filter_map(attribute_filters)
        mode = str(recommendation_mode or "").strip().lower()
        if mode not in {"similar_items", "complementary_items"}:
            mode = self.resolve_mode(
                user_text=user_text,
                anchor_products=anchor_products,
                attribute_filters=attribute_filters,
            )
        exclude_ids = {self._candidate_id(raw) for raw in list(exclude_product_ids or []) if self._candidate_id(raw)}
        anchor_profile = self._build_anchor_profile(anchor_products=anchor_products, clean_filters=clean_filters)
        anchor_price = self._anchor_price(anchor_products)
        complementary_profile = None
        if mode == "complementary_items":
            complementary_profile = self.build_complementary_profile(
                anchor_products=anchor_products,
                attribute_filters=attribute_filters,
            )
        ranked_rows: List[Dict[str, Any]] = []
        evaluation_count = 0

        for order_index, candidate in enumerate(list(candidates or [])):
            candidate_id = self._candidate_id(candidate)
            if not candidate_id or candidate_id in exclude_ids:
                continue
            evaluation_count += 1
            attrs = self._candidate_attrs(candidate)
            score = 0.0
            matched_filters = 0
            matched_anchor_fields = 0
            distance = None
            if isinstance(distance_by_id, dict) and candidate_id in distance_by_id:
                distance = float(distance_by_id[candidate_id])
                score += self._distance_score(distance)

            in_stock = self._candidate_in_stock(candidate)
            if in_stock:
                score += 1.4
            stock_qty = self._candidate_stock_qty(candidate)
            if stock_qty is not None and stock_qty > 0:
                score += min(float(stock_qty), 20.0) / 20.0 * 0.35

            for key, expected in clean_filters.items():
                match_score = self._attribute_match_score(
                    actual=attrs.get(key),
                    expected=expected,
                    key=key,
                )
                if match_score <= 0.0:
                    continue
                matched_filters += 1
                score += match_score * self._filter_weight(key)

            for key, expected_values in anchor_profile.items():
                best_match = 0.0
                for expected in expected_values:
                    best_match = max(
                        best_match,
                        self._attribute_match_score(
                            actual=attrs.get(key),
                            expected=expected,
                            key=key,
                        ),
                    )
                if best_match <= 0.0:
                    continue
                matched_anchor_fields += 1
                score += best_match * self._anchor_weight(key)

            candidate_price = self._candidate_price(candidate)
            price_gap = abs(candidate_price - anchor_price) if anchor_price is not None and candidate_price is not None else None
            score += self._price_score(candidate_price=candidate_price, anchor_price=anchor_price)

            if mode == "complementary_items":
                score += self._complementary_adjustment(
                    candidate=candidate,
                    anchor_products=anchor_products,
                    profile=complementary_profile,
                )

            # Small order preservation so recommendation reranking stays close to upstream retrieval quality.
            score += max(0.0, 0.15 - (float(order_index) * 0.01))

            ranked_rows.append(
                {
                    "item": candidate,
                    "score": float(score),
                    "distance": distance,
                    "in_stock": in_stock,
                    "matched_filters": matched_filters,
                    "matched_anchor_fields": matched_anchor_fields,
                    "price_gap": price_gap if price_gap is not None else float("inf"),
                }
            )

        ranked_rows.sort(
            key=lambda row: (
                -float(row["score"]),
                0 if bool(row["in_stock"]) else 1,
                float(row["distance"]) if row["distance"] is not None else 99.0,
                float(row["price_gap"]),
                self._candidate_name(row["item"]).lower(),
            )
        )

        deduped_items: List[Any] = []
        deduped_debug: List[Dict[str, Any]] = []
        seen_masters = set()
        for row in ranked_rows:
            item = row["item"]
            master_code = product_presentation.master_code_from_product(item).lower().strip()
            if not master_code or master_code in seen_masters:
                continue
            seen_masters.add(master_code)
            deduped_items.append(item)
            deduped_debug.append(
                {
                    "product_id": self._candidate_id(item),
                    "master_code": master_code,
                    "score": round(float(row["score"]), 4),
                    "matched_filters": int(row["matched_filters"]),
                    "matched_anchor_fields": int(row["matched_anchor_fields"]),
                    "distance": None if row["distance"] is None else round(float(row["distance"]), 4),
                }
            )
            if limit is not None and len(deduped_items) >= max(1, int(limit)):
                break

        return RecommendationRankResult(
            items=deduped_items,
            meta={
                "recommendation_mode": mode,
                "recommendation_candidates_evaluated": evaluation_count,
                "recommendation_ranked_count": len(deduped_items),
                "recommendation_anchor_count": len(anchor_products),
                "recommendation_filter_count": len(clean_filters),
                "recommendation_complementary_label": complementary_profile.label if complementary_profile else None,
                "recommendation_complementary_query": complementary_profile.search_query if complementary_profile else None,
                "recommendation_top_scores": deduped_debug[:5],
            },
        )

    @classmethod
    def _clean_filter_map(cls, attribute_filters: Optional[Dict[str, str]]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key, value in dict(attribute_filters or {}).items():
            clean_key = str(key or "").strip().lower()
            clean_value = normalize_user_text(value)
            if not clean_key or not clean_value:
                continue
            out[clean_key] = clean_value
        return out

    @classmethod
    def _build_anchor_profile(
        cls,
        *,
        anchor_products: Sequence[Any],
        clean_filters: Dict[str, str],
    ) -> Dict[str, List[str]]:
        values_by_key: Dict[str, List[str]] = {}
        for key, value in clean_filters.items():
            values_by_key[key] = [value]

        for candidate in list(anchor_products or [])[:3]:
            attrs = cls._candidate_attrs(candidate)
            for key in cls._PROFILE_KEYS:
                normalized = normalize_user_text(attrs.get(key))
                if not normalized:
                    continue
                bucket = values_by_key.setdefault(key, [])
                if normalized not in bucket:
                    bucket.append(normalized)
        return values_by_key

    @classmethod
    def _anchor_price(cls, anchor_products: Sequence[Any]) -> Optional[float]:
        prices = [
            price
            for price in (cls._candidate_price(candidate) for candidate in list(anchor_products or [])[:3])
            if price is not None and price > 0.0
        ]
        if not prices:
            return None
        return float(median(prices))

    @classmethod
    def _distance_score(cls, distance: float) -> float:
        normalized = max(0.0, 1.0 - min(max(float(distance), 0.0), 1.0))
        return normalized * 2.8

    @classmethod
    def _filter_weight(cls, key: str) -> float:
        return 1.6 if key in cls._HIGH_SIGNAL_KEYS else 1.2

    @classmethod
    def _anchor_weight(cls, key: str) -> float:
        return 0.8 if key in cls._HIGH_SIGNAL_KEYS else 0.5

    @classmethod
    def _price_score(cls, *, candidate_price: Optional[float], anchor_price: Optional[float]) -> float:
        if candidate_price is None or candidate_price <= 0.0:
            return 0.0
        if anchor_price is None or anchor_price <= 0.0:
            return max(0.0, 0.2 - (candidate_price / 1000.0))
        ratio_gap = abs(candidate_price - anchor_price) / max(anchor_price, 1.0)
        return max(-0.6, 0.8 - min(ratio_gap, 1.4))

    @classmethod
    def _complementary_adjustment(
        cls,
        *,
        candidate: Any,
        anchor_products: Sequence[Any],
        profile: Optional[ComplementaryProfile],
    ) -> float:
        if not anchor_products:
            return 0.0
        attrs = cls._candidate_attrs(candidate)
        candidate_type = cls._normalize_jewelry_type(attrs.get("jewelry_type") or attrs.get("type"))
        candidate_text = cls._candidate_text(candidate)
        if profile is None:
            if not candidate_type:
                return 0.0
            if candidate_type == cls._normalize_jewelry_type(
                cls._candidate_attrs(anchor_products[0]).get("jewelry_type")
            ):
                return -0.6
            return 0.35

        score = 0.0
        if candidate_type and candidate_type in set(profile.allowed_type_tokens):
            score += 2.8
        elif candidate_type and candidate_type == profile.anchor_type:
            score -= 1.4
        else:
            score -= 0.5

        if any(term in candidate_text for term in profile.match_terms):
            score += 1.9
        else:
            score -= 0.6

        candidate_threading = normalize_user_text(attrs.get("threading"))
        if profile.preferred_threading:
            if candidate_threading == profile.preferred_threading:
                score += 1.4
            elif candidate_threading:
                score -= 1.0
            elif profile.preferred_threading in candidate_text:
                score += 0.8

        candidate_gauge = normalize_user_text(attrs.get("gauge"))
        if profile.preferred_gauge:
            if candidate_gauge == profile.preferred_gauge:
                score += 0.8
            elif candidate_gauge:
                score -= 0.5

        return score

    @classmethod
    def _attribute_match_score(cls, *, actual: Any, expected: str, key: str) -> float:
        actual_text = normalize_user_text(actual)
        expected_text = normalize_user_text(expected)
        if not actual_text or not expected_text:
            return 0.0
        if actual_text == expected_text:
            return 1.0
        if key in cls._TEXT_MATCH_KEYS:
            if expected_text in actual_text or actual_text in expected_text:
                return 0.7
            actual_tokens = set(cls._tokenize(actual_text))
            expected_tokens = set(cls._tokenize(expected_text))
            if actual_tokens and expected_tokens and actual_tokens.intersection(expected_tokens):
                return 0.5
        return 0.0

    @staticmethod
    def _tokenize(value: str) -> List[str]:
        return [token for token in re.split(r"[^a-z0-9]+", str(value or "").lower()) if token]

    @classmethod
    def _normalize_jewelry_type(cls, value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", normalize_user_text(value))

    @staticmethod
    def _candidate_attrs(candidate: Any) -> Dict[str, Any]:
        return dict(getattr(candidate, "attributes", {}) or {})

    @classmethod
    def _candidate_text(cls, candidate: Any) -> str:
        attrs = cls._candidate_attrs(candidate)
        chunks = [
            getattr(candidate, "title", None),
            getattr(candidate, "name", None),
            getattr(candidate, "description", None),
            attrs.get("jewelry_type"),
            attrs.get("type"),
            attrs.get("design"),
            attrs.get("threading"),
            attrs.get("category"),
        ]
        return normalize_user_text(" ".join(str(chunk or "") for chunk in chunks if str(chunk or "").strip()))

    @staticmethod
    def _candidate_price(candidate: Any) -> Optional[float]:
        raw = getattr(candidate, "price", None)
        if raw is None:
            return None
        try:
            return float(raw)
        except Exception:
            return None

    @classmethod
    def _candidate_name(cls, candidate: Any) -> str:
        for raw in (
            getattr(candidate, "title", None),
            getattr(candidate, "name", None),
            getattr(candidate, "sku", None),
            getattr(candidate, "product_id", None),
            getattr(candidate, "id", None),
        ):
            text = str(raw or "").strip()
            if text:
                return text
        return ""

    @classmethod
    def _candidate_id(cls, candidate: Any) -> str:
        if candidate is None:
            return ""
        if isinstance(candidate, (str, UUID)):
            return str(candidate)
        for raw in (
            getattr(candidate, "product_id", None),
            getattr(candidate, "id", None),
        ):
            text = str(raw or "").strip()
            if text:
                return text
        return ""

    @classmethod
    def _candidate_in_stock(cls, candidate: Any) -> bool:
        if hasattr(candidate, "in_stock"):
            return bool(getattr(candidate, "in_stock"))
        raw = getattr(candidate, "stock_status", None)
        if raw is None:
            return False
        return str(raw).strip().lower() == "in_stock"

    @classmethod
    def _candidate_stock_qty(cls, candidate: Any) -> Optional[int]:
        raw = getattr(candidate, "stock_qty", None)
        if raw is None:
            return None
        try:
            return int(raw)
        except Exception:
            return None

    @classmethod
    def _normalize_uuid_list(cls, values: Sequence[Any]) -> List[UUID]:
        out: List[UUID] = []
        seen = set()
        for raw in list(values or []):
            try:
                uid = raw if isinstance(raw, UUID) else UUID(str(raw))
            except Exception:
                continue
            if uid in seen:
                continue
            seen.add(uid)
            out.append(uid)
        return out

    @classmethod
    def _context_value(
        cls,
        *,
        key: str,
        anchor_products: Sequence[Any],
        attribute_filters: Optional[Dict[str, str]],
    ) -> Optional[str]:
        filters = dict(attribute_filters or {})
        value = str(filters.get(key) or "").strip()
        if value:
            return value
        for candidate in list(anchor_products or [])[:3]:
            attrs = cls._candidate_attrs(candidate)
            raw = attrs.get(key)
            text = str(raw or "").strip()
            if text:
                return text
        return None
