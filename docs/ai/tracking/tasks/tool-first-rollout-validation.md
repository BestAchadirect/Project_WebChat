# Tool-First Rollout Validation

## Status
- Status: `local_dev_gate_passed_release_gate_deferred`
- Phase: Phase 3, tool-first backend rollout stabilization
- Scope: backend QA-log validation only

## Goal
Validate the default-on tool-first path with real QA logs before staging/release rollout.

## Validation Approach
Use the faster local development gate during implementation and defer the full rollout gate to staging/release traffic.

Local development gate:

- focused backend tests pass
- `scripts/smoke_tool_first_chat.py --channels widget qa_console` passes
- rollout checker is Green for that smoke window using the per-channel `--minimum-selected` printed by the smoke script

Staging/release gate:

- `100` tool-first selected rows per active channel, or
- `48h` of QA traffic if traffic volume is lower

## Validation Gate
Production rollout remains blocked until each active channel reaches a Green validation window under `docs/runbooks/tool-first-chat-rollout.md`.

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
.\venv\Scripts\python.exe scripts\check_tool_first_rollout.py --base-url http://localhost:8000 --channels widget qa_console --minimum-selected 100 --timeout-seconds 10
```

- Result: all-history local QA logs are Red because they include older failed rows from before the tool-quality fixes.
- Current all-history counts:
  - `widget`: `selected=6`, `fallback_to_component_rate=33.33%`, `grounding_failed_rate=16.67%`.
  - `qa_console`: `selected=25`, `fallback_to_component_rate=72.00%`, `grounding_failed_rate=68.00%`.
- Assessment: not a clean validation window; use a post-fix date range for current behavior.
- Post-fix gate command:

```powershell
cd backend
.\venv\Scripts\python.exe scripts\check_tool_first_rollout.py --base-url http://localhost:8000 --channels widget qa_console --minimum-selected 100 --created-from 2026-05-20T08:35:00Z --timeout-seconds 10
```

- Post-fix result:
  - `widget`: `selected=4`, `fallback_to_component_rate=0%`, `expected_tool_missing_rate=0%`, `grounding_failed_rate=0%`.
  - `qa_console`: `selected=4`, `fallback_to_component_rate=0%`, `expected_tool_missing_rate=0%`, `grounding_failed_rate=0%`.
- Assessment: current post-fix quality is Green for local development, but the release gate remains deferred because both channels are below `100` selected rows.
- Action: collect staging/release QA traffic before evaluating production rollout readiness.

## Latest Tool-First Smoke
- Date: 2026-05-20
- Sample: local `qa_console` and `widget` catalog and knowledge requests through `ChatService.process_chat()`.
- Result:
  - Original local history: `qa_console` was Red because early failed samples remained in the sampled window.
  - Post-fix window from `2026-05-20T08:35:00Z`: `qa_console` was Green with `selected=4`, `fallback_to_component_rate=0%`, `grounding_failed_rate=0%`.
  - Post-fix window from `2026-05-20T08:45:30Z`: `widget` was Green with `selected=4`, `fallback_to_component_rate=0%`, `expected_tool_missing_rate=0%`, `grounding_failed_rate=0%`.
  - Return policy, shipping policy, black opal labrets, and titanium labrets reached `agentic_primary` with grounded output in both post-fix smoke windows.
- Assessment: Green for the latest local smoke windows on both active channels; still below the full rollout gate sample size.
- Repeatable smoke helper run from `2026-05-20T09:05:32Z` returned `7/8` passing cases:
  - One `widget` `titanium_labrets` turn fell back with `agentic_error` before tool execution.
  - An immediate direct rerun of the same `widget` titanium query reached `agentic_primary` with `search_products` and grounded product cards.
- Repeatable smoke helper run from `2026-05-20T09:16:56Z` returned `4/8` passing cases:
  - Failures were `agentic_error` before tool execution on supported catalog/knowledge turns.
- Repeatable smoke helper run from `2026-05-20T09:23:36Z` returned `7/8` passing cases:
  - `agentic_error` was cleared by search-plan tool fallback.
  - One `qa_console` `black_opal_labrets` turn failed grounding because `opal` was treated as hard `material=opal`.
- Repeatable smoke helper run from `2026-05-20T09:29:23Z` returned `8/8` passing cases:
  - `widget`: `selected=4`, `fallback_to_component_rate=0%`, `expected_tool_missing_rate=0%`, `grounding_failed_rate=0%`.
  - `qa_console`: `selected=4`, `fallback_to_component_rate=0%`, `expected_tool_missing_rate=0%`, `grounding_failed_rate=0%`.
  - Persisted rollout summary for that exact window was Green for both channels with `--minimum-selected 4`.
- Local development gate: passed.
- Tuning already applied:
  - Forced a final no-tool answer pass when tool calls succeed but the model returns blank text.
  - Added deterministic product/source-bound final text when final answer generation is blank or errors.
  - Tightened catalog tool guidance to use planner filter names exactly and avoid invented filters.
  - Normalized tool arguments from `SearchPlan` before execution.
  - Aligned agentic catalog filter matching with detail/grounding filter matching.
  - Added structured and lexical rescue inside the agentic product search tool.
  - Added search-plan fallback tool execution when the agentic LLM tool-selection call errors before tool use.
  - Moved decorative `opal` out of hard `material` filters and into semantic terms unless the user explicitly asks for material.
- Remaining blocker: release gate is deferred until staging/production has `100` tool-first selected rows per channel or `48h` of QA traffic.
- Repeatable local helper: `backend/scripts/smoke_tool_first_chat.py`.
- Next tuning target:
  - Continue monitoring larger `widget` and `qa_console` windows because old local failed rows still make all-history summaries Red.
  - Watch for repeated `agentic_error` before tool execution and repeated `opal`/decorative-stone grounding failures in larger samples.
  - If either channel turns Yellow or Red in the larger window, tune the highest-count failure bucket before production rollout.

## Pass Criteria
- `widget` is Green.
- `qa_console` is Green.
- No spike in `failed` or `no_answer` rows.
- Repeated customer-facing failures have regression coverage before behavior changes.

## Failure Handling
- If `expected_tool_missing` dominates, tune `SearchPlan.expected_tool_groups()` or orchestrator tool guidance first.
- If `grounding_failed` dominates, inspect tool arguments and grounding decisions before weakening grounding.
- If `fallback_to_component` dominates without expected-tool or grounding failure, inspect agentic errors, empty tool results, and no-tool answers.
- If any channel is Red, create a targeted tuning task from the highest-count failure bucket before production rollout.
