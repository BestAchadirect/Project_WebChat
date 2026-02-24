# Services Deprecation Runbook

## Purpose
Track service path migrations and hard-removal status for legacy wrappers.

## Current State (Hard Removal Applied)
- Hard removal executed in development on **February 23, 2026**.
- Legacy wrapper modules under `backend/app/services/*.py` were deleted.
- Canonical module paths are now required.
- `backend/scripts/check_legacy_imports.py` remains the CI guard to prevent reintroduction.

## Removed Legacy Module Registry
| Removed path | Replacement |
|---|---|
| `app.services.chat_service` | `app.services.chat.service` |
| `app.services.data_import_service` | `app.services.imports.service` |
| `app.services.agent_tools` | `app.services.chat.agentic.tool_registry` |
| `app.services.agent_orchestrator` | `app.services.chat.agentic.orchestrator` |
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

## Ongoing Verification
1. Search for banned legacy imports:
   - `rg -n "app\\.services\\.(chat_service|data_import_service|agent_tools|agent_orchestrator|llm_service|answer_polisher|response_renderer|eav_service|product_attribute_sync_service|knowledge_pipeline|task_service|ticket_service|rag_service|magento_service)" backend tests`
2. Ensure CI guard passes:
   - `python backend/scripts/check_legacy_imports.py`
3. Keep canonical import tests green (`backend/tests/test_service_adapters.py`).
