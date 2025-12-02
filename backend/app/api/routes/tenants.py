from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List

from app.dependencies import get_db
from app.api.deps import get_current_user
from app.schemas.tenant import TenantCreate, TenantUpdate, TenantResponse
from app.services.tenant_service import tenant_service
from app.models.user import User
from app.core.exceptions import TenantNotFoundException

router = APIRouter()

@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    request: TenantCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new tenant.
    """
    tenant = await tenant_service.create_tenant(
        db=db,
        name=request.name,
        magento_base_url=request.magento_base_url,
        magento_access_token=request.magento_access_token
    )
    
    return tenant

@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get tenant by ID.
    """
    # Check if user belongs to this tenant
    if current_user.tenant_id != tenant_id and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this tenant"
        )
    
    tenant = await tenant_service.get_tenant(db, tenant_id)
    
    if not tenant:
        raise TenantNotFoundException(str(tenant_id))
    
    return tenant

@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: UUID,
    request: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update tenant configuration.
    """
    # Check if user belongs to this tenant
    if current_user.tenant_id != tenant_id and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this tenant"
        )
    
    tenant = await tenant_service.update_tenant(
        db=db,
        tenant_id=tenant_id,
        **request.dict(exclude_unset=True)
    )
    
    if not tenant:
        raise TenantNotFoundException(str(tenant_id))
    
    return tenant
