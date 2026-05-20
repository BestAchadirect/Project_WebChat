# AGENTS.md

## Purpose
This is the canonical project directory policy for `Project_WebChat`.
All structural changes must align with this file.

## Scope
Use this file when creating, moving, or reviewing folders and files.
Do not move or rename directories unless explicitly requested.

## Canonical Top-Level Layout
- `backend/` : FastAPI backend, data access, RAG, integrations.
- `frontend-admin/` : React + Vite admin UI and embedded widget build.
- `shared/` : shared types and utilities used across apps.
- `docs/` : architecture notes, ADRs, and developer guides.
- `infra/` : deployment and environment infrastructure.
- `tests/` : cross-service, integration, and end-to-end tests.

## Root Files Policy
- Keep root-only control files at repo root: `.env`, `.env.example`, `README.md`, `AGENTS.md`, `dev.ps1`.
- Keep Node.js manifests and frontend build tooling in `frontend-admin/`: `package.json`, `package-lock.json`, `postcss.config.js`, `tailwind.config.js`, `tsconfig*.json`, and Vite config files.
- Do not add duplicate Node/tooling manifests at repo root unless an explicit workspace migration is approved.

## Placement Rules
- Backend HTTP routes: `backend/app/api/routes/`.
- Backend business logic: `backend/app/services/`.
- Backend service domain split:
  `backend/app/services/ai`, `backend/app/services/chat`, `backend/app/services/catalog`,
  `backend/app/services/knowledge`, `backend/app/services/imports`,
  `backend/app/services/tasks`, `backend/app/services/tickets`, `backend/app/services/legacy`.
- Canonical domain imports under `backend/app/services/<domain>/` are required; do not add legacy wrapper modules back.
- Chat component builders and registry stay in `backend/app/services/chat/components/`.
- Chat pipeline orchestration internals belong in `backend/app/services/chat/components/pipeline_runtime/`.
- Keep the public component pipeline entrypoint at `backend/app/services/chat/components/pipeline.py`.
- Chat harness observability and control wrappers belong in `backend/app/services/chat/harness/`.
- Backend schemas/models: `backend/app/schemas/` and `backend/app/models/`.
- Backend shared internals: `backend/app/core/`, `backend/app/utils/`, `backend/app/db/`.
- Backend prompts: `backend/app/prompts/`.
- Frontend reusable UI: `frontend-admin/src/components/`.
- Frontend route pages: `frontend-admin/src/routes/`.
- Frontend API clients: `frontend-admin/src/api/`.
- Frontend hooks/types/utils: `frontend-admin/src/hooks/`, `frontend-admin/src/types/`, `frontend-admin/src/utils/`.
- Shared contracts: `shared/types/`.
- Deployment and local infra scripts: `infra/`.
- Architecture docs: `docs/architecture/`.
- AI agent/prompt docs: `docs/ai/`.
- Current AI implementation guidance lives in `docs/ai/agent-implementation-plan.md`.
- AI tracking docs stay under `docs/ai/tracking/`, with status files at that folder root, phase docs in `docs/ai/tracking/phases/`, cross-sprint task docs in `docs/ai/tracking/tasks/`, and sprint packages in `docs/ai/tracking/sprints/`.
- Runbooks: `docs/runbooks/`.
- Reference docs: `docs/reference/`.

## Test Location Policy
- New backend unit and service tests should go in `backend/tests/`.
- Backend unit tests should go in `backend/tests/unit/`.
- Backend service-level integration tests should go in `backend/tests/integration/`.
- Backend regression datasets and regression contract tests should go in `backend/tests/regression/`.
- Backend FastAPI request/response contract tests should go in `backend/tests/api/`.
- Temporary compatibility and deprecation-window tests should go in `backend/tests/unit/compatibility/`.
- Cross-service and end-to-end tests should go in `tests/`.
- Existing files may remain in place during cleanup, but new tests must follow the rule above.

## Naming Conventions
- Use kebab-case for folders and file names unless framework conventions require otherwise.
- Use PascalCase for React component files.
- Use `test_*.py` for Python pytest files in `backend/tests/`.
- Use `.test` or `.spec` suffix for frontend or JavaScript/TypeScript tests.
- Keep config files at the nearest relevant scope.

## Runtime and Generated Artifacts (Never Commit)
- `backend/.venv/`
- `backend/venv/`
- `backend/__pycache__/`
- `backend/.tmp_pyc/`
- `backend/pytest-cache-files-*/`
- `backend/uploads/`
- `backend/backups/`
- `backend/logs/`
- `frontend-admin/node_modules/`
- `frontend-admin/dist/`
- `frontend-admin/.vite/`
- `frontend-admin/.eslintcache`

## Structural Change Protocol
- If a structure change is proposed, include rationale, risk, and migration impact.
- Update this file in the same change set as any approved structural change.
- Prefer extending existing folders before creating new top-level folders.
- New top-level folders require a clear, non-overlapping purpose and owner.

## Drift Review Checklist
- Summarize current top-level layout excluding runtime/generated folders.
- Compare to this policy and list drift.
- Propose minimal changes first, then higher-impact refactors only if needed.
- Update this file when drift is accepted as the new standard.

## Ownership
- Owner: Project maintainers.
- Last reviewed: 2026-04-21.
