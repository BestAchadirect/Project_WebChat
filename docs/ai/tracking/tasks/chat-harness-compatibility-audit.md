# ChatHarness Compatibility Cleanup

## Status
- Status: `hard_cleanup_completed`
- Phase: Phase 3 backend hard cleanup
- Scope: chat runtime import compatibility only

## Current Runtime Ownership
- Primary orchestration lives in `backend/app/services/chat/harness/`.
- `ChatService.process_chat()` now calls `ChatHarness(...).run(req)` directly.
- `HarnessTrace` remains the single trace object exposed through `debug["harness_trace"]`.
- Existing component workflows, decision engine, agentic orchestrator, grounding, and persistence remain in place.

## Removed Compatibility Shims
- Removed `backend/app/services/chat/runtime/unified_chat_runtime.py`.
- Removed `backend/app/services/chat/runtime/execution_coordinator.py`.
- Removed shim-only compatibility tests:
  - `backend/tests/unit/compatibility/test_chat_runtime_entrypoints.py`
  - `backend/tests/unit/compatibility/test_chat_execution_coordinator_shim.py`

## Supported Migration Targets
- Use `app.services.chat.service.ChatService.process_chat()` as the service-level chat entrypoint.
- Use `app.services.chat.harness.chat_harness.ChatHarness` for orchestration.
- Use `app.services.chat.harness.dependencies.build_default_harness_dependencies` for dependency wiring and monkeypatch targets.
- Use `app.services.chat.harness.finalizer` for finalization helpers.
- Use `app.services.chat.harness.support` for `build_initial_debug_meta()` and `safe_conversation_id()`.
- Use `debug["harness_trace"]` for route, workflow, fallback, tool, grounding, and retrieval-count observability.

## Latest Import Audit
- Date: 2026-05-20
- Trigger: project owner chose hard cleanup before production rollout.
- Search command:

```powershell
cd c:\Project_WebChat
rg -n "unified_chat_runtime|execution_coordinator" backend\app backend\tests backend\scripts docs -S
```

- Live app dependencies: none after cleanup.
- Backend test dependencies: none after cleanup.
- Backend script dependencies: none.
- Remaining references are documentation or historical sprint notes only.

## Risk Note
- This intentionally breaks external imports of the old runtime paths.
- This is acceptable for the current non-production phase.
- Before production rollout, validate any external QA tooling, notebooks, hidden tests, or maintainer scripts that might still import the old paths.

## Risk Mitigation
- `backend/scripts/check_legacy_imports.py` now flags new imports of:
  - `app.services.chat.runtime.unified_chat_runtime`
  - `app.services.chat.runtime.execution_coordinator`
  - `from app.services.chat.runtime import unified_chat_runtime`
  - `from app.services.chat.runtime import execution_coordinator`
- `backend/tests/unit/compatibility/test_service_adapters.py` verifies the removed chat runtime modules raise `ModuleNotFoundError`.
- `backend/tests/unit/compatibility/test_check_legacy_imports.py` verifies the import checker catches the removed chat runtime paths.
- `backend/tests/unit/chat/test_chat_service_harness_entrypoint.py` verifies `ChatService.process_chat()` delegates directly to `ChatHarness`.

## Validation Expectation
- Run unit chat and remaining compatibility suites after cleanup.
- Run targeted chat integration/API suites.
- Keep the staging/release tool-first rollout gate separate from this cleanup:
  - `100` tool-first selected rows per active channel, or
  - `48h` QA traffic if volume is lower.
