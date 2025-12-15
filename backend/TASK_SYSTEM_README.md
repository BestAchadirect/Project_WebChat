# Reusable Task System

This backend now includes a reusable task system for managing background operations like document processing, data imports, and embedding generation.

## Features

- **Task Tracking**: All background operations are tracked with status, progress, and metadata
- **Progress Monitoring**: Tasks report progress from 0-100%
- **Error Handling**: Failed tasks include error messages
- **Background Execution**: Uses FastAPI BackgroundTasks for non-blocking operations
- **Database Persistence**: Tasks are stored in PostgreSQL with full history

## Task Types

- `DOCUMENT_PROCESSING`: Processing uploaded documents (text extraction, chunking, embeddings)
- `DATA_IMPORT`: Importing data from CSV files
- `EMBEDDING_GENERATION`: Generating embeddings for products/knowledge
- `PRODUCT_UPDATE`: Updating product information

## API Endpoints

### Get All Tasks
```
GET /api/v1/tasks/
```
Returns a list of tasks (pagination support planned)

### Get Task by ID
```
GET /api/v1/tasks/{task_id}
```
Returns detailed information about a specific task

## Usage Examples

### Document Upload (Automatic)
When uploading documents via `/api/v1/documents/upload`, a background task is automatically created for processing.

### Data Import (Automatic)
When importing products via `/api/v1/import/products`, embeddings are generated in a background task.

### Manual Task Creation
```python
from app.services.task_service import task_service
from app.models.task import TaskType

# Create a task
task = await task_service.create_task(
    db,
    TaskType.DOCUMENT_PROCESSING,
    "Processing document XYZ",
    {"document_id": "123"}
)

# Run in background
task_service.set_background_tasks(background_tasks)
await task_service.run_task_background(
    task.id,
    my_processing_function
)
```

## Task Status Flow

1. `PENDING` → `RUNNING` → `COMPLETED`
2. `PENDING` → `RUNNING` → `FAILED`
3. `PENDING` → `CANCELLED`

## Database Schema

The `tasks` table includes:
- `id`: UUID primary key
- `task_type`: Enum (DOCUMENT_PROCESSING, etc.)
- `status`: Enum (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED)
- `description`: Human-readable description
- `created_at`, `started_at`, `completed_at`: Timestamps
- `error_message`: Error details if failed
- `progress`: Integer 0-100
- `task_metadata`: JSON string for additional data

## Future Enhancements

- Task cancellation
- Task prioritization
- Bulk task operations
- Task dependencies
- Admin UI for task monitoring