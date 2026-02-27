from __future__ import annotations

from typing import Set

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class RecommendationsComponent(BaseComponent):
    component_type = ComponentType.RECOMMENDATIONS
    required_fields: Set[str] = {"product_id", "sku", "title", "price"}

    async def build(self, context: ComponentContext) -> ChatComponent:
        items = []
        for product in context.recommendations[:5]:
            items.append(
                {
                    "product_id": str(product.product_id),
                    "sku": product.sku,
                    "title": product.title,
                    "price": float(product.price),
                    "currency": product.currency,
                    "in_stock": bool(product.in_stock),
                }
            )
        return ChatComponent(type=self.component_type, data={"items": items})

