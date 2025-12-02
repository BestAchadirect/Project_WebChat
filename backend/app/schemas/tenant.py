from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID

# Tenant Schemas
class TenantBase(BaseModel):
    name: str

class TenantCreate(TenantBase):
    magento_base_url: Optional[str] = None
    magento_access_token: Optional[str] = None

class TenantUpdate(BaseModel):
    name: Optional[str] = None
    magento_base_url: Optional[str] = None
    magento_access_token: Optional[str] = None

class TenantResponse(TenantBase):
    id: UUID
    magento_base_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
