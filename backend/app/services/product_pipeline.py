from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.core.config import settings
from app.schemas.chat import ChatContext, ProductCard

SearchProductsFn = Callable[
    ...,
    Awaitable[Tuple[List[ProductCard], List[float], Optional[float], Dict[str, float]]],
]
SearchSkuFn = Callable[..., Awaitable[List[ProductCard]]]
InferJewelryFn = Callable[[str], Optional[str]]
LogEventFn = Callable[..., None]


@dataclass
class ProductPipelineResult:
    product_cards: List[ProductCard]
    product_top_distances: List[float]
    product_best: Optional[float]
    product_gate_decision: str


class ProductPipeline:
    def __init__(
        self,
        *,
        search_products: SearchProductsFn,
        search_products_by_exact_sku: SearchSkuFn,
        infer_jewelry_type_filter: InferJewelryFn,
        log_event: LogEventFn,
    ) -> None:
        self._search_products = search_products
        self._search_products_by_exact_sku = search_products_by_exact_sku
        self._infer_jewelry_type_filter = infer_jewelry_type_filter
        self._log_event = log_event

    async def sku_shortcut(self, *, sku: Optional[str], limit: int) -> List[ProductCard]:
        if not sku:
            return []
        return await self._search_products_by_exact_sku(sku=sku, limit=limit)

    async def run(
        self,
        *,
        ctx: ChatContext,
        product_embedding: Optional[List[float]],
        product_topk: int,
        use_products: bool,
        is_policy_intent: bool,
        looks_like_product: bool,
        run_id: str,
    ) -> ProductPipelineResult:
        product_cards_all: List[ProductCard] = []
        product_top_distances: List[float] = []
        product_best: Optional[float] = None
        product_distance_by_id: Dict[str, float] = {}

        # Policy keywords: allow skipping product search to avoid irrelevant work.
        if use_products and not (is_policy_intent and not looks_like_product):
            product_retrieve_k = max(product_topk * 5, product_topk)
            product_cards_all, product_top_distances, product_best, product_distance_by_id = await self._search_products(
                query_embedding=product_embedding or [],
                limit=product_retrieve_k,
                run_id=run_id,
            )

        jewelry_type_filter = self._infer_jewelry_type_filter(ctx.text)
        if jewelry_type_filter:
            filtered: List[ProductCard] = []
            for p in product_cards_all:
                jt = None
                if isinstance(p.attributes, dict):
                    jt = p.attributes.get("jewelry_type")
                if jt is not None and str(jt).strip().lower() == jewelry_type_filter.lower():
                    filtered.append(p)
            product_cards_filtered = filtered
        else:
            product_cards_filtered = product_cards_all

        product_cards = product_cards_filtered[:product_topk]
        product_best_for_gate: Optional[float] = None
        if product_cards:
            bests = []
            for p in product_cards:
                d = product_distance_by_id.get(str(p.id))
                if d is not None:
                    bests.append(float(d))
            product_best_for_gate = min(bests) if bests else product_best

        strict = float(getattr(settings, "PRODUCT_DISTANCE_STRICT", 0.35))
        loose = float(getattr(settings, "PRODUCT_DISTANCE_LOOSE", 0.45))
        product_gate_decision = "none"
        if looks_like_product and product_best_for_gate is not None:
            if product_best_for_gate <= strict:
                product_gate_decision = "strict"
            elif product_best_for_gate <= loose:
                product_gate_decision = "loose"

        self._log_event(
            run_id=run_id,
            location="chat_service.product.route_gate",
            data={
                "looks_like_product": looks_like_product,
                "jewelry_type_filter": jewelry_type_filter,
                "product_best": product_best,
                "product_best_for_gate": product_best_for_gate,
                "strict": strict,
                "loose": loose,
                "decision": product_gate_decision,
                "count": len(product_cards),
            },
        )

        return ProductPipelineResult(
            product_cards=product_cards,
            product_top_distances=product_top_distances,
            product_best=product_best,
            product_gate_decision=product_gate_decision,
        )
