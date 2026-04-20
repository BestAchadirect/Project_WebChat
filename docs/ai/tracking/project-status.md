# AI Project Status

## Current Focus
- Scope: Magento-only, single-store, read-only AI assistant
- Data source now: Klevu-backed local data
- Data source later: Magento API sync into local DB
- Priority: AI implementation logic first

## Phase Board
| Phase | Title | Status | Owner | Notes |
|---|---|---|---|---|
| 1 | Primary orchestration | `completed` | AI/runtime | Tool path is now primary for supported read-only requests, with explicit fallback coverage |
| 2 | Tool promotion | `completed` | AI/runtime | Read-only tools now have tighter contracts, resilient lookup behavior, normalized outputs, and focused coverage |
| 3 | Thin routing | `pending` | AI/runtime | Reduce routing to guardrails and fast-path hints |
| 4 | Orchestration contracts | `pending` | AI/runtime | Standardize orchestrator input/output and fallback contract |
| 5 | AI tests | `pending` | AI/tests | Add focused tests for tool path behavior |

## Immediate Next Task
- Start Phase 3: audit routing logic that should remain as deterministic guardrails versus logic that should be downgraded to hints

## Phase 2 Summary
- [x] 2.1 Audit current tool contracts and argument gaps
- [x] 2.2 Tighten product search tool arguments
- [x] 2.3 Improve product detail and inventory lookup resilience
- [x] 2.4 Improve knowledge search tool behavior
- [x] 2.5 Normalize tool outputs for orchestration and rendering
- [x] 2.6 Add focused tool-path tests

## Latest Findings
- Agentic fallback behavior in `unified_chat_runtime` is already usable; the main blocker is preselection, not fallback mechanics.
- The suitability gate has been widened for supported read-only catalog and knowledge requests.
- `decision_engine.build_decision_state()` already prefers agentic once the widened suitability gate passes; that behavior is now covered by focused tests.
- Runtime fallback behavior is now covered for success, `None`, `no_tool_usage`, and exception paths.
- Debug fidelity is now covered: fallback transitions preserve both a human-readable `fallback_reason` and a machine-readable `failure_reason`.
- The remaining component-first list is now explicit and short: off-topic/smalltalk, fallback/clarify, understanding-failure cases, and feature/channel guardrail cases.
- The `search_products` contract is now typed and schema-bounded.
- Detail and inventory tools are no longer exact-SKU-only; they now distinguish resolved vs ambiguous reference handling.
- Knowledge search now broadens category-filtered retrieval and returns stable, trimmed output.
- Tool outputs now share a stable envelope and ambiguous product candidates are renderable by the orchestrator.
- Phase 2 is complete: the read-only tool layer now has tighter contracts, resilient lookup behavior, normalized envelopes, and focused coverage.

## Not In Scope For This Tracker
- Multi-tenant support
- Non-Magento platform support
- Order/account/cart tools
- Ticket handoff
- Generic platform abstractions
