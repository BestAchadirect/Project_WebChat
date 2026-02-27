from __future__ import annotations

from typing import Set

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ProductBulletsComponent(BaseComponent):
    component_type = ComponentType.PRODUCT_BULLETS
    required_fields: Set[str] = {"sku", "title", "price", "material", "gauge"}

    async def build(self, context: ComponentContext) -> ChatComponent:
        bullets = []
        for product in context.canonical_products:
            bullets.append(
                f"{product.sku}: {product.title} ({float(product.price):.2f} {product.currency})"
                f" material={product.material or 'n/a'}, gauge={product.gauge or 'n/a'}"
            )
        return ChatComponent(type=self.component_type, data={"items": bullets})

