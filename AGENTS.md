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
- Keep current root tooling in place: `package.json`, `tsconfig*.json`, `tailwind.config.js`, `postcss.config.js`.
- Do not relocate root tooling unless the repo is intentionally migrated to an explicit workspace model.

## Placement Rules
- Backend HTTP routes: `backend/app/api/routes/`.
- Backend business logic: `backend/app/services/`.
- Backend service domain split:
  `backend/app/services/ai`, `backend/app/services/chat`, `backend/app/services/catalog`,
  `backend/app/services/knowledge`, `backend/app/services/imports`,
  `backend/app/services/tasks`, `backend/app/services/tickets`, `backend/app/services/legacy`.
- Keep compatibility wrappers in `backend/app/services/*.py` during deprecation window; new code must import domain paths.
- Backend schemas/models: `backend/app/schemas/` and `backend/app/models/`.
- Backend shared internals: `backend/app/core/`, `backend/app/utils/`, `backend/app/db/`.
- Backend prompts: `backend/app/prompts/`.
- Frontend reusable UI: `frontend-admin/src/components/`.
- Frontend route pages: `frontend-admin/src/routes/`.
- Frontend API clients: `frontend-admin/src/api/`.
- Frontend hooks/types/utils: `frontend-admin/src/hooks/`, `frontend-admin/src/types/`, `frontend-admin/src/utils/`.
- Shared contracts: `shared/types/`.
- Deployment and local infra scripts: `infra/`.
- Architecture and runbooks: `docs/`.

## Test Location Policy
- New backend unit and service tests should go in `backend/tests/`.
- Cross-service and end-to-end tests should go in `tests/`.
- Existing files may remain in place during cleanup, but new tests must follow the rule above.

## Naming Conventions
- Use kebab-case for folders and file names unless framework conventions require otherwise.
- Use PascalCase for React component files.
- Use `.test` or `.spec` suffix for test files.
- Keep config files at the nearest relevant scope.

## Runtime and Generated Artifacts (Never Commit)
- `backend/.venv/`
- `backend/venv/`
- `backend/__pycache__/`
- `backend/.tmp_pyc/`
- `backend/pytest-cache-files-*/`
- `backend/uploads/`
- `backend/logs/`
- `frontend-admin/node_modules/`
- `frontend-admin/dist/`

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
- Last reviewed: 2026-02-23.
