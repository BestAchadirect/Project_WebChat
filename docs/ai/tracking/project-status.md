# AI Project Status

## Current Focus
- Scope: Magento-only, single-store, read-only AI assistant
- Data source now: Klevu-backed local data
- Data source later: Magento API sync into local DB
- Priority: AI implementation logic first
- Active tracker: sprint-first (`docs/ai/tracking/sprints/`)

## Phase Board
| Phase | Title | Status | Owner | Notes |
|---|---|---|---|---|
| 1 | Foundation and agentic adoption | `completed` | AI/runtime | The initial AI-first foundation is in place through completed sprint history |
| 2 | Runtime consolidation | `completed` | AI/runtime | Runtime ownership, fallback narrowing, and orchestrator/tool boundary consolidation are complete |
| 3 | Hardening and expansion | `in_progress` | AI/runtime + AI/tests | Current tracked focus after runtime consolidation |

## Active Sprint
- None

## Last Completed Sprint
- [Sprint: Grounded Response Quality](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-grounded-response-quality/README.md>)
- [Sprint: Evaluation Observability Hardening](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-evaluation-observability-hardening/README.md>)
- [Sprint: Long-Context Robustness and Adversarial Evaluation](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-long-context-robustness-and-adversarial-evaluation/README.md>)
- [Sprint: Context Correctness Evaluation](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-context-correctness-evaluation/README.md>)
- Previous completed sprint:
  - [Sprint: Orchestrator Boundary Finalization](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-orchestrator-boundary-finalization/README.md>)

## Inactive Sprints

### Completed
- [Sprint: AI Runtime Foundation](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-ai-runtime-foundation/README.md>)
- [Sprint: Customer Response Accuracy](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-customer-response-accuracy/README.md>)
- [Sprint: Runtime Ownership Consolidation](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-runtime-ownership-consolidation/README.md>)
- [Sprint: Fallback Clarify Segmentation](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-fallback-clarify-segmentation/README.md>)
- [Sprint: Orchestrator Boundary Finalization](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-orchestrator-boundary-finalization/README.md>)
- [Sprint: Long-Context Robustness and Adversarial Evaluation](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-long-context-robustness-and-adversarial-evaluation/README.md>)

### Pending
- None

### Blocked
- None

## Immediate Next Step
- Keep tracking docs aligned to `docs/ai/agent-implementation-plan.md`.
- Select the next Phase 3 hardening follow-up.

## Tracking Policy
- `phases/` is the higher-level project status model.
- `sprints/` is the default place for active implementation work.
- `tasks/` is reserved for smaller follow-up work that does not need a sprint.
- Sprint status is managed here, not in `docs/ai/agent-implementation-plan.md`.

## Historical Sprint Highlights
- The original foundational implementation work is now grouped under:
  - [Sprint: AI Runtime Foundation](</c:/Project_WebChat/docs/ai/tracking/sprints/sprint-ai-runtime-foundation/README.md>)
- That sprint includes the historical execution tasks for:
  - primary orchestration
  - tool promotion
  - thin routing
  - orchestration contracts
  - AI tests

## Current High-Signal Notes
- The strongest current architectural truth remains the same: the system is viable and agent-ready with moderate changes, but reasoning is still fragmented across routing and component knowledge logic.
- The runtime-ownership-consolidation sprint is now completed.
- `understanding.py` moved to a hint-first LLM contract:
  - the prompt now asks for explicit hint booleans
  - `_llm_understanding()` now prefers explicit hint payloads over weak workflow labels
  - deterministic understanding now derives compatibility workflow from hints through a shared helper instead of separate staged returns
  - the remaining live-path `workflow_hypothesis` reads are now compatibility/debug only
- `decision_engine.py` now selects execution from route capability and tool suitability rather than staged workflow ownership.
- `workflow_knowledge.py` now separates retrieval, evidence evaluation, answer attempts, and degrade policy more cleanly.
- The orchestrator now consumes normalized tool-result artifacts from the tool layer instead of owning raw per-tool payload branching in the core loop.
- Fallback semantics are more coherent across agentic, component, and runtime-error paths.
- The fallback-clarify-segmentation sprint is now completed:
  - broad fallback reasons are now segmented into explicit customer-input classes
  - knowledge clarify and knowledge unavailable remain distinct through the knowledge path
  - clarify policy now emits explicit category/debug metadata and stronger category-specific copy
  - clarify rendering now skips unnecessary contextual rewrites when policy copy is already strong
- Focused verification passed:
  - `39 passed` on the unit chat routing/knowledge/agentic suites
  - `15 passed` on the integration chat agentic/component suites
- Focused verification for fallback/clarify segmentation passed:
  - `72 passed` on focused unit + integration fallback/clarify suites
  - `13 passed` on the broader component-primary integration suite
- The orchestrator-boundary-finalization sprint is now completed:
  - typed tool artifacts are normalized at the tool registry boundary
  - the orchestrator merges normalized artifacts instead of parsing raw tool payload shape
  - focused verification passed with `23 passed`
  - broader verification passed with `46 passed`
- The Context Correctness Evaluation sprint is now completed:
  - seeded DB context follow-ups now cover product, policy, mixed-topic, and no-anchor cases
  - the accuracy evaluator now scores context anchors directly
  - regression and DB-grounded suites both pass
- The Long-Context Robustness and Adversarial Evaluation sprint is now completed:
  - long-context decay and re-anchoring cases are now covered by dedicated seeded scenarios
  - adversarial prompt-injection, jailbreak, redirect, and unsafe refusal cases are now covered
  - trend reporting now surfaces long-context and adversarial groups directly
  - a repeatable performance guardrail now exists for a representative chat path
- The Evaluation Observability Hardening sprint is now completed:
  - accuracy eval returns repeatable failure clusters for baseline comparison
  - borderline cases have a reusable manual review rubric
  - the deterministic performance guard now checks stable signal shape rather than raw latency values
- Phase 2 runtime consolidation is complete.
- The Conversation State Diagnostics sprint produced the first diagnostics slice:
  - QA metrics now expose conversation-state enabled/written/version signals
  - the diagnostics summary now tracks state-enabled rows and loaded versions
- Phase 3 hardening and expansion remains active, with grounded response quality as the current follow-up.
- Grounded Response Quality is now active as the correctness-focused Phase 3 sprint:
  - it adds structured search planning, evidence grounding, safe fallback, and natural evidence-bound response composition
  - the goal is to stop incorrect or weakly related retrieved data from reaching customer-facing answers
  - search plan, grounding contract, catalog enforcement, knowledge/mixed grounding, agentic metadata, and QA metric aggregation are implemented
  - grounding-specific natural response composition is implemented
  - DB-grounded verification passed with local Supabase Postgres on `localhost:54322`
  - post-completion smoke testing fixed explicit product-browse routing, return-policy routing, mixed payment/product routing, broad rescue compatibility, and attribute-list overreach
- The historical AI runtime foundation work is complete and preserved in sprint history.
- The customer-response-accuracy sprint is complete and remains useful as a finished evaluation-hardening reference.

## Not In Scope For This Tracker
- Multi-tenant support
- Non-Magento platform support
- Order/account/cart tools
- Ticket handoff
- Generic platform abstractions
