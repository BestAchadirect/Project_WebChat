from datetime import datetime, timedelta, timezone
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models.chat import Conversation, Message, MessageRole
from app.schemas.analytics import (
    ChatStatsResponse,
    ChatLogResponse,
    ChatMessageResponse,
    ChatMessageMetadata,
)


router = APIRouter()


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {value}") from exc


def _period_range(period: str) -> tuple[Optional[datetime], Optional[datetime]]:
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if period == "week":
        return now - timedelta(days=7), now
    if period == "month":
        return now - timedelta(days=30), now
    return None, None


def _build_messages(messages: List[Message]) -> List[ChatMessageResponse]:
    ordered = sorted(messages, key=lambda m: m.created_at or datetime.min.replace(tzinfo=timezone.utc))
    results: List[ChatMessageResponse] = []
    prev_role: Optional[str] = None
    prev_created: Optional[datetime] = None

    for msg in ordered:
        metadata: Optional[ChatMessageMetadata] = None
        response_time: Optional[float] = None
        if (
            prev_role == MessageRole.USER.value
            and msg.role == MessageRole.ASSISTANT.value
            and prev_created
            and msg.created_at
        ):
            response_time = (msg.created_at - prev_created).total_seconds()

        if msg.product_data or response_time is not None:
            metadata = ChatMessageMetadata(
                products=msg.product_data or None,
                responseTime=response_time,
            )

        results.append(
            ChatMessageResponse(
                id=str(msg.id),
                role=str(msg.role),
                content=msg.content,
                timestamp=msg.created_at,
                metadata=metadata,
            )
        )
        prev_role = msg.role
        prev_created = msg.created_at

    return results


def _build_chat_log(conversation: Conversation) -> ChatLogResponse:
    messages = _build_messages(conversation.messages or [])
    ended_at = messages[-1].timestamp if messages else None
    return ChatLogResponse(
        id=str(conversation.id),
        sessionId=str(conversation.id),
        userId=conversation.user_id,
        startedAt=conversation.started_at,
        endedAt=ended_at,
        messageCount=len(messages),
        userSatisfaction=None,
        messages=messages,
    )


@router.get("/stats", response_model=ChatStatsResponse)
async def get_chat_stats(
    period: Literal["today", "week", "month", "all"] = "week",
    db: AsyncSession = Depends(get_db),
) -> ChatStatsResponse:
    start, end = _period_range(period)

    chats_query = select(func.count()).select_from(Conversation)
    if start:
        chats_query = chats_query.where(Conversation.started_at >= start)
    if end:
        chats_query = chats_query.where(Conversation.started_at <= end)
    chats_result = await db.execute(chats_query)
    total_chats = int(chats_result.scalar() or 0)

    messages_query = select(func.count()).select_from(Message)
    if start:
        messages_query = messages_query.where(Message.created_at >= start)
    if end:
        messages_query = messages_query.where(Message.created_at <= end)
    messages_result = await db.execute(messages_query)
    total_messages = int(messages_result.scalar() or 0)

    prev_role = func.lag(Message.role).over(
        partition_by=Message.conversation_id,
        order_by=Message.created_at,
    )
    prev_created = func.lag(Message.created_at).over(
        partition_by=Message.conversation_id,
        order_by=Message.created_at,
    )
    response_time = case(
        (
            and_(
                Message.role == MessageRole.ASSISTANT.value,
                prev_role == MessageRole.USER.value,
            ),
            func.extract("epoch", Message.created_at - prev_created),
        ),
        else_=None,
    ).label("response_time")

    response_subquery = select(
        Message.created_at.label("created_at"),
        response_time,
    ).subquery()

    avg_query = select(func.avg(response_subquery.c.response_time))
    if start:
        avg_query = avg_query.where(response_subquery.c.created_at >= start)
    if end:
        avg_query = avg_query.where(response_subquery.c.created_at <= end)

    avg_result = await db.execute(avg_query)
    avg_response_time = float(avg_result.scalar() or 0.0)

    return ChatStatsResponse(
        totalChats=total_chats,
        totalMessages=total_messages,
        avgResponseTime=avg_response_time,
        userSatisfaction=0.0,
        period=period,
    )


@router.get("/logs", response_model=List[ChatLogResponse])
async def list_chat_logs(
    start_date: Optional[str] = Query(None, alias="startDate"),
    end_date: Optional[str] = Query(None, alias="endDate"),
    min_satisfaction: Optional[float] = Query(None, alias="minSatisfaction"),
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> List[ChatLogResponse]:
    start = _parse_datetime(start_date)
    end = _parse_datetime(end_date)

    query = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .order_by(desc(Conversation.started_at))
        .offset(offset)
        .limit(limit)
    )
    if start:
        query = query.where(Conversation.started_at >= start)
    if end:
        query = query.where(Conversation.started_at <= end)

    if min_satisfaction is not None:
        # Satisfaction is not captured yet; keep the filter here for forward compatibility.
        pass

    result = await db.execute(query)
    conversations = result.scalars().all()
    return [_build_chat_log(conv) for conv in conversations]


@router.get("/logs/{session_id}", response_model=ChatLogResponse)
async def get_chat_log_details(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> ChatLogResponse:
    try:
        conversation_id = int(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid session id") from exc

    query = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    result = await db.execute(query)
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return _build_chat_log(conversation)
