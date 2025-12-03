from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional

from app.db.session import get_db
from app.models.embedding import Embedding
from app.services.embedding import EmbeddingService
from openai import AsyncOpenAI
from app.core.config import settings

router = APIRouter()
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

from app.models.chat_session import ChatSession
from app.models.message import Message, MessageRole
import uuid

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[uuid.UUID] = None
    tenant_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    sources: List[str]
    session_id: uuid.UUID

@router.post("/message", response_model=ChatResponse)
async def chat_message(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db)
):
    print(f"💬 Chat request received: {request.message}")
    try:
        # 1. Get or Create Session
        session_id = request.session_id
        print(f"🔍 Session ID from request: {session_id}")
        if not session_id:
            # Create new session
            # Get tenant
            tenant_id = request.tenant_id
            print(f"🔍 Tenant ID from request: {tenant_id}")
            
            if not tenant_id:
                # Default tenant logic
                from app.models.tenant import Tenant
                print("🔍 No tenant_id provided, looking for default...")
                result = await db.execute(select(Tenant).where(Tenant.name == "Default Tenant"))
                tenant = result.scalars().first()
                if not tenant:
                    print("⚠️ Default tenant not found, creating...")
                    tenant = Tenant(name="Default Tenant")
                    db.add(tenant)
                    await db.flush()
                tenant_id = tenant.id
            else:
                # Check if tenant_id is a valid UUID
                try:
                    uuid_obj = uuid.UUID(str(tenant_id))
                    tenant_id = uuid_obj
                except ValueError:
                    # It's not a UUID, treat as name
                    print(f"⚠️ tenant_id '{tenant_id}' is not a UUID, treating as name...")
                    from app.models.tenant import Tenant
                    result = await db.execute(select(Tenant).where(Tenant.name == str(tenant_id)))
                    tenant = result.scalars().first()
                    if not tenant:
                        print(f"⚠️ Tenant '{tenant_id}' not found, creating...")
                        tenant = Tenant(name=str(tenant_id))
                        db.add(tenant)
                        await db.flush()
                    tenant_id = tenant.id
            
            print(f"✅ Using tenant ID: {tenant_id}")
            
            new_session = ChatSession(
                tenant_id=tenant_id,
                session_id=str(uuid.uuid4()),
                user_identifier="anonymous"
            )
            db.add(new_session)
            await db.flush()
            session_id = new_session.id
            print(f"✅ Created new session: {session_id}")
        else:
            # Verify session exists
            print(f"🔍 Verifying session: {session_id}")
            result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
            if not result.scalar_one_or_none():
                print("❌ Session not found")
                raise HTTPException(status_code=404, detail="Session not found")

        # 2. Save User Message
        user_msg = Message(
            chat_session_id=session_id,
            role=MessageRole.USER,
            content=request.message
        )
        db.add(user_msg)
        
        # 3. Embed query
        print("🧠 Generating embedding...")
        query_vector = await EmbeddingService.get_embedding(request.message)
        
        # 4. Search similar chunks
        print("🔍 Searching vector store...")
        chunks = await db.execute(
            select(Embedding)
            .order_by(Embedding.embedding.cosine_distance(query_vector))
            .limit(5)
        )
        relevant_chunks = chunks.scalars().all()
        print(f"✅ Found {len(relevant_chunks)} chunks")
        
        context = "\n\n".join([c.chunk_text for c in relevant_chunks])
        
        # 5. Call LLM
        print("🤖 Calling LLM...")
        system_prompt = f"""You are a helpful assistant for a Magento store.
Use the following context to answer the user's question.
If the answer is not in the context, say you don't know or try to be helpful based on general knowledge but mention it's not in the docs.

Context:
{context}
"""
        
        completion = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.message}
            ]
        )
        
        response_text = completion.choices[0].message.content
        print("✅ LLM response received")
        
        # 6. Save Assistant Message
        asst_msg = Message(
            chat_session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=response_text,
            message_metadata=str([str(c.document_id) for c in relevant_chunks]) # Store sources in metadata
        )
        db.add(asst_msg)
        await db.commit()
        
        return ChatResponse(
            response=response_text,
            sources=[str(c.document_id) for c in relevant_chunks],
            session_id=session_id
        )
    except Exception as e:
        print(f"❌ Error in chat_message: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
