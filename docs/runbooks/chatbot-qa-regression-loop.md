# Chatbot QA Regression Loop

## Purpose
Use this runbook to turn real QA failures into repeatable regression coverage without letting the chatbot modify itself in production.

## Principle
- The live chatbot stays deterministic and grounded.
- QA logs identify failures.
- Humans review the failure, decide the expected behavior, and then promote it into a regression dataset.
- Every fix must pass regression checks before release.

## Daily Flow
1. Mine recent failures.
2. Review the dominant failure buckets.
3. Export one or more QA logs into regression review bundles.
4. Promote the reviewed bundle into the correct regression dataset.
5. Fix the underlying layer.
6. Run regression checks before deploy.

## Commands
Inspect recent QA failures:

```powershell
backend\venv\Scripts\python.exe backend\scripts\mine_qa_failures.py --limit 100
```

Export review bundles for a bucket:

```powershell
backend\venv\Scripts\python.exe backend\scripts\export_qa_review_bundle.py --failure-bucket hard_constraint_no_match --limit 5 --output-json backend\tmp\qa-hard-no-match.json
```

Export a specific QA log:

```powershell
backend\venv\Scripts\python.exe backend\scripts\export_qa_review_bundle.py --qa-log-id <qa_log_uuid>
```

Run the regression suite:

```powershell
backend\venv\Scripts\python.exe backend\scripts\run_chat_regression_eval.py
backend\venv\Scripts\python.exe -m pytest backend\tests\regression
```

## Which Dataset To Update
- Use `backend/tests/regression/data/chat_customer_message_coverage_cases.json` when the main problem is customer phrasing, routing, or broad query handling.
- Use `backend/tests/regression/data/chat_response_contract_cases.json` when the failure is about grounding, no-match behavior, wrong answer framing, or missing response constraints.
- If a failure touches both, add a coverage case first and then add a response contract after the expected behavior is clear.

## Promotion Rules
- Do not copy a QA log directly into a regression dataset unchanged.
- Exported review bundles intentionally contain `__REVIEW_REQUIRED__` placeholders.
- Replace the placeholders only after deciding the correct expected behavior.
- If the expected behavior depends on product cards or component layout, replay the conversation before finalizing a response contract.

## Review Checklist
- Confirm the failure bucket is correct.
- Confirm which system layer failed: routing, context, retrieval, grounding, or response builder.
- Write the expected behavior explicitly.
- Add the reviewed case to the smallest dataset that proves the fix.
- Run regression checks before merging.

## Current Limitation
- Legacy QA logs do not always contain `conversation_id`.
- New QA logs now include `conversation_id` in `chat_metrics`, which improves traceability for replay and follow-up debugging.
- QA logs still do not persist full product-card/component payloads, so exported response-contract bundles are review seeds, not final test cases.
