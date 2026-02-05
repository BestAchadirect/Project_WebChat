# Agent.md

## Purpose
This document defines how the project should be organized and where new files should go. Keep changes consistent with this structure unless there is a clear reason to add a new top-level folder.

## Top-level layout
- backend/ : server-side services, APIs, and business logic.
- frontend-admin/ : admin web UI and client-side assets.
- shared/ : code and types shared across backend and frontend.
- docs/ : architecture notes, ADRs, and developer guides.
- infra/ : infrastructure-as-code, deployment scripts, and environment configs.
- tests/ : end-to-end and cross-service tests.

## Folder responsibilities
- backend/
  - services/ : domain services, orchestration, and workflows.
  - api/ : HTTP routes, controllers, and request validation.
  - data/ : data access, repositories, and migrations.
  - config/ : environment and runtime configuration.
  - jobs/ : background workers and scheduled tasks.
  - integrations/ : third-party clients and adapters.

- frontend-admin/
  - src/ : application code.
  - src/components/ : reusable UI components.
  - src/pages/ : route-level screens.
  - src/state/ : app state management.
  - src/api/ : API clients and request helpers.
  - public/ : static assets.

- shared/
  - types/ : shared TypeScript types and interfaces.
  - utils/ : shared helpers with no app-specific dependencies.

- tests/
  - e2e/ : end-to-end tests.
  - integration/ : cross-service tests.
  - fixtures/ : test data and mocks.

- docs/
  - adr/ : architecture decision records.
  - runbooks/ : operational guides.
  - diagrams/ : architecture diagrams and exports.

- infra/
  - deploy/ : deployment scripts and pipelines.
  - env/ : environment templates and secrets guidance.
  - terraform/ : terraform modules and stacks (if used).

## Naming conventions
- Use kebab-case for folders and file names unless the framework requires otherwise.
- Use PascalCase for React components and their files.
- Use .test or .spec suffix for test files.
- Keep config at the nearest relevant scope (app or service).

## Adding new top-level folders
Before adding a new top-level folder, update this file to explain the purpose and ownership. Prefer extending existing folders first.
