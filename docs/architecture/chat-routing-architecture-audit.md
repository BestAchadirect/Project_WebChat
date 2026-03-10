# Chat Routing Architecture Audit

## Purpose
Document the current chat architecture, explain why it is still hybrid, and define the target architecture for a clean component-first cutover.

## Status
As of March 10, 2026, the live widget path runs through a component-primary runtime. The main remaining work is cleanup of legacy compatibility layers and contract simplification.

## Current Architecture

```text
Frontend (React Chat Widget)
  -> FastAPI /chat
     -> ChatService.process_chat
        -> Unified Chat Runtime
           -> ComponentPipeline
           -> shared routing policy
           -> product retrieval / recommendation / knowledge retrieval
           -> output planner
           -> component builders
           -> minimal compatibility fields
        -> persistence + QA log + optional conversation state
```

## What Is Already Modern

### Task Detection

Implemented through a mix of:

- deterministic heuristics
- structured parser logic
- LLM NLU fallback
- normalization rules

Supported task families:

- product browse/search
- product detail
- recommendations
- FAQ / knowledge
- store overview

### Service Separation

The backend already separates major service responsibilities:

- product retrieval
- product detail resolution
- recommendation ranking
- knowledge retrieval
- response formatting
- persistence and QA logging

### UI-Ready Response Layer

The system already supports:

- componentized responses
- legacy compatibility fields
- product carousel payloads
- follow-up question payloads

### Structured Context

Structured conversation state exists and persists into `conversation.state`, although it is not yet default-on and not fully component-path aware.

## Why The Architecture Is Still Transitional

### 1. Cleanup Is Not Complete

The live route is unified, but the codebase still contains compatibility and legacy support pieces that should be removed to reduce maintenance risk.

### 2. Compatibility Output Still Exists

Current gaps:

- top-level legacy fields still exist alongside `components`
- frontend still accepts legacy-shaped history and API payloads during migration

### 3. Vector Fallback Is Still A Broad Escape Hatch

When structured product search returns no match, product flows can still fall back to vector retrieval. This improves recall but can reduce precision if parser output is wrong or catalog data is sparse.

## Current Risks

### High Risk

- response-contract drift between `components` and legacy compatibility fields
- incorrect product fallback when structured filters fail

### Medium Risk

- optional conversation-state rollout delaying consistent multi-turn behavior
- environment-dependent behavior caused by feature flags

### Lower Risk

- response drift between component and legacy compatibility fields
- gradual accumulation of duplicated routing rules

## Recommended Target Architecture

```text
Frontend
  -> FastAPI /chat
     -> Unified Chat Orchestrator
        -> Context Manager
           -> load conversation.state
           -> load recent history
        -> Task Classifier
           -> browse_products
           -> search_specific
           -> detail_mode
           -> compare_products
           -> recommend_products
           -> knowledge_query
        -> Route Policy
           -> Product Search Service
           -> Product Detail Service
           -> Recommendation Service
           -> Knowledge Service
        -> Confidence / No-Match Layer
        -> Response Composer
           -> components as primary output
           -> optional legacy fields during migration
        -> Persistence + QA Metrics
```

## Target Design Principles

1. one routing/orchestration path
2. deterministic product parsing and retrieval before LLM phrasing
3. LLMs used primarily for NLU fallback and grounded knowledge phrasing
4. components as the primary response contract
5. legacy fields retained only during migration
6. stateful multi-turn product behavior as standard, not optional

## Migration Plan

### Phase 1: Documentation And Contract Alignment

- document the component-primary architecture clearly
- align intent schema and roadmap docs with code

### Phase 2: Cleanup And Contract Simplification

- remove dead legacy runtime code
- make the frontend render from `components` only
- keep only minimal compatibility fields at the API boundary

### Phase 3: Confidence Controls

- add stricter no-match behavior before vector fallback
- separate weak semantic suggestions from exact structured matches

### Phase 4: Component-First Cutover

- make components the default backend contract
- keep legacy compatibility only for migration support
- remove legacy-only routing once evaluation targets are met

## Recommended Exit Criteria For Legacy Compatibility

Legacy compatibility should remain until all of the following are true:

1. component path supports browse, detail, compare, recommend, and FAQ flows
2. conversation-state behavior is equivalent or better in the component path
3. regression and accuracy suites pass in component-only mode
4. frontend no longer depends on `reply_text` plus `product_carousel` as the primary rendering model

## Related Files

- `backend/app/services/chat/service.py`
- `backend/app/services/chat/unified_chat_runtime.py`
- `backend/app/services/chat/components/pipeline.py`
- `backend/app/services/chat/routing_policy.py`
- `backend/app/services/chat/result_policy.py`
- `backend/app/services/chat/conversation_state.py`
- `backend/app/services/chat/recommendation_service.py`
- `backend/app/services/catalog/product_search.py`
- `backend/app/services/knowledge/retrieval.py`
