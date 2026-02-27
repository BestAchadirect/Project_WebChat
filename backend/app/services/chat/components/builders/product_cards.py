from __future__ import annotations

from typing import Set

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ProductCardsComponent(BaseComponent):
    component_type = ComponentType.PRODUCT_CARDS
    required_fields: Set[str] = {
        "product_id",
        "title",
        "image_url",
        "price",
        "in_stock",
        "material",
        "gauge",
    }

    async def build(self, context: ComponentContext) -> ChatComponent:
        cards = []
        for product in context.canonical_products:
            cards.append(
                {
                    "product_id": str(product.product_id),
                    "sku": product.sku,
                    "title": product.title,
                    "price": float(product.price),
                    "currency": product.currency,
                    "in_stock": bool(product.in_stock),
                    "stock_qty": product.stock_qty,
                    "image_url": product.image_url,
                    "material": product.material,
                    "gauge": product.gauge,
                    "product_url": product.product_url,
                }
            )
        return ChatComponent(type=self.component_type, data={"cards": cards})

