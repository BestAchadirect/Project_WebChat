from __future__ import annotations

from typing import List, Tuple

from app.schemas.chat import KnowledgeSource, ProductCard


class ProductContextAssembler:
    @staticmethod
    def select_primary_products(
        *,
        product_cards: List[ProductCard],
        best_distance: float | None,
        show_products_flag: bool,
        intent: str,
        default_threshold: float,
    ) -> Tuple[List[ProductCard], List[KnowledgeSource], bool]:
        top_products: List[ProductCard] = []
        sources: List[KnowledgeSource] = []
        fallback_used = False

        product_threshold = float(default_threshold)
        if show_products_flag:
            if intent == "browse_products":
                product_threshold = 0.85
            else:
                product_threshold = 0.65

        if product_cards and best_distance is not None and best_distance < product_threshold:
            top_products = product_cards[:10]
            product_text = "\n".join(
                [
                    (
                        f"TYPE: {p.attributes.get('jewelry_type', 'Jewelry')}, "
                        f"NAME: {p.name}, SKU: {p.sku}, PRICE: {p.price} {p.currency}"
                    )
                    for p in top_products[:3]
                ]
            )
            sources.append(
                KnowledgeSource(
                    source_id="product_listings",
                    title="Current Store Products",
                    content_snippet=f"The following products are available in the store:\n{product_text}",
                    relevance=1.0 - best_distance,
                )
            )
        elif show_products_flag and product_cards:
            top_products = product_cards[:10]
            product_text = "\n".join(
                [
                    f"- {p.attributes.get('jewelry_type', 'Jewelry')} {p.name} ({p.sku}): {p.price} {p.currency}"
                    for p in top_products
                ]
            )
            sources.append(
                KnowledgeSource(
                    source_id="products_fallback",
                    title="Related Products",
                    content_snippet=f"Here are some products you might be interested in:\n{product_text}",
                    relevance=0.3,
                )
            )
            fallback_used = True

        return top_products, sources, fallback_used
