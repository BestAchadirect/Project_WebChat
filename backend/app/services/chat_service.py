import json
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.schemas.chat import (
    ParsedQuery, ChatRequest, ChatResponse, ProductCard, 
    ProductSearchResult, KnowledgeSource
)
from app.models.chat import AppUser, Conversation, Message, MessageRole
from app.models.product import Product, ProductEmbedding
from app.models.knowledge import KnowledgeArticle, KnowledgeEmbedding

import openai

class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        openai.api_key = settings.OPENAI_API_KEY

    async def get_or_create_user(self, user_id: str, name: str = None, email: str = None) -> AppUser:
        """Finds or creates an AppUser."""
        stmt = select(AppUser).where(AppUser.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            user = AppUser(
                id=user_id,
                customer_name=name,
                email=email
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
        return user

    async def get_or_create_conversation(self, app_user: AppUser, conversation_id: Optional[int] = None) -> Conversation:
        """
        Gets an existing conversation by ID (if owned by user) or creates a new one.
        """
        if conversation_id:
            stmt = select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == app_user.id)
            result = await self.db.execute(stmt)
            conversation = result.scalar_one_or_none()
            if conversation:
                return conversation
        
        # Create new conversation
        conversation = Conversation(user_id=app_user.id)
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def save_message(self, conversation_id: int, role: MessageRole, content: str):
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content
        )
        self.db.add(msg)
        await self.db.commit()

    async def update_conversation_state(self, conversation: Conversation, intent: str, filters: Dict):
        """Updates the AI memory state of the conversation."""
        # Merge new state with existing (simple implementation)
        current_state = conversation.state or {}
        current_state.update({
            "last_intent": intent,
            "filters": filters
        })
        conversation.state = current_state
        self.db.add(conversation)
        await self.db.commit()

    async def get_history(self, conversation_id: int, limit: int = 5) -> List[Dict]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        msgs = result.scalars().all()
        return [{"role": m.role, "content": m.content} for m in reversed(msgs)]

    async def classify_intent(self, message: str, history: List[Dict]) -> ParsedQuery:
        system_prompt = """
        You are an e-commerce assistant. Classify the user's intent and extract filters.
        Return RAW JSON.
        Intent options: "search_products", "ask_info", "mixed", "smalltalk", "other".
        Filters: category, price_min, price_max, material, color, etc.
        Language: "en", "th", "auto".
        """
        
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-3:])
        messages.append({"role": "user", "content": message})

        try:
            response = await openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            return ParsedQuery(**data)
        except Exception as e:
            # Fallback
            print(f"Intent Error: {e}")
            return ParsedQuery(intent="other", query_text=message, language="auto")

    async def embed_text(self, text: str) -> List[float]:
        try:
            response = await openai.embeddings.create(
                model="text-embedding-3-small", 
                input=text
            )
            return response.data[0].embedding
        except Exception:
            return [] # Mock or handle error

    async def search_products(self, query_embedding: List[float], filters: Dict, limit: int = 10) -> List[ProductCard]:
        # Placeholder SQL
        sql = text("""
            SELECT p.id, p.sku, p.name, p.price, p.currency, p.image_url, p.product_url, p.attributes,
                   (pe.embedding <=> :embedding) as distance
            FROM products p
            JOIN product_embeddings pe ON p.id = pe.product_id
            ORDER BY distance ASC
            LIMIT :limit
        """)
        try:
            # In a real app, bind parameters properly
            result = await self.db.execute(sql, {"embedding": str(query_embedding), "limit": limit})
            return [] 
        except Exception as e:
            print(f"Product Search Error: {e}")
            return []

    async def search_knowledge(self, query_embedding: List[float], limit: int = 3) -> List[KnowledgeSource]:
        return []

    async def generate_response(self, parsed: ParsedQuery, products: List[ProductCard], docs: List[KnowledgeSource]) -> ChatResponse:
        return ChatResponse(
            conversation_id=0, # Placeholder, will be overwritten
            reply_text=f"I understood your intent is {parsed.intent}. (Placeholder response)", 
            intent=parsed.intent,
            product_carousel=products
        )

    async def process_chat(self, req: ChatRequest) -> ChatResponse:
        # 1. Identify/Create User
        app_user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        
        # 2. Identify/Create Conversation
        conversation = await self.get_or_create_conversation(app_user, req.conversation_id)
        
        # 3. Get History
        history = await self.get_history(conversation.id)
        
        # 4. Intent & Processing
        parsed = await self.classify_intent(req.message, history)
        
        # Update conversation state with intent memory
        await self.update_conversation_state(conversation, parsed.intent, parsed.filters)
        
        products = []
        docs = []
        
        # 5. Retrieval
        if parsed.intent in ["search_products", "mixed"]:
            emb = await self.embed_text(parsed.query_text)
            products = await self.search_products(emb, parsed.filters)
            
        if parsed.intent in ["ask_info", "mixed"]:
            emb = await self.embed_text(parsed.query_text)
            docs = await self.search_knowledge(emb)
            
        # 6. Generation
        response = await self.generate_response(parsed, products, docs)
        response.conversation_id = conversation.id
        
        # 7. Save Messages
        await self.save_message(conversation.id, MessageRole.USER, req.message)
        await self.save_message(conversation.id, MessageRole.ASSISTANT, response.reply_text)
        
        return response
