# Tool-First Chat Rollout Runbook

## Purpose
Use this runbook to validate the default-on tool-first chat path before any legacy runtime shim cleanup. This is backend-only rollout monitoring. Do not change frontend contracts, database schema, or public chat response shape as part of this validation.

## Rollout Summary Endpoint
Query the rollout summary endpoint from an authenticated admin or local test environment:

```http
GET /api/v1/dashboard/qa/qa-logs/rollout-summary
```

The default local API prefix is `/api/v1`. If a gateway strips that prefix, use `/dashboard/qa/qa-logs/rollout-summary` at the gateway boundary.

Useful query parameters:

- `channel`: filter by channel, usually `widget` or `qa_console`.
- `workflow`: filter by public workflow, such as `catalog`, `knowledge`, or `fallback`.
- `agenticIssue`: filter by `expected_tool_missing`, `grounding_failed`, `fallback_to_component`, or `tool_first_selected`.
- `agenticFallbackReason`: filter by exact fallback reason, such as `agentic_expected_tool_missing` or `agentic_grounding_failed`.
- `harnessTool`: filter rows where `debug.harness_trace.tools_called` includes a tool, such as `search_products` or `search_knowledge_base`.
- `createdFrom` and `createdTo`: filter by ISO datetime range.
- `maxRows`: cap sampled rows, default `5000`, maximum `20000`.

Example checks:

```http
GET /api/v1/dashboard/qa/qa-logs/rollout-summary?channel=widget&createdFrom=2026-05-18T00:00:00Z
GET /api/v1/dashboard/qa/qa-logs/rollout-summary?channel=qa_console&agenticIssue=tool_first_selected
GET /api/v1/dashboard/qa/qa-logs/rollout-summary?agenticIssue=expected_tool_missing
GET /api/v1/dashboard/qa/qa-logs/rollout-summary?agenticIssue=grounding_failed
GET /api/v1/dashboard/qa/qa-logs/rollout-summary?harnessTool=search_products
```

The response includes `toolFirst.fallback_to_component_rate`, `toolFirst.expected_tool_missing_rate`, `toolFirst.grounding_failed_rate`, `toolFirst.top_tools`, and breakdowns by route, workflow, fallback reason, and missing expected tool.

## Validation Script
Use the backend helper to run the same checks repeatably:

```powershell
cd backend
.\venv\Scripts\python.exe scripts\check_tool_first_rollout.py --base-url http://localhost:8000
```

Common options:

- `--channels widget qa_console`: channels to validate.
- `--qa-prefix /api/v1/dashboard/qa`: mounted QA route prefix.
- `--created-from 2026-05-18T00:00:00Z --created-to 2026-05-20T00:00:00Z`: validation window.
- `--max-rows 5000`: endpoint sample size.
- `--minimum-selected 100`: minimum useful tool-first selected rows per channel.
- `--output-json rollout-report.json`: save the full assessment.
- `--header NAME=VALUE`: add an HTTP header. If `QA_API_TOKEN` is set, the script sends `Authorization: Bearer <token>`.

Exit codes:

- `0`: all checked channels are Green.
- `1`: at least one checked channel is Red.
- `2`: at least one checked channel is Yellow, has insufficient sample, or the endpoint could not be queried.

## QA Log Filtering
Use QA log list filters for row-level triage:

```http
GET /api/v1/dashboard/qa/qa-logs?agenticIssue=expected_tool_missing
GET /api/v1/dashboard/qa/qa-logs?agenticIssue=grounding_failed
GET /api/v1/dashboard/qa/qa-logs?agenticIssue=fallback_to_component
GET /api/v1/dashboard/qa/qa-logs?agenticFallbackReason=agentic_expected_tool_missing
GET /api/v1/dashboard/qa/qa-logs?harnessTool=search_knowledge_base
GET /api/v1/dashboard/qa/qa-logs?workflow=catalog&channel=widget
GET /api/v1/dashboard/qa/qa-logs?createdFrom=2026-05-18T00:00:00Z&createdTo=2026-05-20T00:00:00Z
```

Open representative rows and inspect `token_usage.chat_metrics`, `debug.harness_trace`, route metadata, tool names, grounding status, fallback reason, and final answer shape.

## Thresholds
Minimum useful sample:

- `100` tool-first selected rows per channel, or
- `48h` of QA traffic if traffic volume is lower.

Green:

- `fallback_to_component_rate < 10%`
- `expected_tool_missing_rate < 2%`
- `grounding_failed_rate < 2%`

Yellow:

- `fallback_to_component_rate` from `10%` to `20%`
- `expected_tool_missing_rate` from `2%` to `5%`
- `grounding_failed_rate` from `2%` to `5%`

Red:

- `fallback_to_component_rate > 20%`
- `expected_tool_missing_rate > 5%`
- `grounding_failed_rate > 5%`
- Any spike in `failed` or `no_answer` QA statuses.

If any channel is Red, do not proceed to legacy shim cleanup. Create a targeted tuning task from the highest-count failure bucket.

## Required Validation Queries
Run these before declaring the validation window healthy:

- Overall rollout summary for `channel=widget`.
- Overall rollout summary for `channel=qa_console`.
- QA log list for `agenticIssue=expected_tool_missing`.
- QA log list for `agenticIssue=grounding_failed`.
- QA log list for `agenticIssue=fallback_to_component`.
- Top tool summary from `toolFirst.top_tools`.
- Fallback reason summary from `toolFirst.by_agentic_fallback_reason`.

## Triage Steps
For `agentic_expected_tool_missing`:

1. Check `toolFirst.by_agentic_missing_expected_tool` to find the missing tool group.
2. Inspect sample rows and compare requested workflow against `harness_trace.metadata.agentic_tool_expectations`.
3. Tune `SearchPlan.expected_tool_groups()` or orchestrator tool guidance first.
4. Do not add routing branches unless the route itself is genuinely wrong.

For `agentic_grounding_failed`:

1. Inspect `harness_trace.tools_called`, tool arguments, retrieved product/source counts, and grounding status.
2. Verify the tool result was related to the user request.
3. Tune tool arguments, query planning, or grounding evidence mapping before weakening grounding.
4. Add a regression case for repeated customer-facing failures.

For `agentic_fallback_to_component`:

1. Split rows by `agenticFallbackReason`.
2. Check for agentic errors, empty tool results, no-tool answers, expected-tool missing, and grounding failures.
3. If no specific reason dominates, inspect orchestrator traces and component fallback output quality.
4. Keep deterministic component fallback enabled while tuning.

## Follow-Up Rules
- If `expected_tool_missing` dominates, tune `SearchPlan.expected_tool_groups()` or orchestrator tool guidance first.
- If `grounding_failed` dominates, inspect tool arguments and grounding decisions before changing thresholds.
- If `fallback_to_component` dominates without expected-tool or grounding failure, inspect agentic errors, empty tool results, and no-tool answers.
- Add a regression case for every repeated customer-facing issue before changing behavior.
- Keep `runtime.unified_chat_runtime` and `runtime.execution_coordinator` compatibility shims until at least one Green validation window passes.
