# AI and Prompt Ops

## Purpose
Centralize AI-facing documentation for prompt operations, audit workflows, and architecture planning tasks.

## Context
Runtime prompts are defined in backend code, while this folder documents how to operate and evolve those prompts safely for chat-commerce use cases.

## Content

### Prompt-Ops Docs

- `chat-commerce-audit-prompt.md`: reusable audit prompt for evaluating chat-commerce maturity.
- `architecture-planning-prompt.md`: reusable planning prompt for converting gaps into implementation plans.

### Runtime Prompt Sources

- `backend/app/prompts/nlu.py`: active NLU prompt builders.
- `backend/app/prompts/localization.py`: active UI localization prompt builders.
- `backend/app/services/ai/llm_service.py`: NLU, localization, and JSON-generation runtime calls.

### Operating Guidelines

- Keep prompt contracts explicit and schema-first.
- Prefer updating existing prompt docs over adding near-duplicate variants.
- Link prompt docs to concrete backend modules that execute the prompt.

## Related Files

- `backend/app/prompts/nlu.py`
- `backend/app/prompts/localization.py`
- `backend/app/services/ai/llm_service.py`
- `docs/README.md`
