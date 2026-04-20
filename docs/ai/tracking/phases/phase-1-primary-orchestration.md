# Phase 1: Primary Orchestration

## Status
- Phase status: `in_progress`

## Goal
Make the tool-calling path the default execution path for supported read-only requests.

## Why This Phase Comes First
The current system still treats tool use as secondary.
If this is not changed first, later work will keep strengthening the staged pipeline instead of the AI-first path.

## Primary Files
- `backend/app/services/chat/runtime/unified_chat_runtime.py`
- `backend/app/services/chat/routing/decision_engine.py`
- `backend/app/services/chat/routing/routing_policy.py`
- `backend/app/services/chat/agentic/orchestrator.py`
- `backend/app/services/chat/agentic/tool_registry.py`

## Phase Outcome
At the end of this phase, supported read-only product and knowledge requests should try the tool path first, and the component pipeline should mainly serve as fallback and response composition.

## Task Breakdown

### 1.1 Audit current agentic eligibility and decision flow
Status: `completed`

Files:
- `backend/app/services/chat/routing/routing_policy.py`
- `backend/app/services/chat/routing/decision_engine.py`
- `backend/app/services/chat/runtime/unified_chat_runtime.py`

Checklist:
- [x] Confirm the current eligibility conditions that block agentic execution
- [x] Identify which current read-only requests should be agentic-first
- [x] List the current component-first branches that still exist for those requests

Done when:
- A clear before-state is recorded for current agentic selection behavior

Audit findings:
- `routing_policy.is_agentic_tool_suitable()` is the main choke point. It currently returns `True` only when a SKU token is present, or when the public workflow is `catalog` and the route needs both products and knowledge. That excludes most straightforward catalog-only requests and most knowledge-only requests from agentic-first execution.
- `decision_engine.build_decision_state()` is staged-first by construction. It only selects `agentic` when feature flags are enabled, the channel is allowed, the public workflow is not `fallback`, and `tool_suitable` is already `True`. Because the suitability gate is narrow, component mode remains the default for most supported read-only requests.
- `unified_chat_runtime.process_chat()` already has the right fallback shape once `agentic` is selected. It tries `_run_agentic_workflow()` first, records explicit fallback reasons such as `no_tool_usage`, `empty_result`, and `agentic_error`, and then falls back to the component pipeline cleanly.
- The current tool surface is already sufficient for the first migration slice: `search_products`, `get_product_details`, `search_knowledge_base`, and `check_inventory_db`.
- The first requests that should become agentic-first are: product detail by SKU or direct product reference, straightforward catalog discovery/search, and read-only knowledge or policy lookup.
- Current component-first behavior for those requests is mostly an eligibility artifact, not a runtime limitation. The agentic path is not failing first; it is usually not being selected first.

### 1.2 Expand agentic eligibility for supported read-only requests
Status: `completed`

Files:
- `backend/app/services/chat/routing/routing_policy.py`

Checklist:
- [x] Widen `is_agentic_tool_suitable()` for supported read-only catalog requests
- [x] Widen `is_agentic_tool_suitable()` for supported read-only knowledge requests
- [x] Keep obvious unsupported or unsafe cases out of the widened path

Done when:
- Supported read-only product and knowledge requests are no longer narrowly excluded by suitability logic

Implementation notes:
- `routing_policy.is_agentic_tool_suitable()` now treats supported read-only requests as tool-suitable when they actually need the corresponding data path: `catalog` requires `needs_products`, `knowledge` requires `needs_knowledge`.
- SKU-based detail requests remain tool-suitable, but they are no longer the only straightforward catalog requests that can enter the agentic path.
- Unsupported workflows such as `off_topic` and empty or structurally unsupported requests remain excluded.
- Focused verification passed: `25 passed` on `backend/tests/unit/chat/test_chat_routing_policy.py` and `backend/tests/unit/chat/test_chat_decision_engine.py`.

### 1.3 Make decision engine prefer agentic for supported requests
Status: `completed`

Files:
- `backend/app/services/chat/routing/decision_engine.py`

Checklist:
- [x] Update execution-mode selection so supported requests prefer `agentic`
- [x] Keep fallback behavior explicit when suitability or feature gates fail
- [x] Keep public/internal workflow mapping stable while changing execution preference

Done when:
- `DecisionState` prefers agentic execution for supported read-only requests

Implementation notes:
- `decision_engine.build_decision_state()` already preferred `agentic` when feature flags, channel gating, and tool suitability all passed. No additional branching change was required after widening the suitability rule in task `1.2`.
- Added regression coverage to confirm the staged decision engine now selects `agentic` for supported catalog and knowledge requests when agentic execution is enabled on the allowed channel.
- Focused verification passed: `27 passed` on `backend/tests/unit/chat/test_chat_routing_policy.py` and `backend/tests/unit/chat/test_chat_decision_engine.py`.

### 1.4 Make unified runtime treat component pipeline as fallback
Status: `completed`

Files:
- `backend/app/services/chat/runtime/unified_chat_runtime.py`

Checklist:
- [x] Ensure the runtime attempts the agentic path first for supported requests
- [x] Keep the component pipeline as fallback when agentic returns no tools, empty result, or failure
- [x] Preserve deterministic runtime error handling

Done when:
- The runtime attempts agentic execution first for supported requests and falls back cleanly

Implementation notes:
- `unified_chat_runtime.process_chat()` already had the correct fallback shape once `agentic` was selected. No runtime branch rewrite was required.
- Added integration coverage for two missing cases in `backend/tests/integration/chat/test_chat_service_component_primary.py`:
  - supported knowledge requests now try the agentic path first before falling back to the component pipeline
  - the `no_tool_usage` branch now has explicit fallback coverage instead of only `None` and exception paths
- Focused verification passed: `10 passed` on `backend/tests/integration/chat/test_chat_service_component_primary.py`.

### 1.5 Preserve explicit failure reasons across fallback transitions
Status: `completed`

Files:
- `backend/app/services/chat/runtime/unified_chat_runtime.py`
- `backend/app/services/chat/runtime/agentic_adapter.py`
- `backend/app/services/chat/routing/decision_engine.py`

Checklist:
- [x] Preserve machine-readable fallback reasons
- [x] Preserve no-tool and empty-result distinctions
- [x] Confirm debug payload still exposes useful reason chains

Done when:
- Agentic fallback transitions remain inspectable and do not collapse into ambiguous behavior

Implementation notes:
- No runtime branch change was required. `agentic_adapter.apply_agentic_fallback_debug()` and `unified_chat_runtime.process_chat()` already preserved machine-readable fallback information.
- Added integration assertions to confirm the response debug payload keeps:
  - `fallback_reason=empty_result` with `failure_reason=agentic_failed:empty_result`
  - `fallback_reason=no_tool_usage` with `failure_reason=agentic_failed:no_tool_usage`
  - `fallback_reason=agentic_error` with `failure_reason=agentic_failed:RuntimeError`
- Focused verification passed: `10 passed` on `backend/tests/integration/chat/test_chat_service_component_primary.py`.

### 1.6 Record remaining component-first exceptions
Status: `completed`

Files:
- `backend/app/services/chat/runtime/unified_chat_runtime.py`
- `backend/app/services/chat/components/pipeline_runtime/core.py`
- `docs/ai/tracking/phases/phase-1-primary-orchestration.md`

Checklist:
- [x] Identify flows that should remain component-first for now
- [x] Record why those flows should not move yet
- [x] Keep the exception list short and explicit

Done when:
- Remaining component-first cases are documented and justified

Exception list for Phase 1:
- `off_topic` and smalltalk-style requests stay component-first. They do not require product or knowledge tools, and pushing them through the tool loop adds no value.
- `fallback` / clarification requests stay component-first. These are the cases where understanding is ambiguous, the request is structurally incomplete, or the system intentionally needs a clarification response rather than a tool plan.
- Understanding-failure cases stay component-first. When staged understanding returns a machine failure reason such as `understanding_failed:*`, the safe next step remains deterministic fallback rather than speculative tool execution.
- Feature-disabled or channel-disallowed requests stay component-first. This is an operating-mode guardrail, not a product capability gap.

Notes:
- This list is intentionally short. Supported read-only catalog and knowledge requests are no longer on the exception list.
- Mixed product-plus-knowledge requests should continue moving through the widened agentic-first path unless later testing shows the current tool surface is insufficient.

## Suggested Execution Order
1. Task 1.1
2. Task 1.2
3. Task 1.3
4. Task 1.4
5. Task 1.5
6. Task 1.6

## Exit Criteria
- Supported read-only product and knowledge requests attempt agentic execution first
- Component pipeline is fallback, not default, for those supported requests
- Fallback behavior remains deterministic and debuggable
- Remaining component-first cases are explicit, short, and justified

## Notes
- Do not expand tool count in this phase unless required to make the path viable
- Do not start frontend cleanup in this phase
