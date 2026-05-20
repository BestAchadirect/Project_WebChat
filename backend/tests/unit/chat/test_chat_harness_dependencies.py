from __future__ import annotations

from dataclasses import fields

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.services.chat.harness.context import ChatHarnessDependencies
from app.services.chat.harness.dependencies import build_default_harness_dependencies


def test_default_harness_dependencies_exclude_finalizer_callbacks() -> None:
    field_names = {field.name for field in fields(ChatHarnessDependencies)}

    assert "finalize_agentic_response" not in field_names
    assert "finalize_component_response" not in field_names
    assert "finalize_runtime_error" not in field_names

    dependencies = build_default_harness_dependencies()
    assert not hasattr(dependencies, "finalize_agentic_response")
    assert not hasattr(dependencies, "finalize_component_response")
    assert not hasattr(dependencies, "finalize_runtime_error")


def test_default_harness_dependencies_keep_execution_callbacks() -> None:
    dependencies = build_default_harness_dependencies()

    assert callable(dependencies.apply_agentic_fallback_debug)
    assert callable(dependencies.apply_agentic_success_debug)
    assert callable(dependencies.coerce_agentic_result)
    assert callable(dependencies.agentic_failure_reason)
