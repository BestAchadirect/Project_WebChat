from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from app.services.catalog.projection_service import ProductProjectionSyncService


@dataclass
class _ProductStub:
    id: object
    sku: str
    attributes: dict = field(default_factory=dict)
    search_text: str = ""
    stock_status: str = "in_stock"
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _product(**kwargs) -> _ProductStub:
    payload = {
        "id": uuid4(),
        "sku": "SKU-1",
        "attributes": {},
        "search_text": "",
        "stock_status": "in_stock",
        "is_active": True,
    }
    payload.update(kwargs)
    return _ProductStub(**payload)


def test_projection_row_normalizes_structured_attributes() -> None:
    product = _product(
        sku=" Br-001 ",
        attributes={
            "material": "Surgical Steel",
            "jewelry_type": "barbells",
            "gauge": "16 gauge",
            "threading": "internally threaded",
            "color": "Black",
            "opal_color": "Blue",
        },
    )

    row = ProductProjectionSyncService._build_projection_row(product=product, eav_attrs={})

    assert row["sku_norm"] == "br-001"
    assert row["material_norm"] == "steel"
    assert row["jewelry_type_norm"] == "barbell"
    assert row["gauge_norm"] == "16g"
    assert row["threading_norm"] == "internal"
    assert row["color_norm"] == "black"
    assert row["opal_color_norm"] == "blue"
    assert row["is_active"] is True


def test_projection_row_uses_search_text_fallback_when_material_missing() -> None:
    product = _product(
        sku="X-OPAL-1",
        attributes={},
        search_text="implant grade titanium g23 circular barbell opal",
    )

    row = ProductProjectionSyncService._build_projection_row(product=product, eav_attrs={})

    assert row["material_norm"] == "titanium g23"
    assert row["jewelry_type_norm"] == "circular barbell"


def test_projection_row_prefers_eav_value_over_json_attributes() -> None:
    product = _product(
        sku="X-2",
        attributes={"material": "Steel"},
    )

    row = ProductProjectionSyncService._build_projection_row(
        product=product,
        eav_attrs={"material": "Titanium"},
    )

    assert row["material_norm"] == "titanium"
