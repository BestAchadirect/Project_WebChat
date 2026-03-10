# Test Architecture

## Overview

The backend test suite protects the Python service layer, chat orchestration, and import logic for the FastAPI backend under `backend/`.

As of March 10, 2026, `backend/tests` passes `235` tests in about `2.38s` with the current local environment.

The suite is strongest in these areas:

- Chat orchestration, routing, fallback, and policy logic
- Component-pipeline behavior and conversation-state handling
- Catalog normalization and product projection rules
- Klevu sync mapping, run control, and worker behavior
- Compatibility coverage for temporary adapter paths

The suite is still weak in these areas:

- FastAPI route contract coverage beyond health and chat
- Real DB-backed integration coverage
- Cross-service end-to-end flows
- Knowledge import and retrieval coverage
- Tasks, tickets, training, analytics, banner, and product route HTTP tests

## Current Test Structure

Current layout:

```text
backend/tests/
  __init__.py
  conftest.py
  fixtures/
    __init__.py
    chat.py
    klevu.py
    persistence.py
  api/
    conftest.py
    test_chat_api.py
    test_health_api.py
  unit/
    ai/
      test_llm_service.py
    catalog/
      test_attributes_service_facets.py
      test_category_taxonomy_service.py
      test_product_projection_service.py
      test_products_filter_modes.py
    chat/
      agentic/
        test_agent_tools.py
      components/
        test_chat_component_builders.py
        test_chat_component_cache.py
        test_chat_component_field_resolver.py
        test_chat_component_registry.py
      test_chat_conversation_state.py
      test_chat_detail_helpers.py
      test_chat_follow_up_policy.py
      test_chat_result_policy.py
      test_chat_routing_policy.py
      test_chat_runtime_metrics.py
      test_chat_sku_precheck.py
      test_response_consistency.py
    compatibility/
      test_data_import_helper_compat.py
      test_service_adapters.py
  integration/
    catalog/
      test_product_embedding_model_filter.py
    chat/
      agentic/
        test_agent_orchestrator.py
      test_chat_commerce_intents.py
      test_chat_conversation_state_persistence.py
      test_chat_conversation_state_pipeline.py
      test_chat_detail_mode.py
      test_chat_performance_guards.py
      test_chat_product_presentation.py
      test_chat_qa_metrics.py
      test_chat_recommendation_service.py
      test_chat_service_component_primary.py
    imports/
      klevu/
        test_klevu_mapping.py
        test_klevu_run_control.py
        test_klevu_upsert.py
        test_klevu_worker.py
  regression/
    data/
      chat_regression_cases.json
      faq_accuracy_cases.json
      product_accuracy_cases.json
    test_chat_accuracy_eval.py
    test_chat_regression_dataset.py
```

Current structure summary:

- `43` Python test files are organized by layer under `unit/`, `integration/`, `api/`, and `regression/`
- `3` shared helper modules now live under `backend/tests/fixtures/`
- `2` real API test files now exist under `backend/tests/api/`
- `0` end-to-end tests exist yet in the top-level `tests/` folder
- The Klevu monolith was split into `mapping`, `run_control`, `upsert`, and `worker`
- The old conversation-state monolith was split into unit, pipeline, and persistence-focused files
- Component-primary chat coverage was merged into `test_chat_service_component_primary.py`
- SKU precheck coverage was merged into `test_chat_sku_precheck.py`

Architecture mapping:

| Backend area | Current tests | Test style |
| --- | --- | --- |
| Chat services and runtime | `unit/chat/test_chat_*`, `integration/chat/test_chat_service_component_primary.py`, `integration/chat/test_chat_detail_mode.py`, `integration/chat/test_chat_conversation_state_*` | Mostly unit tests plus service-level orchestration tests |
| Intent routing and fallback logic | `test_chat_routing_policy.py`, `test_chat_result_policy.py`, `test_chat_sku_precheck.py`, `test_response_consistency.py` | Unit tests |
| Product retrieval and presentation | `test_chat_product_presentation.py`, `test_chat_recommendation_service.py`, `test_product_embedding_model_filter.py`, `test_product_projection_service.py`, `test_products_filter_modes.py`, `test_category_taxonomy_service.py` | Mixed unit and service-level integration |
| API endpoints | `api/test_health_api.py`, `api/test_chat_api.py` | Real FastAPI route tests via `TestClient` |
| Runtime pipeline and conversation state | `unit/chat/test_chat_conversation_state.py`, `integration/chat/test_chat_conversation_state_pipeline.py`, `integration/chat/test_chat_conversation_state_persistence.py` | Unit and integration split by seam |
| Import pipeline | `integration/imports/klevu/test_klevu_*.py`, `unit/compatibility/test_data_import_helper_compat.py` | Service-level integration with fake DB objects |
| Agentic path | `unit/chat/agentic/test_agent_tools.py`, `integration/chat/agentic/test_agent_orchestrator.py` | Unit and orchestration tests |

## Problems Identified

- The suite is cleaner than before, but route coverage is still thin. Only `health` and `chat` now have true HTTP tests.
- There are still no end-to-end tests in top-level `tests/`, so no coverage proves a full user flow across import, persistence, retrieval, and API layers.
- Most integration tests are still service-level tests with fake DB sessions, monkeypatched dependencies, fake Redis, and fake knowledge services. They do not validate real DB queries or dependency wiring.
- `test_category_taxonomy_service.py` and `test_products_filter_modes.py` still import private helpers from `app.api.routes.products`, which couples unit tests to route internals.
- Several files are still broader than they should be:
  - `integration/chat/test_chat_product_presentation.py`
  - `integration/chat/test_chat_performance_guards.py`
  - `integration/chat/test_chat_detail_mode.py`
  - `unit/chat/test_chat_detail_helpers.py`
- Some naming is still ambiguous:
  - `test_chat_detail_helpers.py`
  - `test_chat_detail_mode.py`
  - `test_data_import_helper_compat.py`
- Compatibility coverage is isolated better now, but the compatibility file names still do not follow the final target naming from this document.
- The API layer has started, but there is still no HTTP coverage for:
  - `products`
  - `data_import`
  - `training`
  - `analytics`
  - `tasks`
  - `tickets`
  - `banner`
  - `chat_setting`
- There is still no DB-backed integration coverage for chat persistence, product search, or knowledge retrieval.

## Test Categories

Current classification of the `backend/tests` suite:

| Type | File count | Notes |
| --- | --- | --- |
| Unit tests | `26` | Includes regression-style dataset evaluators |
| Integration tests | `15` | Mostly service-level orchestration tests |
| API tests | `2` | `health` and `chat` only |
| End-to-end tests | `0` | Should live under top-level `tests/` |

### Unit tests

These files validate isolated modules, helpers, policies, compatibility contracts, or dataset evaluators:

- `unit/ai/test_llm_service.py`
- `unit/catalog/test_attributes_service_facets.py`
- `unit/catalog/test_category_taxonomy_service.py`
- `unit/catalog/test_product_projection_service.py`
- `unit/catalog/test_products_filter_modes.py`
- `unit/chat/agentic/test_agent_tools.py`
- `unit/chat/components/test_chat_component_builders.py`
- `unit/chat/components/test_chat_component_cache.py`
- `unit/chat/components/test_chat_component_field_resolver.py`
- `unit/chat/components/test_chat_component_registry.py`
- `unit/chat/test_chat_conversation_state.py`
- `unit/chat/test_chat_detail_helpers.py`
- `unit/chat/test_chat_follow_up_policy.py`
- `unit/chat/test_chat_result_policy.py`
- `unit/chat/test_chat_routing_policy.py`
- `unit/chat/test_chat_runtime_metrics.py`
- `unit/chat/test_chat_sku_precheck.py`
- `unit/chat/test_response_consistency.py`
- `unit/compatibility/test_data_import_helper_compat.py`
- `unit/compatibility/test_service_adapters.py`
- `regression/test_chat_accuracy_eval.py`
- `regression/test_chat_regression_dataset.py`

### Integration tests

These files combine multiple services, orchestration seams, or import flows:

- `integration/catalog/test_product_embedding_model_filter.py`
- `integration/chat/agentic/test_agent_orchestrator.py`
- `integration/chat/test_chat_commerce_intents.py`
- `integration/chat/test_chat_conversation_state_persistence.py`
- `integration/chat/test_chat_conversation_state_pipeline.py`
- `integration/chat/test_chat_detail_mode.py`
- `integration/chat/test_chat_performance_guards.py`
- `integration/chat/test_chat_product_presentation.py`
- `integration/chat/test_chat_qa_metrics.py`
- `integration/chat/test_chat_recommendation_service.py`
- `integration/chat/test_chat_service_component_primary.py`
- `integration/imports/klevu/test_klevu_mapping.py`
- `integration/imports/klevu/test_klevu_run_control.py`
- `integration/imports/klevu/test_klevu_upsert.py`
- `integration/imports/klevu/test_klevu_worker.py`

### API tests

These files exercise FastAPI routers through `TestClient`:

- `api/test_chat_api.py`
- `api/test_health_api.py`

### End-to-end tests

There are no end-to-end tests yet.

Per `AGENTS.md`, true cross-service flows should live in top-level `tests/`, not `backend/tests/`.

## Recommended Test Architecture

Keep backend-owned unit, service, and API tests under `backend/tests`, and keep true cross-service and end-to-end flows under top-level `tests/`.

Recommended structure:

```text
backend/tests/
  conftest.py
  fixtures/
    chat.py
    catalog.py
    imports.py
    persistence.py

  unit/
    ai/
      test_llm_service.py
    catalog/
      test_attributes_service.py
      test_category_taxonomy_service.py
      test_product_projection_service.py
      test_product_search_sql_filters.py
    chat/
      test_conversation_state.py
      test_detail_query_parser.py
      test_detail_response_builder.py
      test_product_detail_resolver.py
      test_follow_up_policy.py
      test_result_policy.py
      test_routing_policy.py
      test_runtime_metrics.py
      test_response_consistency.py
      test_sku_precheck.py
      components/
        test_builders.py
        test_cache.py
        test_field_resolver.py
        test_registry.py
    imports/
      klevu/
        test_mapping.py
        test_run_control.py
        test_upsert.py
        test_worker.py
    compatibility/
      test_service_adapters.py
      test_data_import_private_helpers.py

  integration/
    chat/
      test_chat_service_component_primary.py
      test_component_pipeline_conversation_state.py
      test_component_pipeline_detail.py
      test_component_pipeline_product_presentation.py
      test_component_pipeline_recommendations.py
    catalog/
      test_catalog_product_search.py
    imports/
      klevu/
        test_full_sync_service.py
    persistence/
      test_chat_persistence.py

  api/
    test_chat_api.py
    test_products_api.py
    test_data_import_api.py
    test_training_api.py
    test_analytics_api.py
    test_tasks_api.py
    test_tickets_api.py
    test_banner_api.py
    test_chat_settings_api.py
    test_health_api.py

  regression/
    data/
      chat_regression_cases.json
      faq_accuracy_cases.json
      product_accuracy_cases.json
    test_chat_accuracy.py
    test_chat_regressions.py

tests/
  e2e/
    test_chat_user_journeys.py
    test_product_import_to_chat_visibility.py
    test_knowledge_import_to_chat_answer.py
```

## File Naming Guidelines

- Keep one test file focused on one production module or one integration seam.
- Put the test layer in the folder, not in the file name.
- Mirror the production module name where possible.
- Avoid ambiguous names such as `helpers`, `mode`, or `runtime` unless the production module uses the same name.
- Keep temporary adapter coverage under `unit/compatibility/`.
- Keep dataset-driven contract checks under `regression/`.

Specific naming work still recommended in this project:

- Rename `unit/chat/test_chat_detail_helpers.py` to:
  - `test_detail_query_parser.py`
  - `test_detail_response_builder.py`
  - `test_product_detail_resolver.py`
- Rename `unit/compatibility/test_data_import_helper_compat.py` to `test_data_import_private_helpers.py`
- Keep `integration/chat/test_chat_service_component_primary.py` as the single home for component-primary `ChatService` routing behavior
- Keep the Klevu split by responsibility instead of restoring a single `test_klevu_sync_service.py`

## Missing Test Coverage

Important gaps by backend component:

- FastAPI routes:
  - `app.api.routes.products`
  - `app.api.routes.data_import`
  - `app.api.routes.training`
  - `app.api.routes.analytics`
  - `app.api.routes.tasks`
  - `app.api.routes.tickets`
  - `app.api.routes.banner`
  - `app.api.routes.chat_setting`
- Chat runtime composition:
  - `app.services.chat.unified_chat_runtime`
  - `app.services.chat.product_context`
  - `app.services.chat.knowledge_context`
  - `app.services.chat.runtime_state`
- Chat persistence beyond finalize:
  - `save_message`
  - `submit_feedback`
  - `get_history`
  - active-conversation lookup
- Knowledge services:
  - `app.services.knowledge.retrieval`
  - `app.services.knowledge.pipeline`
- Import helpers outside the current Klevu seam:
  - product parser and upload history
  - knowledge chunking, embeddings, parser, and upload history
- Shared backend services:
  - `currency_service`
  - `embedding`
  - `semantic_cache_service`
- Cross-service behavior:
  - product import to API visibility
  - product import to chat visibility
  - knowledge import to retrieval-backed chat answers
  - chat request to persistence to history retrieval

## Cleanup Plan

Cleanup progress as of March 10, 2026:

- Completed: remove `backend/tests/__pycache__/` from the suite tree
- Completed: restructure the suite into `unit/`, `integration/`, `api/`, and `regression/`
- Completed: extract shared helpers into `fixtures/chat.py`, `fixtures/persistence.py`, and `fixtures/klevu.py`
- Completed: split `test_klevu_sync_service.py` into `mapping`, `run_control`, `upsert`, and `worker`
- Completed: split `test_chat_conversation_state.py` into unit, pipeline, and persistence seams
- Completed: merge overlapping component-primary tests into `test_chat_service_component_primary.py`
- Completed: merge overlapping SKU-precheck tests into `test_chat_sku_precheck.py`
- Started: add an API layer with `test_health_api.py` and `test_chat_api.py`
- Completed: isolate compatibility coverage under `unit/compatibility/`
- Completed: move regression datasets under `regression/data/`
- Started: apply project markers such as `agentic`, `imports`, and `adapter`

Next cleanup steps:

1. Rename the remaining ambiguous files:
   - `test_chat_detail_helpers.py`
   - `test_chat_detail_mode.py`
   - `test_data_import_helper_compat.py`

2. Add the next API test files:
   - `test_products_api.py`
   - `test_data_import_api.py`
   - `test_training_api.py`
   - `test_tasks_api.py`
   - `test_tickets_api.py`

3. Add DB-backed integration tests for:
   - chat persistence
   - product search
   - knowledge retrieval

4. Break up the remaining broad chat integration files:
   - `test_chat_product_presentation.py`
   - `test_chat_performance_guards.py`
   - `test_chat_detail_mode.py`

5. Add top-level end-to-end tests under `tests/e2e/`

## Example Final Test Folder

```text
backend/tests/
  unit/
    chat/
      test_conversation_state.py
      test_detail_query_parser.py
      test_detail_response_builder.py
      test_product_detail_resolver.py
      test_result_policy.py
      test_routing_policy.py
      test_sku_precheck.py
    chat/components/
      test_builders.py
      test_cache.py
      test_field_resolver.py
      test_registry.py
    catalog/
      test_attributes_service.py
      test_category_taxonomy_service.py
      test_product_projection_service.py
      test_product_search_sql_filters.py
    imports/klevu/
      test_mapping.py
      test_run_control.py
      test_upsert.py
      test_worker.py
    compatibility/
      test_service_adapters.py
      test_data_import_private_helpers.py

  integration/
    chat/
      test_chat_service_component_primary.py
      test_component_pipeline_conversation_state.py
      test_component_pipeline_detail.py
      test_component_pipeline_product_presentation.py
      test_component_pipeline_recommendations.py
    persistence/
      test_chat_persistence.py

  api/
    test_chat_api.py
    test_products_api.py
    test_data_import_api.py
    test_training_api.py
    test_tasks_api.py
    test_tickets_api.py
    test_analytics_api.py
    test_banner_api.py
    test_chat_settings_api.py
    test_health_api.py

  regression/
    data/
      chat_regression_cases.json
      faq_accuracy_cases.json
      product_accuracy_cases.json
    test_chat_accuracy.py
    test_chat_regressions.py

tests/
  e2e/
    test_chat_user_journeys.py
    test_product_import_to_chat_visibility.py
    test_knowledge_import_to_chat_answer.py
```
