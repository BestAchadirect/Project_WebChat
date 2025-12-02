from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID

# Auth Schemas
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    email: Optional[str] = None
    tenant_id: Optional[UUID] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

# User Schemas
class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None

class UserCreate(UserBase):
    password: str
    tenant_id: UUID

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = None

class UserResponse(UserBase):
    id: UUID
    tenant_id: UUID
    is_active: bool
    is_superuser: bool
    created_at: datetime
    
    class Config:
        from_attributes = True
