from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Any

from app.api.deps import get_db
from app.models.chat_setting import ChatSetting
from app.schemas.chat_setting import ChatSettingRead, ChatSettingUpdate

router = APIRouter()

@router.get("/", response_model=ChatSettingRead)
async def get_chat_settings(db: AsyncSession = Depends(get_db)) -> Any:
    """
    Get the current chat settings. Returns default settings if none exist.
    """
    stmt = select(ChatSetting).limit(1)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    
    if not settings:
        # Create default settings if they don't exist
        settings = ChatSetting()
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    
    return settings

@router.post("/", response_model=ChatSettingRead)
async def update_chat_settings(
    settings_in: ChatSettingUpdate,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Update the current chat settings.
    """
    stmt = select(ChatSetting).limit(1)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    
    if not settings:
        settings = ChatSetting()
        db.add(settings)
    
    update_data = settings_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings, field, value)
    
    await db.commit()
    await db.refresh(settings)
    
    return settings
