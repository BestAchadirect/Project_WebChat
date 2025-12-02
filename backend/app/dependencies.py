from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for database session."""
    async with AsyncSessionLocal() as session:
        yield session

async def get_tenant_id(tenant_id: str) -> str:
    """
    Dependency to extract and validate tenant_id.
    In production, this might come from JWT claims or headers.
    """
    # TODO: Add validation logic
    return tenant_id
