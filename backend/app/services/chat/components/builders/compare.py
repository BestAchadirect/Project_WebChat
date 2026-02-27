from __future__ import annotations

from typing import Set

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class CompareComponent(BaseComponent):
    component_type = ComponentType.COMPARE
    required_fields: Set[str] = {"sku", "title", "price", "in_stock", "full_spec_fields"}

    async def build(self, context: ComponentContext) -> ChatComponent:
        rows = []
        for product in context.canonical_products[:5]:
            rows.append(
                {
                    "sku": product.sku,
                    "title": product.title,
                    "price": float(product.price),
                    "currency": product.currency,
                    "in_stock": bool(product.in_stock),
                    "stock_qty": product.stock_qty,
                    "attributes": dict(product.attributes or {}),
                }
            )
        return ChatComponent(type=self.component_type, data={"items": rows})

