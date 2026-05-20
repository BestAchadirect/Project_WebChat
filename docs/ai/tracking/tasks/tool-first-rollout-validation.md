# Tool-First Rollout Validation

## Status
- Status: `red_needs_tuning`
- Phase: Phase 3, tool-first backend rollout stabilization
- Scope: backend QA-log validation only

## Goal
Validate the default-on tool-first path with real QA logs before any legacy ChatHarness runtime shim cleanup.

## Validation Gate
Legacy shim cleanup remains blocked until each active channel reaches a Green validation window under `docs/runbooks/tool-first-chat-rollout.md`.

Minimum useful sample:

- `100` tool-first selected rows per channel, or
- `48h` of QA traffic if traffic volume is lower.

Required channels:

- `widget`
- `qa_console`

## Latest Local Check
- Date: 2026-05-20
- Command:

```powershell
cd backend
.\venv\Scripts\python.exe scripts\check_tool_first_rollout.py --base-url http://localhost:8000 --timeout-seconds 5
```

- Result: endpoint reachable through `/api/v1/dashboard/qa`, but both channels returned `selected=0`.
- Assessment: `insufficient_sample`, not a valid rollout window.
- Action: generate or collect real QA traffic before evaluating shim cleanup readiness.

## Latest Tool-First Smoke
- Date: 2026-05-20
- Sample: local `qa_console` catalog and knowledge requests through `ChatService.process_chat()`.
- Result:
  - `qa_console`: `selected=17`, `fallback_to_component_rate=94.12%`, `grounding_failed_rate=88.24%`.
  - `widget`: `selected=0`, still insufficient sample.
  - One clear knowledge request, shipping policy, reached `agentic_primary` with grounded sources.
- Assessment: Red for `qa_console`, insufficient sample for `widget`.
- Tuning already applied:
  - Forced a final no-tool answer pass when tool calls succeed but the model returns blank text.
  - Added deterministic product/source-bound final text when final answer generation is blank or errors.
  - Tightened catalog tool guidance to use planner filter names exactly and avoid invented filters.
- Remaining top failure bucket: `agentic_grounding_failed`.
- Next tuning target:
  - Catalog search argument quality for required filters and semantic terms.
  - Knowledge retrieval/query behavior for return-policy requests that still produce empty or weak agentic artifacts.

## Pass Criteria
- `widget` is Green.
- `qa_console` is Green.
- No spike in `failed` or `no_answer` rows.
- Repeated customer-facing failures have regression coverage before behavior changes.

## Failure Handling
- If `expected_tool_missing` dominates, tune `SearchPlan.expected_tool_groups()` or orchestrator tool guidance first.
- If `grounding_failed` dominates, inspect tool arguments and grounding decisions before weakening grounding.
- If `fallback_to_component` dominates without expected-tool or grounding failure, inspect agentic errors, empty tool results, and no-tool answers.
- If any channel is Red, create a targeted tuning task from the highest-count failure bucket and keep shims.
