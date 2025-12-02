from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.tenant import Tenant
from app.core.logging import get_logger

logger = get_logger(__name__)

class TenantService:
    """Service for tenant management."""
    
    async def create_tenant(
        self,
        db: AsyncSession,
        name: str,
        magento_base_url: Optional[str] = None,
        magento_access_token: Optional[str] = None
    ) -> Tenant:
        """Create a new tenant."""
        tenant = Tenant(
            name=name,
            magento_base_url=magento_base_url,
            magento_access_token=magento_access_token  # TODO: Encrypt this
        )
        
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)
        
        logger.info(f"Created tenant: {tenant.id} - {tenant.name}")
        return tenant
    
    async def get_tenant(
        self,
        db: AsyncSession,
        tenant_id: UUID
    ) -> Optional[Tenant]:
        """Get tenant by ID."""
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def update_tenant(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        **kwargs
    ) -> Optional[Tenant]:
        """Update tenant."""
        tenant = await self.get_tenant(db, tenant_id)
        if not tenant:
            return None
        
        for key, value in kwargs.items():
            if hasattr(tenant, key) and value is not None:
                setattr(tenant, key, value)
        
        await db.commit()
        await db.refresh(tenant)
        
        return tenant

# Singleton instance
tenant_service = TenantService()
