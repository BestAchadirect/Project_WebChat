from typing import Any, Dict, Optional, Callable, Awaitable
from uuid import UUID
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.sql import func
from fastapi import BackgroundTasks

from app.models.task import Task, TaskStatus, TaskType
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal

logger = get_logger(__name__)

class TaskService:
    """Reusable task service for managing background tasks."""

    def __init__(self):
        self._background_tasks = None

    def set_background_tasks(self, background_tasks: BackgroundTasks):
        """Set the FastAPI BackgroundTasks instance."""
        self._background_tasks = background_tasks

    async def create_task(
        self,
        db: AsyncSession,
        task_type: TaskType,
        description: str = None,
        metadata: Dict[str, Any] = None
    ) -> Task:
        """Create a new task record."""
        task = Task(
            task_type=task_type,
            description=description,
            # Ensure any non-JSON-native types (e.g., UUID) are serialized safely
            task_metadata=json.dumps(metadata, default=str) if metadata else None
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    async def get_task(self, db: AsyncSession, task_id: UUID) -> Optional[Task]:
        """Get a task by ID."""
        stmt = select(Task).where(Task.id == task_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_task_status(
        self,
        db: AsyncSession,
        task_id: UUID,
        status: TaskStatus,
        error_message: str = None,
        progress: int = None
    ) -> None:
        """Update task status."""
        update_data = {"status": status}

        if status == TaskStatus.RUNNING:
            update_data["started_at"] = func.now()
        elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            update_data["completed_at"] = func.now()

        if error_message:
            update_data["error_message"] = error_message

        if progress is not None:
            update_data["progress"] = progress

        stmt = update(Task).where(Task.id == task_id).values(**update_data)
        await db.execute(stmt)
        await db.commit()

    async def run_task_background(
        self,
        task_id: UUID,
        task_func: Callable[[UUID], Awaitable[None]],
        description: str = None
    ) -> None:
        """
        Run a task function in the background.

        Args:
            task_id: The task ID
            task_func: Async function that takes task_id and performs the work
            description: Optional description for the task
        """
        if not self._background_tasks:
            raise ValueError("BackgroundTasks not set. Call set_background_tasks() first.")

        self._background_tasks.add_task(self._execute_task, task_id, task_func)

    async def _execute_task(
        self,
        task_id: UUID,
        task_func: Callable[[UUID], Awaitable[None]]
    ) -> None:
        """Internal method to execute a task with proper error handling."""
        async with AsyncSessionLocal() as db:
            try:
                # Update status to running
                await self.update_task_status(db, task_id, TaskStatus.RUNNING)

                # Execute the task function
                await task_func(task_id)

                # Update status to completed
                await self.update_task_status(db, task_id, TaskStatus.COMPLETED, progress=100)

                logger.info(f"Task {task_id} completed successfully")

            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}")
                await self.update_task_status(
                    db, task_id, TaskStatus.FAILED, error_message=str(e)
                )

    async def run_task_immediate(
        self,
        db: AsyncSession,
        task_type: TaskType,
        task_func: Callable[[AsyncSession, UUID], Awaitable[None]],
        description: str = None,
        metadata: Dict[str, Any] = None
    ) -> Task:
        """
        Create and run a task immediately (not in background).

        Args:
            db: Database session
            task_type: Type of task
            task_func: Function to execute (takes db and task_id)
            description: Task description
            metadata: Additional metadata

        Returns:
            The created task
        """
        # Create task record
        task = await self.create_task(db, task_type, description, metadata)

        try:
            # Update to running
            await self.update_task_status(db, task.id, TaskStatus.RUNNING)

            # Execute function
            await task_func(db, task.id)

            # Complete
            await self.update_task_status(db, task.id, TaskStatus.COMPLETED, progress=100)

        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            await self.update_task_status(db, task.id, TaskStatus.FAILED, error_message=str(e))

        return task

# Global instance
task_service = TaskService()
