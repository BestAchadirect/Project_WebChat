from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.dependencies import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.models.tenant import Tenant
from app.core.exceptions import AuthenticationException

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Dependency to get current authenticated user from JWT token.
    """
    token = credentials.credentials
    payload = decode_access_token(token)
    
    if payload is None:
        raise AuthenticationException("Invalid authentication credentials")
    
    email: str = payload.get("sub")
    if email is None:
        raise AuthenticationException("Invalid token payload")
    
    # Get user from database
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user is None:
        raise AuthenticationException("User not found")
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    
    return user

async def get_current_tenant(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Tenant:
    """
    Dependency to get current user's tenant.
    """
    stmt = select(Tenant).where(Tenant.id == current_user.tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()
    
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    
    return tenant
