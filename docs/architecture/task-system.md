# Task System

## Purpose
Document how long-running backend operations are tracked and exposed through the current task model and APIs.

## Context
Task records are used by import and maintenance workflows to persist execution state, progress, and error details.

## Content

### Data Model

Source: `backend/app/models/task.py`

- Status enum: `pending`, `running`, `completed`, `failed`, `cancelled`.
- Type enum: `document_processing`, `data_import`, `embedding_generation`, `product_update`.
- Core fields:
  - `id` (UUID)
  - `task_type`
  - `status`
  - `description`
  - `created_at`, `started_at`, `completed_at`
  - `error_message`
  - `progress` (0-100)
  - `task_metadata` (JSON serialized string)

### API Endpoints

Source: `backend/app/api/routes/tasks.py`

- `GET /api/v1/tasks/`
  - Currently returns an empty list placeholder.
  - `skip` and `limit` parameters exist, but listing logic is not implemented.
- `GET /api/v1/tasks/{task_id}`
  - Returns task details by ID.
  - Returns `404` when no task exists for the ID.

### Service Behavior

Source: `backend/app/services/tasks/service.py`

- `create_task`: creates a task row and initializes metadata.
- `update_task_status`: updates lifecycle fields and optional progress/error.
- `run_task_background`: wraps execution in FastAPI `BackgroundTasks`.
- `run_task_immediate`: creates and executes a task inline with status transitions.

### Known Gaps

- No implemented list/query endpoint for persisted tasks.
- No task cancellation API exposed by route/service contract.
- No documented retention job for old completed/failed task rows.

## Related Files

- `backend/app/models/task.py`
- `backend/app/api/routes/tasks.py`
- `backend/app/services/tasks/service.py`
- `docs/database-tables.md`
