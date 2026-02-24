# Services Redesign (Backend)

## Goal
Redesign `backend/app/services` into domain packages while preserving external API behavior and standardizing on canonical service import paths.

## Status
- Phase 0 baseline docs: in progress
- Phase 1 quality tooling: in progress
- Phase 2 package structure and adapters: completed
- Phase 3 chat decomposition: partially completed
- Phase 4 import decomposition: partially completed
- Phase 5 agentic/retrieval consolidation: partially completed
- Phase 6 removals: completed early in development (February 23, 2026)

## New Domain Layout
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

## Old -> New Module Map
| Legacy module | New module |
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

## Compatibility Policy
- Legacy wrapper modules were removed.
- Canonical module paths are now required.
- CI guard blocks any new legacy-path imports (`backend/scripts/check_legacy_imports.py`).

## Implemented Decomposition Highlights
- Added shared catalog search service:
  - `app.services.catalog.product_search.CatalogProductSearchService`
  - Reused by chat and agentic tools to remove duplicated vector search logic.
- Added knowledge retrieval facade:
  - `app.services.knowledge.retrieval.KnowledgeRetrievalService`
  - Used by chat and agentic tool registry.
- Added chat collaborators:
  - `chat/intent_router.py`
  - `chat/retrieval_gate.py`
  - `chat/product_context.py`
  - `chat/knowledge_context.py`
  - `chat/response_consistency.py`
- Added import utility modules:
  - Product parser/search text/embedding/upload helpers
  - Knowledge parser/chunking/hash/upload helpers
  - Existing `DataImportService` private helper surfaces remain available as pass-through methods for script compatibility.

## Behavior Guardrails
- No HTTP route contract changes in `backend/app/api/routes/*`.
- Legacy import paths are intentionally blocked.
- Response consistency policy now centralizes the "product cards shown + not-found text" correction.

## Next Steps
1. Continue splitting `chat/service.py` and `imports/service.py` to smaller orchestrator-only facades.
2. Add characterization and adapter test coverage for canonical paths only.
3. Remove empty legacy directories in a separate cleanup pass when no longer needed.
