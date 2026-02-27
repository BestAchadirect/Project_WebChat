from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID


@dataclass
class CanonicalProduct:
    product_id: UUID
    sku: str
    title: str
    price: Decimal
    currency: str
    in_stock: bool
    stock_qty: Optional[int]
    material: Optional[str]
    gauge: Optional[str]
    image_url: Optional[str]
    attributes: Dict[str, Any] = field(default_factory=dict)
    product_url: Optional[str] = None

    def to_cache_payload(self) -> Dict[str, Any]:
        return {
            "product_id": str(self.product_id),
            "sku": self.sku,
            "title": self.title,
            "price": str(self.price),
            "currency": self.currency,
            "in_stock": bool(self.in_stock),
            "stock_qty": self.stock_qty,
            "material": self.material,
            "gauge": self.gauge,
            "image_url": self.image_url,
            "attributes": dict(self.attributes or {}),
            "product_url": self.product_url,
        }

    @classmethod
    def from_cache_payload(cls, payload: Dict[str, Any]) -> "CanonicalProduct":
        return cls(
            product_id=UUID(str(payload.get("product_id"))),
            sku=str(payload.get("sku") or ""),
            title=str(payload.get("title") or ""),
            price=Decimal(str(payload.get("price") or "0")),
            currency=str(payload.get("currency") or "USD"),
            in_stock=bool(payload.get("in_stock", False)),
            stock_qty=payload.get("stock_qty"),
            material=(str(payload.get("material")) if payload.get("material") is not None else None),
            gauge=(str(payload.get("gauge")) if payload.get("gauge") is not None else None),
            image_url=(str(payload.get("image_url")) if payload.get("image_url") is not None else None),
            attributes=dict(payload.get("attributes") or {}),
            product_url=(str(payload.get("product_url")) if payload.get("product_url") is not None else None),
        )

