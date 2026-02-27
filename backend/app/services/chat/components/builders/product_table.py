from __future__ import annotations

from typing import Set

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ProductTableComponent(BaseComponent):
    component_type = ComponentType.PRODUCT_TABLE
    required_fields: Set[str] = {
        "sku",
        "title",
        "price",
        "stock_qty",
        "material",
        "gauge",
    }

    async def build(self, context: ComponentContext) -> ChatComponent:
        rows = []
        for product in context.canonical_products:
            rows.append(
                {
                    "sku": product.sku,
                    "title": product.title,
                    "price": float(product.price),
                    "currency": product.currency,
                    "stock_qty": product.stock_qty,
                    "in_stock": bool(product.in_stock),
                    "material": product.material,
                    "gauge": product.gauge,
                }
            )
        return ChatComponent(type=self.component_type, data={"columns": ["sku", "title", "price", "stock_qty", "material", "gauge"], "rows": rows})

