from __future__ import annotations

import pytest

from app.services.chat.components.registry import ComponentRegistry
from app.services.chat.components.types import ComponentType


def test_registry_maps_all_component_types() -> None:
    for component_type in ComponentType:
        builder = ComponentRegistry.builder_for(component_type)
        assert builder.component_type == component_type


def test_registry_missing_builder_raises_controlled_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ComponentRegistry, "_registry", {})
    with pytest.raises(KeyError):
        ComponentRegistry.builder_for(ComponentType.PRODUCT_CARDS)
