# Agent.md

## Purpose
This file defines the canonical project structure and rules for where new files should go.
All structure changes must align with this document.

## How to use this file (for humans + AI)
When asked to analyze or manage the directory structure:
1) Summarize the current top-level layout (exclude `node_modules`, `.git`, `venv`, `__pycache__`, `uploads`, `logs`).
2) Compare against this file and call out drift or inconsistencies.
3) Suggest minimal changes with clear benefits and risks.
4) If any structural change is proposed, update this file and explain why.

Do not move or rename folders unless explicitly requested.

## Top-level layout (authoritative)
- backend/ : FastAPI backend, data access, RAG, integrations.
- frontend-admin/ : React + Vite admin UI and embedded widget build.
- shared/ : shared types/utilities used by both frontend and backend.
- docs/ : architecture notes, ADRs, and developer guides.
- infra/ : deployment scripts and infrastructure config.
- tests/ : cross-service and end-to-end tests.

Root files (kept at repo root):
- `.env`, `.env.example` : repo-wide defaults (no secrets committed).
- `README.md`, `Agent.md` : overview + structure rules.
- `dev.ps1` : local dev launcher.
- `package.json`, `tsconfig*.json`, `tailwind.config.js`, `postcss.config.js` : root tooling/config (do not move unless the repo is converted to a workspace or single-app layout).

## Backend structure (backend/)
- app/
  - api/routes/ : HTTP endpoints.
  - core/ : config, logging, auth, settings.
  - models/ : SQLAlchemy models.
  - schemas/ : Pydantic request/response models.
  - services/ : business logic, orchestration, integrations.
  - prompts/ : system/user prompts for LLM workflows.
  - utils/ : small utilities/helpers.
  - static/ : built assets (widget build output).
- alembic/ : database migrations.
- scripts/ : ad-hoc utilities and maintenance scripts.
- sql/ : legacy/manual migration SQL (if needed).
- uploads/ : runtime files (do not commit).
- logs/ : runtime logs (do not commit).
- agents/ : internal instructions/automation notes.
- venv/ : local Python env (do not commit).

## Frontend structure (frontend-admin/)
- src/
  - components/ : reusable UI components.
  - routes/ : route-level screens.
  - api/ : API clients and request helpers.
  - state/ : shared state stores.
- public/ : static assets.
- vite.config.ts, tailwind.config.js, etc. : frontend toolchain config.
- node_modules/ : local deps (do not commit).

## Shared structure (shared/)
- types/ : shared TypeScript types and interfaces.
- utils/ : cross-app helpers without app-specific dependencies.

## Tests structure (tests/)
- e2e/ : end-to-end tests.
- integration/ : cross-service tests.
- fixtures/ : test data and mocks.

## Docs structure (docs/)
- adr/ : architecture decision records.
- runbooks/ : ops/support guides.
- diagrams/ : architecture diagrams and exports.

## Infra structure (infra/)
- deploy/ : deployment scripts and pipelines.
- env/ : environment templates and secrets guidance.
- terraform/ : terraform modules/stacks (if used).

## Naming conventions
- Use kebab-case for folders and file names unless the framework requires otherwise.
- Use PascalCase for React components and their files.
- Use `.test` or `.spec` suffix for test files.
- Keep config at the nearest relevant scope (app or service).

## Rules for adding new top-level folders
- Only add a new top-level folder if there is a clear, non-overlapping purpose.
- Update this file with the purpose and ownership.
- Prefer extending existing folders first.

## Generated / runtime folders (do not edit)
- backend/venv/
- backend/__pycache__/
- backend/uploads/
- backend/logs/
- frontend-admin/node_modules/
- frontend-admin/dist/ (if present)
