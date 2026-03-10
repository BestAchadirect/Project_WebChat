# Implementation Roadmap

## Purpose
Provide an updated implementation plan for the chat-commerce stack based on the current repository state.

## Status
As of March 10, 2026, the core architecture is already in the post-cutover stage.

The live `/chat` path now runs through:

- `ChatService.process_chat`
- `unified_chat_runtime.process_chat`
- `ComponentPipeline`

This means the roadmap is no longer about introducing a unified component runtime. The roadmap is now about finishing the migration cleanly and hardening the component-primary system.

## What Is Already Implemented

Implemented foundation:

- component-primary runtime on the main chat path
- component responses for browse, detail, compare, recommendations, knowledge, and clarify flows
- deterministic route policy for compare, recommendation, store-overview, and knowledge detection
- structured-first retrieval with controlled semantic fallback
- recommendation expansion and reranking, including complementary-item profiles
- conversation-state load/write support in the component pipeline when `CHAT_CONVERSATION_STATE_ENABLED=true`
- short follow-up filter continuity from stored conversation state
- structured QA metrics, regression helpers, and accuracy-evaluation utilities

Still transitional:

- frontend and API responses still carry legacy compatibility fields beside `components`
- conversation state remains feature-flagged and does not yet resolve references such as `these` or `the first one` from `last_product_ids`
- product discovery still uses vector fallback for some low-structure queries
- operator-facing reporting and broader API / DB-backed test coverage are incomplete

## Current Priority

The highest-value work is now migration cleanup and reliability, in this order:

1. simplify the response contract around `components`
2. finish stateful multi-turn behavior
3. tighten retrieval precision and recommendation behavior
4. expand evaluation, reporting, and end-to-end confidence

## Phase 1: Contract Simplification

Status: `active / highest priority`

Goal:

- make `components` the primary response contract across backend and frontend

Work:

- reduce frontend dependence on `reply_text`, `product_carousel`, `carousel_msg`, and `follow_up_questions` as primary render inputs
- keep only minimal compatibility fields at the API boundary during migration
- remove residual legacy-only compatibility branches once widget and history rendering are component-safe
- align docs and tests to describe the runtime as component-primary, not hybrid-by-default

Exit criteria:

- widget rendering works from `components` without needing legacy fields for normal cases
- history replay and QA tooling tolerate component-first payloads
- compatibility fields are clearly marked as temporary or removed where safe

## Phase 2: Stateful Multi-Turn Hardening

Status: `partial / next`

Goal:

- make conversation state reliable enough to enable by default

Work:

- implement reference resolution from `last_product_ids` for follow-ups such as `these`, `that one`, and ordinal references
- use stored product context more consistently for image/detail/recommendation follow-ups
- keep history-based fallbacks only as backup behavior
- expand regression and integration coverage for multi-turn browse -> detail -> recommend flows

Exit criteria:

- `CHAT_CONVERSATION_STATE_ENABLED` can default to `true`
- component-path behavior is stable for short follow-ups and product references
- malformed or missing state still degrades safely to history-based handling

## Phase 3: Retrieval Precision And Recommendation Quality

Status: `active`

Goal:

- improve precision without losing helpful discovery behavior

Work:

- keep semantic fallback restricted to true discovery cases
- present semantic suggestions more explicitly when no exact structured match exists
- strengthen no-match behavior for weak vector results
- improve complementary recommendation profiles with more catalog-specific rules
- define clearer handling when recommendation expansion succeeds but ranking quality is weak

Exit criteria:

- exact matches, semantic suggestions, and no-match outcomes are clearly separated
- compare/detail flows do not drift into weak semantic fallback behavior
- recommendation quality is measurable through regression and accuracy suites

## Phase 4: Evaluation, Reporting, And Coverage

Status: `partial / ongoing`

Goal:

- make the component-primary runtime observable and operationally reviewable

Work:

- expose QA metrics and route aggregates in admin-facing reporting surfaces
- add production review loops for sampled conversations and failure buckets
- expand FastAPI route tests beyond `chat` and `health`
- add more DB-backed integration coverage for persistence, retrieval, and knowledge flows
- add top-level end-to-end tests under `tests/`

Exit criteria:

- operators can inspect intent, route, status, latency, and recommendation behavior without log spelunking
- regression and accuracy runs are part of routine release validation
- route, integration, and end-to-end coverage reduce reliance on manual spot checks

## Deferred Scope

Status: `deferred by design`

Not planned for the current phase:

- `add_to_cart`
- `view_cart`
- `start_checkout`
- transactional tool execution and order-management workflows

These should remain out of scope until discovery, detail, recommendation, and FAQ quality are stable under the component-primary contract.

## Delivery Sequence

1. Contract cleanup
2. Stateful follow-up hardening
3. Retrieval and recommendation precision work
4. Operator reporting and test expansion

## Related Files

- `docs/architecture/chat-routing-architecture-audit.md`
- `docs/architecture/conversation-state-design.md`
- `docs/architecture/commerce-intent-schema.md`
- `docs/architecture/test-architecture.md`
- `backend/app/services/chat/service.py`
- `backend/app/services/chat/unified_chat_runtime.py`
- `backend/app/services/chat/components/pipeline.py`
- `backend/app/services/chat/routing_policy.py`
- `backend/app/services/chat/result_policy.py`
- `backend/app/services/chat/recommendation_service.py`
- `backend/app/services/chat/qa_metrics.py`
- `frontend-admin/src/components/chat/ChatWidget.tsx`
