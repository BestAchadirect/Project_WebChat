# Phase 3: Thin Routing

## Status
- Phase status: `pending`

## Goal
Reduce routing to a thin pre-orchestration layer instead of a full answer-strategy owner.

## Primary Files
- `backend/app/services/chat/routing/understanding.py`
- `backend/app/services/chat/routing/decision_engine.py`
- `backend/app/services/chat/routing/routing_policy.py`

## Tasks
- [ ] Identify routing logic that is still useful as a deterministic guardrail
- [ ] Identify routing logic that should be removed or downgraded to hints
- [ ] Keep only obvious fast paths and hard guardrails
- [ ] Remove or reduce workflow-specific staged ownership where tools can handle it
- [ ] Verify fallback and clarify paths still work after routing simplification

## Keep In Routing
- empty input detection
- obvious off-topic handling
- obvious SKU/detail fast-path hints
- hard failure fallback
- necessary clarify guardrails

## Exit Criteria
- Routing no longer owns most of the answer strategy
- Routing exists mainly to guard, hint, and fail safely
- The agentic/tool path remains primary for supported flows
