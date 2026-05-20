from __future__ import annotations

"""Compatibility exports for older chat runtime imports.

The harness package now owns these helpers. Keep this module lightweight so
external callers and older tests can migrate without behavior changes.

Do not add new finalization or runtime logic here. Add behavior under
``app.services.chat.harness.finalizer`` or ``app.services.chat.harness.support``
and re-export only when a compatibility window requires it.
"""

from app.services.chat.harness.finalizer import (
    apply_component_debug,
    build_runtime_error_response,
    finalize_agentic_response,
    finalize_component_response,
    finalize_runtime_error,
)
from app.services.chat.harness.support import build_initial_debug_meta, safe_conversation_id

__all__ = [
    "apply_component_debug",
    "build_initial_debug_meta",
    "build_runtime_error_response",
    "finalize_agentic_response",
    "finalize_component_response",
    "finalize_runtime_error",
    "safe_conversation_id",
]

_COMPATIBILITY_METADATA = {
    "import_path": "app.services.chat.runtime.execution_coordinator",
    "role": "historical finalization and runtime helper import path",
    "migration_targets": [
        "app.services.chat.harness.finalizer",
        "app.services.chat.harness.support",
    ],
    "removal_condition": "after one release cycle and external import audit completion",
}
