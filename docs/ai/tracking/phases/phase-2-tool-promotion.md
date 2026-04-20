# Phase 2: Tool Promotion

## Status
- Phase status: `completed`

## Goal
Promote the existing read-only tools into the main AI execution model and improve their quality before adding more orchestration complexity.

## Current Tool Seed
- `search_products`
- `get_product_details`
- `search_knowledge_base`
- `check_inventory_db`

## Primary Files
- `backend/app/services/chat/agentic/tool_registry.py`
- `backend/app/services/chat/agentic/orchestrator.py`
- `backend/app/services/catalog/product_search.py`
- `backend/app/services/knowledge/retrieval.py`

## Task Breakdown

### 2.1 Audit current tool contracts and argument gaps
Status: `completed`

Files:
- `backend/app/services/chat/agentic/tool_registry.py`
- `backend/app/services/catalog/product_search.py`
- `backend/app/services/knowledge/retrieval.py`
- `backend/tests/unit/chat/agentic/test_agent_tools.py`

Checklist:
- [x] Review current tool argument schemas for ambiguity
- [x] Identify exact-match assumptions that will make tool calling brittle
- [x] Identify output fields that are structured but still loosely normalized

Done when:
- A concrete before-state is recorded for the current tool surface

Audit findings:
- `search_products` uses a loose `filters: Dict[str, Any]` schema. It validates keys, but not value shape per key, which leaves too much room for inconsistent LLM arguments.
- `tool_definitions()` exposes `filters` as an untyped object with no per-field schema or examples. That is easy for the model to misuse.
- `get_product_details` and `check_inventory_db` are exact-SKU only. The underlying catalog service has richer lookup helpers, but the current tool contracts do not expose any near-SKU or direct product-reference fallback behavior.
- `search_products` currently performs embedding-first search through `vector_search()` only. The catalog service already has `lexical_search()` and `smart_search()`, but the tool path is not using them yet.
- `search_knowledge_base` is structurally safe, but its optional `category` field is free-form and its output fields are only lightly normalized.
- Current unit coverage is mostly schema validation coverage, not behavior-quality coverage.

### 2.2 Tighten product search tool arguments
Status: `completed`

Files:
- `backend/app/services/chat/agentic/tool_registry.py`
- `backend/app/services/chat/agentic/tool_handlers.py`
- `backend/tests/unit/chat/agentic/test_agent_tools.py`

Checklist:
- [x] Reduce ambiguity in the `filters` contract
- [x] Add validation for common filter value shapes
- [x] Keep the contract simple enough for tool calling

Done when:
- `search_products` has a clearer and more predictable argument contract for LLM use

Implementation notes:
- Replaced the loose `filters: Dict[str, Any]` contract in `tool_registry.py` with a typed `SearchProductFilters` model.
- Added validation for price range coherence (`min_price <= max_price`) and trimmed text filters.
- Updated the tool JSON schema so `filters` now exposes explicit supported fields with `additionalProperties: false`.
- Aligned runtime filtering in `tool_handlers.py` so the matcher now covers every text filter field exposed by the tool contract, including `body_part`, `feature`, `presentation_type`, and `theme`.
- Focused verification passed: `7 passed` on `backend/tests/unit/chat/agentic/test_agent_tools.py`.

### 2.3 Improve product detail and inventory lookup resilience
Status: `completed`

Files:
- `backend/app/services/chat/agentic/tool_registry.py`
- `backend/app/services/catalog/product_search.py`
- `backend/tests/unit/chat/agentic/test_agent_tools.py`

Checklist:
- [x] Add a safer path for near-SKU or direct product-reference lookup
- [x] Keep exact-SKU behavior stable
- [x] Avoid inventing product identities when lookup confidence is weak

Done when:
- Detail and inventory tools are less brittle than exact-SKU-only behavior

Implementation notes:
- Added `resolve_product_reference()` to `CatalogProductSearchService` to distinguish `resolved`, `ambiguous`, and `not_found` outcomes for direct and normalized product references.
- `get_product_details` now preserves the existing success path for unique matches, but returns a structured `ambiguous` payload with compact candidates when the reference is not specific enough.
- `check_inventory_db` now keeps exact-SKU behavior first, then falls back to resolved product references when possible, while preserving safe failure behavior for ambiguous references.
- Focused verification passed: `9 passed` on `backend/tests/unit/chat/agentic/test_agent_tools.py`.

### 2.4 Improve knowledge search tool behavior
Status: `completed`

Files:
- `backend/app/services/chat/agentic/tool_registry.py`
- `backend/app/services/knowledge/retrieval.py`
- `backend/tests/unit/chat/agentic/test_agent_tools.py`

Checklist:
- [x] Review category handling for FAQ and policy queries
- [x] Keep query/limit behavior predictable
- [x] Confirm result truncation and ordering are stable

Done when:
- `search_knowledge_base` behaves consistently for current-scope FAQ and policy requests

Implementation notes:
- Moved the main consistency fix into `KnowledgeRetrievalService.search()`:
  - category-filtered requests now broaden the underlying candidate search before filtering
  - results are sorted deterministically by relevance, title, and source id before truncation
  - category matching uses normalized case-insensitive comparison
- `tool_registry.search_knowledge_base()` now returns trimmed category values in the final payload and preserves the applied category filter explicitly.
- Focused verification passed: `11 passed` on `backend/tests/unit/knowledge/test_knowledge_retrieval.py` and `backend/tests/unit/chat/agentic/test_agent_tools.py`.

### 2.5 Normalize tool outputs for orchestration and rendering
Status: `completed`

Files:
- `backend/app/services/chat/agentic/tool_registry.py`
- `backend/app/services/chat/agentic/orchestrator.py`
- `backend/tests/unit/chat/agentic/test_agent_tools.py`

Checklist:
- [x] Confirm tool outputs stay structured and frontend-safe
- [x] Identify result fields that should be normalized before rendering
- [x] Keep output shapes stable across empty and success cases

Done when:
- Tool outputs are stable enough for orchestration, fallback, and rendering

Implementation notes:
- Added a consistent response envelope in `tool_registry.py` with stable top-level fields such as `tool`, `status`, and `source`.
- Normalized search and knowledge payloads now preserve explicit query/filter/category metadata in a stable shape.
- Ambiguous detail and inventory responses now carry full product-card candidate payloads instead of lossy mini-records, which lets the orchestrator surface them as renderable products.
- Updated `AgentOrchestrator` to count candidate lists in traces and collect ambiguous product candidates into the product carousel set.
- Focused verification passed: `13 passed` on `backend/tests/unit/chat/agentic/test_agent_tools.py` and `backend/tests/unit/chat/agentic/test_agent_orchestrator.py`.

### 2.6 Add focused tool-path tests
Status: `completed`

Files:
- `backend/tests/unit/chat/agentic/test_agent_tools.py`
- `backend/tests/unit/chat/agentic/test_agent_orchestrator.py`
- `backend/tests/unit/knowledge/test_knowledge_retrieval.py`

Checklist:
- [x] Add tests for improved tool argument handling
- [x] Add tests for resilient lookup behavior
- [x] Add tests for normalized output shapes

Done when:
- Tool promotion changes are protected by focused tests

Implementation notes:
- Added coverage for typed product-search filters, invalid price ranges, and normalized filter output shapes.
- Added coverage for resilient detail/inventory lookup behavior across `ambiguous`, `resolved`, and `not_found` paths.
- Added coverage for normalized success and empty envelopes on product and knowledge tool responses.
- Added orchestrator-side coverage to confirm ambiguous product candidates contribute to result counting and stay renderable.
- Focused verification passed: `16 passed` on:
  - `backend/tests/unit/chat/agentic/test_agent_tools.py`
  - `backend/tests/unit/chat/agentic/test_agent_orchestrator.py`
  - `backend/tests/unit/knowledge/test_knowledge_retrieval.py`

## Exit Criteria
- Existing tools cover the main current-scope read-only requests
- Tool inputs are validated and predictable
- Tool outputs are stable enough for orchestration and rendering
- Focused tool-path tests cover the promoted contracts and normalized result shapes

## Notes
- Prefer strengthening current tools over adding new workflow branches
