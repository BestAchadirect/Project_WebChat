# Services Redesign

## Purpose
Track the ongoing refactor of `backend/app/services` into stable domain packages and document migration guardrails.

## Context
The codebase moved from flat service modules to domain-based packages while preserving API route behavior and enforcing canonical import paths.

## Content

### Objective

- Use domain packages as the only supported import surface.
- Keep route contracts stable while internal service composition evolves.
- Prevent regressions by blocking legacy import paths in CI.

### Status Snapshot (March 6, 2026)

- Phase 0 baseline docs: in progress.
- Phase 1 quality tooling: in progress.
- Phase 2 package structure and adapters: completed.
- Phase 3 chat decomposition: partially completed.
- Phase 4 import decomposition: partially completed.
- Phase 5 agentic/retrieval consolidation: partially completed.
- Phase 6 legacy wrapper removals: completed on February 23, 2026.

### Canonical Domain Layout

```text
backend/app/services/
  ai/
  chat/
    agentic/
  catalog/
  knowledge/
  imports/
    products/
    knowledge/
  tasks/
  tickets/
  legacy/
```

### Legacy to Canonical Module Map

| Legacy module | Canonical module |
|---|---|
| `app.services.chat_service` | `app.services.chat.service` |
| `app.services.agent_tools` | `app.services.chat.agentic.tool_registry` |
| `app.services.agent_orchestrator` | `app.services.chat.agentic.orchestrator` |
| `app.services.data_import_service` | `app.services.imports.service` |
| `app.services.llm_service` | `app.services.ai.llm_service` |
| `app.services.answer_polisher` | `app.services.ai.answer_polisher` |
| `app.services.response_renderer` | `app.services.ai.response_renderer` |
| `app.services.eav_service` | `app.services.catalog.attributes_service` |
| `app.services.product_attribute_sync_service` | `app.services.catalog.attribute_sync_service` |
| `app.services.knowledge_pipeline` | `app.services.knowledge.pipeline` |
| `app.services.task_service` | `app.services.tasks.service` |
| `app.services.ticket_service` | `app.services.tickets.service` |
| `app.services.rag_service` | `app.services.legacy.rag_service_deprecated` |
| `app.services.magento_service` | `app.services.legacy.magento_service_deprecated` |

### Current Guardrails

- Legacy wrapper files were removed; canonical imports are required.
- CI guard script blocks reintroduction of removed module paths.
- API route contracts under `backend/app/api/routes` remain the compatibility boundary.

### Remaining Work

1. Continue decomposing `chat/service.py` and `imports/service.py` into orchestrator-first modules.
2. Add adapter and behavior characterization tests for canonical imports.
3. Complete cleanup of residual legacy scaffolding after final call-site verification.

## Related Files

- `backend/scripts/check_legacy_imports.py`
- `backend/app/services/chat/service.py`
- `backend/app/services/imports/service.py`
- `docs/runbooks/services-deprecation.md`
