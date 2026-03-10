# Architecture Planning Prompt

## Purpose
Define a reusable prompt for turning an AI chat-commerce audit into an implementation plan with concrete milestones.

## Context
Use this after an audit identifies Partial or Missing capabilities. It emphasizes pragmatic sequencing, explicit scope, and measurable acceptance criteria.

## Content

### When to Use

- After completing a chat-commerce AI audit.
- Before sprint planning for AI/search/memory features.
- When prioritizing foundation work over UI-only tasks.

### Required Inputs

- Audit output with evidence and gaps.
- Current backend/frontend constraints.
- Existing API contracts and database tables.
- Delivery window and team constraints.

### Planning Prompt Template

```text
You are a systems architect for AI chat-commerce.

Given the audit findings and repository evidence, produce a phased implementation plan.

Requirements:
- Prioritize by business impact and dependency order.
- Separate "foundation", "capability", and "hardening" work.
- Include data model changes, API changes, service changes, and prompt changes.
- For each item include:
  1) What to build
  2) Why it matters
  3) Dependencies
  4) Acceptance criteria
  5) Risks

Output format:
# AI Chat-Commerce Implementation Plan
## 1. Target Outcomes
## 2. Current Constraints
## 3. Phased Plan
## 4. API and Data Contract Changes
## 5. Test and Observability Plan
## 6. Rollout Strategy
```

### Planning Quality Bar

- Every phase must ship independently.
- Every phase must include at least one measurable acceptance check.
- Avoid introducing new abstractions without immediate usage.

## Related Files

- `docs/architecture/implementation-roadmap.md`
- `docs/architecture/commerce-intent-schema.md`
- `docs/architecture/conversation-state-design.md`
- `backend/app/services/chat/unified_chat_runtime.py`
