from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.services.chat.harness import finalizer, support
from app.services.chat.runtime import execution_coordinator


def test_execution_coordinator_public_surface_is_expected_reexports() -> None:
    assert execution_coordinator.__all__ == [
        "apply_component_debug",
        "build_initial_debug_meta",
        "build_runtime_error_response",
        "finalize_agentic_response",
        "finalize_component_response",
        "finalize_runtime_error",
        "safe_conversation_id",
    ]


def test_execution_coordinator_migration_metadata_is_private_to_shim() -> None:
    assert "_COMPATIBILITY_METADATA" not in execution_coordinator.__all__
    assert execution_coordinator._COMPATIBILITY_METADATA["import_path"] == (
        "app.services.chat.runtime.execution_coordinator"
    )
    assert execution_coordinator._COMPATIBILITY_METADATA["migration_targets"] == [
        "app.services.chat.harness.finalizer",
        "app.services.chat.harness.support",
    ]


def test_execution_coordinator_reexports_harness_helpers() -> None:
    assert execution_coordinator.apply_component_debug is finalizer.apply_component_debug
    assert execution_coordinator.build_runtime_error_response is finalizer.build_runtime_error_response
    assert execution_coordinator.finalize_agentic_response is finalizer.finalize_agentic_response
    assert execution_coordinator.finalize_component_response is finalizer.finalize_component_response
    assert execution_coordinator.finalize_runtime_error is finalizer.finalize_runtime_error
    assert execution_coordinator.build_initial_debug_meta is support.build_initial_debug_meta
    assert execution_coordinator.safe_conversation_id is support.safe_conversation_id
