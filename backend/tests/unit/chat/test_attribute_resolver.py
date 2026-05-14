from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.chat.parsing import attribute_resolver
from app.services.chat.parsing.attribute_resolver import resolve_catalog_attributes
from app.services.chat.parsing.query_understanding import (
    CatalogQueryUnderstanding,
    QueryConfidence,
    QueryHardConstraints,
)


def _understanding(
    *,
    hard_constraints: QueryHardConstraints,
    product_type_terms: list[str] | None = None,
    soft_hints: list[str] | None = None,
    strictness: dict[str, str] | None = None,
) -> CatalogQueryUnderstanding:
    return CatalogQueryUnderstanding(
        intent="catalog_search",
        is_searchable_enough=True,
        clarification_needed=False,
        product_type_terms=product_type_terms or [],
        hard_constraints=hard_constraints,
        soft_hints=soft_hints or [],
        semantic_query="test query",
        strictness=strictness or {},
        confidence=QueryConfidence(intent=0.9, constraints=0.9, searchable=0.9),
    )


@pytest.mark.asyncio
async def test_attribute_resolver_maps_critical_aliases_to_catalog_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_load_catalog_values(db: Any, attributes):
        return {
            "material": [
                {"value": "316L Surgical Steel", "value_norm": "316l surgical steel", "product_count": "10"},
                {"value": "Titanium", "value_norm": "titanium", "product_count": "4"},
            ],
            "jewelry_type": [
                {"value": "Navel Ring", "value_norm": "navel ring", "product_count": "8"},
            ],
        }

    monkeypatch.setattr(attribute_resolver, "_load_catalog_values", fake_load_catalog_values)

    result = await resolve_catalog_attributes(
        db=SimpleNamespace(execute=object()),
        understanding=_understanding(
            hard_constraints=QueryHardConstraints(material=["surgical steel"]),
            product_type_terms=["belly ring"],
        ),
    )

    assert result.resolved_hard_constraints == {
        "material": "316l surgical steel",
        "jewelry_type": "navel ring",
    }
    assert result.unresolved_constraints == []


@pytest.mark.asyncio
async def test_attribute_resolver_keeps_unresolved_hard_constraints_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_load_catalog_values(db: Any, attributes):
        return {"material": [{"value": "Titanium", "value_norm": "titanium", "product_count": "4"}]}

    monkeypatch.setattr(attribute_resolver, "_load_catalog_values", fake_load_catalog_values)

    result = await resolve_catalog_attributes(
        db=SimpleNamespace(execute=object()),
        understanding=_understanding(
            hard_constraints=QueryHardConstraints(material=["unobtainium"]),
            strictness={"material": "required"},
        ),
    )

    assert result.resolved_hard_constraints == {}
    assert result.unresolved_constraints == [
        {
            "attribute": "material",
            "value": "unobtainium",
            "reason": "unresolved",
            "strictness": "required",
        }
    ]


@pytest.mark.asyncio
async def test_attribute_resolver_translates_price_constraints() -> None:
    result = await resolve_catalog_attributes(
        db=object(),
        understanding=_understanding(
            hard_constraints=QueryHardConstraints(price="under $50"),
        ),
    )

    assert result.resolved_hard_constraints == {"max_price": "50"}
    assert result.unresolved_constraints == []
