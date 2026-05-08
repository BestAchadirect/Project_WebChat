from __future__ import annotations

from typing import Set

from app.schemas.chat import ChatComponent, product_attributes_to_component_payload
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ProductCardsComponent(BaseComponent):
    component_type = ComponentType.PRODUCT_CARDS
    required_fields: Set[str] = {
        "product_id",
        "title",
        "description",
        "image_url",
        "price",
        "in_stock",
        "material",
        "gauge",
        "attributes",
    }

    async def build(self, context: ComponentContext) -> ChatComponent:
        cards = []
        for product in context.canonical_products:
            attrs = product_attributes_to_component_payload(dict(product.attributes or {}))
            master_code = str(attrs.get("master_code") or product.title or product.sku or "").strip()
            cards.append(
                {
                    "product_id": str(product.product_id),
                    "master_code": master_code,
                    "sku": product.sku,
                    "title": product.title,
                    "description": product.description,
                    "price": float(product.price),
                    "currency": product.currency,
                    "in_stock": bool(product.in_stock),
                    "stock_qty": product.stock_qty,
                    "image_url": product.image_url,
                    "material": product.material,
                    "gauge": product.gauge,
                    "attributes": attrs,
                    "product_url": product.product_url,
                }
            )
        return ChatComponent(type=self.component_type, data={"cards": cards})
