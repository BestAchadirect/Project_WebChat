# Chat Commerce Audit Prompt

## Purpose
Provide a repeatable prompt template to audit whether a repository is a real AI chat-commerce system versus a basic chat integration.

## Context
This prompt is used during architecture reviews, backlog grooming, and readiness checks. It is designed to force evidence-based conclusions tied to code and docs.

## Content

### When to Use

- Before planning major AI feature work.
- Before stakeholder demos that claim chat-commerce readiness.
- After large backend or prompt refactors.

### Required Inputs

- Current repository structure.
- Backend chat and search modules.
- API routes and schemas.
- Frontend chat widget behavior.
- Existing docs and prompt modules.

### Audit Prompt Template

```text
You are an AI system auditor for chat-based ecommerce.

Your job is to inspect the repository and evaluate whether the system includes the essential Core AI Components for Chat Commerce.

Evaluate these 5 components:
1) Natural Language Understanding (NLU)
2) Product Search AI
3) Product Recommendation
4) Conversational Memory / Context Handling
5) Checkout / Business Logic Integration

Rules:
- Do not guess.
- If evidence is missing, explicitly say "not enough evidence".
- Mark each component as Present / Partial / Missing.
- Distinguish strict AI capability from simple UI/backend plumbing.
- Cite concrete evidence: files, functions, routes, schema fields, and runtime behavior.

Output format:

# Chat Commerce AI Audit

## 1. Executive Summary
## 2. Component-by-Component Assessment
### <Component Name>
Status: Present / Partial / Missing
Evidence:
- ...
Reasoning:
- ...
Gap:
- ...

## 3. System Maturity Score (0-100)
## 4. Priority Next Steps (Top 5)
## 5. Final Verdict
```

### Review Checklist for the Auditor

- Did every claim include a concrete file/path reference?
- Were missing capabilities called out explicitly as missing?
- Is the maturity score aligned with the evidence quality?

## Related Files

- `docs/architecture/system-overview.md`
- `docs/architecture/commerce-intent-schema.md`
- `docs/architecture/conversation-state-design.md`
- `backend/app/prompts/nlu.py`
- `backend/app/prompts/localization.py`
