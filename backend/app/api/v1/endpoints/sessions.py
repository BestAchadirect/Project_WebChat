from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional
import uuid

from app.db.session import get_db
from app.models.chat_session import ChatSession
from app.models.message import Message, MessageRole
from app.models.tenant import Tenant

router = APIRouter()

class SessionCreate(BaseModel):
    user_identifier: Optional[str] = None
    tenant_id: Optional[str] = None # For MVP, we might infer or pass it

class SessionResponse(BaseModel):
    id: uuid.UUID
    session_id: str
    user_identifier: Optional[str]
    created_at: str

    class Config:
        from_attributes = True

@router.post("/", response_model=SessionResponse)
async def create_session(
    session_in: SessionCreate,
    db: AsyncSession = Depends(get_db)
):
    # Get default tenant if not provided (MVP hack)
    tenant_id = session_in.tenant_id
    if not tenant_id:
        result = await db.execute(select(Tenant))
        tenant = result.scalars().first()
        if not tenant:
            # Create default tenant if none exists
            tenant = Tenant(name="Default Tenant")
            db.add(tenant)
            await db.flush()
        tenant_id = tenant.id
    
    # Generate a friendly session ID if needed, or just use UUID
    # The model has session_id as String. Let's use UUID string.
    session_uid = str(uuid.uuid4())
    
    db_session = ChatSession(
        tenant_id=tenant_id,
        session_id=session_uid,
        user_identifier=session_in.user_identifier
    )
    db.add(db_session)
    await db.commit()
    await db.refresh(db_session)
    
    return SessionResponse(
        id=db_session.id,
        session_id=db_session.session_id,
        user_identifier=db_session.user_identifier,
        created_at=db_session.created_at.isoformat()
    )

@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return SessionResponse(
        id=session.id,
        session_id=session.session_id,
        user_identifier=session.user_identifier,
        created_at=session.created_at.isoformat()
    )

class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: str

    class Config:
        from_attributes = True

@router.get("/{session_id}/messages", response_model=List[MessageResponse])
async def get_session_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    # Verify session exists
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    result = await db.execute(
        select(Message)
        .where(Message.chat_session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    
    return [
        MessageResponse(
            id=m.id,
            role=m.role.value,
            content=m.content,
            created_at=m.created_at.isoformat()
        ) for m in messages
    ]
