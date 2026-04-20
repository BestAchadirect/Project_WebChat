# AI Tracking Docs

This folder is the working tracker for AI implementation.

Use it for:
- current phase status
- task checklists
- exit criteria
- implementation order

Do not use it for:
- repo structure policy
- general project setup
- broad architecture rationale

Those belong in:
- `AGENTS.md`
- `README.md`
- `docs/ai/agent-implementation-plan.md`

## Files
- `project-status.md`: top-level status board
- `phases/phase-1-primary-orchestration.md`
- `phases/phase-2-tool-promotion.md`
- `phases/phase-3-thin-routing.md`
- `phases/phase-4-orchestration-contracts.md`
- `phases/phase-5-ai-tests.md`

## Status Labels
- `pending`: not started
- `in_progress`: active implementation phase
- `blocked`: cannot proceed without clarification or prerequisite work
- `done`: phase exit criteria met

## Update Rule
When a task changes state:
1. Update the relevant phase file
2. Update `project-status.md`
3. Keep changes factual and short
