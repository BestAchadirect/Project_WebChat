# Task System (Backend)

This document describes the background task model and current API behavior.

## Purpose

Track long-running backend operations (for example imports or embedding generation) with status, progress, and metadata.

## Data Model

Source: `backend/app/models/task.py`

- `TaskStatus`: `pending`, `running`, `completed`, `failed`, `cancelled`
- `TaskType`: `document_processing`, `data_import`, `embedding_generation`, `product_update`
- Core fields:
  - `id` (UUID)
  - `task_type`
  - `status`
  - `description`
  - `created_at`, `started_at`, `completed_at`
  - `error_message`
  - `progress` (0-100)
  - `task_metadata` (JSON string)

## API Endpoints

Source: `backend/app/api/routes/tasks.py`

- `GET /api/v1/tasks/`
  - Current behavior: returns an empty list placeholder.
  - Note: pagination/listing logic is not implemented yet.
- `GET /api/v1/tasks/{task_id}`
  - Returns task detail by ID.
  - Returns `404` if not found.

## Service Usage Pattern

Source: `backend/app/services/task_service.py`

Typical flow:
1. Create task.
2. Mark task as running.
3. Execute background work.
4. Update progress and final status.

## Current Limitations

- No list endpoint persistence output yet (`GET /api/v1/tasks/` placeholder).
- No cancellation API.
- No prioritization/dependencies.

## Next Steps (Suggested)

1. Implement `GET /api/v1/tasks/` with pagination and filters.
2. Add cancellation support for eligible tasks.
3. Add retention/cleanup policy for old completed tasks.
