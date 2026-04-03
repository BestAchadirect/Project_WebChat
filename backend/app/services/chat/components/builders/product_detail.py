from __future__ import annotations

from typing import Set

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ProductDetailComponent(BaseComponent):
    component_type = ComponentType.PRODUCT_DETAIL
    required_fields: Set[str] = {
        "product_id",
        "sku",
        "title",
        "description",
        "price",
        "in_stock",
        "material",
        "gauge",
        "image_url",
        "full_spec_fields",
    }

    async def build(self, context: ComponentContext) -> ChatComponent:
        product = context.canonical_products[0] if context.canonical_products else None
        if product is None:
            return ChatComponent(type=self.component_type, data={"product": None})
        attrs = dict(product.attributes or {})
        master_code = str(attrs.get("master_code") or product.title or product.sku or "").strip()
        return ChatComponent(
            type=self.component_type,
            data={
                "product": {
                    "product_id": str(product.product_id),
                    "master_code": master_code,
                    "sku": product.sku,
                    "title": product.title,
                    "description": product.description,
                    "price": float(product.price),
                    "currency": product.currency,
                    "in_stock": bool(product.in_stock),
                    "stock_qty": product.stock_qty,
                    "material": product.material,
                    "gauge": product.gauge,
                    "image_url": product.image_url,
                    "product_url": product.product_url,
                    "attributes": attrs,
                }
            },
        )
