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

## Structure
- `project-status.md`: top-level status board
- `phases/`: project-level implementation phases and current overall status
- `tasks/`: cross-sprint follow-up work items that stay within the existing plan
- `sprints/`: active execution packages with sprint-level docs and sprint task lists

## Tracking Model
- Use `phases/` for the bigger project stages.
- Use `sprints/` as the default tracker for current and future active work.
- Use `tasks/` for small follow-up items that do not need a full sprint package.
- `project-status.md` should show both the broader phase position and the active sprint.
- `project-status.md` is the source of truth for which sprint is active vs inactive.

## Document Roles
- `project-status.md` is the dashboard:
  - what phase the project is in
  - what sprint is active
  - what sprints are inactive
  - what the next implementation step is
- `phases/` records project-level stage intent and status
- `sprints/` records real execution packages and their task lists
- `tasks/` records smaller follow-up work outside a full sprint

## Current Project Phases
- `phases/phase-1-foundation-and-agentic-adoption.md`
- `phases/phase-2-runtime-consolidation.md`
- `phases/phase-3-hardening-and-expansion.md`

## Current Active Sprint
- None currently assigned

## Historical Sprint Examples
- `sprints/sprint-ai-runtime-foundation/README.md`
- `sprints/sprint-customer-response-accuracy/README.md`
- `sprints/sprint-fallback-clarify-segmentation/README.md`

## Supporting Task Example
- Add a `tasks/` item only when the work does not need a full sprint package.

## Status Labels
- `pending`: not started
- `in_progress`: active implementation phase
- `blocked`: cannot proceed without clarification or prerequisite work
- `completed`: work is finished and exit criteria are met

## Sprint State Rule
- Exactly one sprint should be treated as active at a time.
- The active sprint must be listed in `project-status.md` under `Active Sprint`.
- All other sprints should be treated as inactive and listed under:
  - `Completed`
  - `Pending`
  - `Blocked`
- `agent-implementation-plan.md` should describe strategy and priorities, not sprint state.

## Update Rule
When a task changes state:
1. Update the relevant phase file
2. Update the relevant file under `tasks/` when the work item is not a new phase
3. Update the relevant sprint file under `sprints/` when the work is being managed as a sprint
4. Update `project-status.md`
5. Keep changes factual and short
