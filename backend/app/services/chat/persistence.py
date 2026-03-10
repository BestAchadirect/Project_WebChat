from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select, update

from app.core.logging import get_logger
from app.models.chat import Conversation, Message, MessageRole
from app.models.qa_log import QALog, QAStatus
from app.schemas.chat import ChatComponent, ChatResponse, ProductCard
from app.services.chat import qa_metrics

logger = get_logger(__name__)


async def save_message(
    *,
    db,
    conversation_id: int,
    role: str,
    content: str,
    product_data: List[ProductCard] | None = None,
    components: List[ChatComponent] | List[Dict[str, Any]] | None = None,
    token_usage: Dict[str, Any] | None = None,
    commit: bool = True,
    touch_conversation: bool = True,
) -> Message:
    if product_data:
        data_json = []
        for p in product_data:
            d = p.dict()
            if "id" in d and d["id"]:
                d["id"] = str(d["id"])
            data_json.append(d)
    else:
        data_json = None

    components_json: List[Dict[str, Any]] | None = None
    if components:
        components_json = []
        for component in components:
            if isinstance(component, ChatComponent):
                components_json.append(component.model_dump(mode="json"))
            elif isinstance(component, dict):
                components_json.append(dict(component))

    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        product_data=data_json,
        components=components_json,
        token_usage=token_usage,
    )
    db.add(msg)
    if touch_conversation:
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(last_message_at=func.now())
        )
    if commit:
        await db.commit()
    return msg


async def finalize_response(
    *,
    db,
    conversation_id: int,
    user_text: str,
    response: ChatResponse,
    token_usage: Optional[Dict[str, Any]] = None,
    channel: Optional[str] = None,
    conversation_state: Optional[Dict[str, Any]] = None,
) -> ChatResponse:
    chat_metrics = qa_metrics.build_chat_qa_metrics(
        user_text=user_text,
        response=response,
        channel=channel,
    )
    qa_status = QAStatus.SUCCESS
    if chat_metrics.get("status") == "fallback":
        qa_status = QAStatus.FALLBACK
    elif chat_metrics.get("status") == "no_answer":
        qa_status = QAStatus.NO_ANSWER
    elif chat_metrics.get("status") == "failed":
        qa_status = QAStatus.FAILED

    token_usage_payload = qa_metrics.merge_token_usage_with_metrics(
        token_usage=token_usage,
        chat_metrics=chat_metrics,
    )

    qa_log = QALog(
        question=user_text,
        answer=response.reply_text,
        sources=[
            {
                "source_id": s.source_id,
                "chunk_id": s.chunk_id,
                "title": s.title,
                "relevance": s.relevance,
            }
            for s in response.sources
        ],
        status=qa_status,
        token_usage=token_usage_payload,
        channel=channel,
    )
    qa_log_id: Optional[str] = None

    try:
        await save_message(
            db=db,
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=user_text,
            commit=False,
            touch_conversation=False,
        )
        await save_message(
            db=db,
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=response.reply_text,
            product_data=response.product_carousel,
            components=response.components,
            token_usage=token_usage_payload,
            commit=False,
            touch_conversation=False,
        )
        conversation_update = {"last_message_at": func.now()}
        if conversation_state is not None:
            conversation_update["state"] = dict(conversation_state)
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(**conversation_update)
        )
        await db.flush()

        try:
            async with db.begin_nested():
                db.add(qa_log)
                await db.flush()
                if qa_log.id:
                    qa_log_id = str(qa_log.id)
        except Exception as e:
            logger.error(f"Failed to log QA event: {e}")

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    response.qa_log_id = qa_log_id
    return response


async def submit_feedback(*, db, qa_log_id: UUID, feedback: int) -> Optional[QALog]:
    stmt = select(QALog).where(QALog.id == qa_log_id)
    result = await db.execute(stmt)
    qa_log = result.scalar_one_or_none()
    if qa_log is None:
        return None
    if feedback not in (-1, 1):
        raise ValueError("feedback must be -1 or 1")
    qa_log.user_feedback = int(feedback)
    qa_log.feedback_at = datetime.utcnow()
    db.add(qa_log)
    await db.commit()
    await db.refresh(qa_log)
    return qa_log


async def get_history(*, db, conversation_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    if not hasattr(db, "execute"):
        return []
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    msgs = result.scalars().all()
    return [
        {
            "role": m.role,
            "content": m.content,
            "product_data": m.product_data,
            "components": m.components,
            "created_at": m.created_at,
        } for m in reversed(msgs)
    ]
