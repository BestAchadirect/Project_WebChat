# ChatHarness Compatibility Audit

## Status
- Status: `completed`
- Phase: Phase 10.1, deprecation documentation and import audit
- Scope: chat runtime import compatibility only

## Current Runtime Ownership
- Primary orchestration now lives in `backend/app/services/chat/harness/`.
- `ChatHarness.run()` owns the visible step boundary: prepare context, understand, route, execute, finalize.
- `HarnessTrace` is the single trace object exposed through `debug["harness_trace"]`.
- Existing component workflows, decision engine, agentic orchestrator, grounding, and persistence remain in place.

## Compatibility Shims To Keep
- `app.services.chat.runtime.unified_chat_runtime.process_chat`
  - Compatibility role: historical chat runtime entrypoint.
  - Current target: `app.services.chat.harness.chat_harness.ChatHarness`.
  - Keep while `ChatService.process_chat()` and external scripts may still import the old runtime module.
- `app.services.chat.runtime.execution_coordinator`
  - Compatibility role: historical finalization/helper import path.
  - Current targets: `app.services.chat.harness.finalizer` and `app.services.chat.harness.support`.
  - Keep while external tests, QA tooling, or notebooks may still import finalization helpers.

## Migration Targets
- Prefer `app.services.chat.harness.chat_harness.ChatHarness` for orchestration.
- Prefer `app.services.chat.harness.dependencies.build_default_harness_dependencies` for dependency wiring and monkeypatch targets.
- Prefer `app.services.chat.harness.finalizer` for finalization helpers.
- Prefer `app.services.chat.harness.support` for `build_initial_debug_meta()` and `safe_conversation_id()`.
- Prefer `debug["harness_trace"]` for route, workflow, fallback, tool, grounding, and retrieval-count observability.

## Import Audit Result
- App code intentionally keeps `ChatService.process_chat()` delegating through `runtime.unified_chat_runtime`.
- Project tests only reference `runtime.execution_coordinator` in compatibility coverage.
- Old monkeypatch targets such as `runtime.unified_chat_runtime.build_understanding_result` and `runtime.unified_chat_runtime.infer_detail_query` are no longer used in app or test code.
- Existing evaluation monkeypatches target `app.services.chat.harness.dependencies`.

## Phase 11.2 Shim Hardening
- Both remaining runtime shims expose private `_COMPATIBILITY_METADATA` with import path, migration target, and removal condition.
- The metadata is intentionally not part of `__all__`; it exists for tests, audits, and maintainer visibility only.
- Compatibility tests now guard the shim metadata and verify the public shim surfaces remain narrow.

## Removal Readiness Checklist
- Keep both shims for at least one release cycle after this audit.
- Before removal, run a repo-wide search for `unified_chat_runtime` and `execution_coordinator`.
- Check CI scripts for direct imports or monkeypatch targets.
- Check deployment and health-check scripts for direct imports.
- Check evaluation scripts for direct imports or monkeypatch targets.
- Check notebooks, manual QA scripts, and one-off maintainer tooling for direct imports.
- Check docs and runbooks for instructions that name the old paths.
- Confirm hidden/extended test suites no longer import the old paths.
- Confirm the release notes name the migration targets before removal.
- Remove compatibility tests only after the shims are intentionally deleted.
- Do not remove component workflows, decision engine, agentic orchestrator, or runtime grounding modules as part of shim cleanup.
