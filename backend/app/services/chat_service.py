import json
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, text
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.schemas.chat import (
    ParsedQuery, ChatRequest, ChatResponse, ProductCard, 
    ProductSearchResult, KnowledgeSource
)
from app.models.chat import AppUser, Conversation, Message, MessageRole
from app.models.product import Product, ProductEmbedding
from app.models.knowledge import KnowledgeArticle, KnowledgeEmbedding

from openai import AsyncOpenAI

class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

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
            response = await self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            parsed = ParsedQuery(**data)
        except Exception as e:
            # Fallback
            print(f"Intent Error: {e}")
            parsed = ParsedQuery(intent="other", query_text=message, language="auto")

        # Simple keyword heuristic to force ask_info intent for FAQ-style questions
        if parsed.intent == "other":
            lowered = message.lower()
            faq_keywords = ["policy", "shipping", "return", "warranty", "faq", "information", "hours", "support"]
            if any(keyword in lowered for keyword in faq_keywords):
                parsed.intent = "ask_info"

        return parsed

    async def embed_text(self, text: str) -> List[float]:
        try:
            response = await self.openai_client.embeddings.create(
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

    async def search_knowledge(self, query_text: str, query_embedding: List[float], limit: int = 5) -> List[KnowledgeSource]:
        """
        Search knowledge base for relevant articles using vector similarity.
        Returns top matching knowledge sources ranked by relevance.
        """
        if not query_embedding:
            return []
        try:
            # Query knowledge embeddings using cosine distance
            stmt = (
                select(
                    KnowledgeEmbedding,
                    KnowledgeArticle,
                    KnowledgeEmbedding.embedding.cosine_distance(query_embedding).label("distance")
                )
                .join(KnowledgeArticle, KnowledgeEmbedding.article_id == KnowledgeArticle.id)
                .order_by("distance")
                .limit(limit)
            )
            
            result = await self.db.execute(stmt)
            rows = result.all()
            
            sources = []
            for embedding, article, distance in rows:
                similarity = 1 - distance  # Convert distance to similarity (0-1)

                if similarity >= 0.3:  # Looser relevance threshold
                    sources.append(
                        KnowledgeSource(
                            source_id=str(article.id),
                            title=article.title,
                            content_snippet=getattr(embedding, 'chunk_text', article.content[:500]),
                            category=article.category,
                            relevance=float(similarity),
                            url=article.url or ""
                        )
                    )

            if not sources:
                # Simple keyword fallback search
                stmt = (
                    select(KnowledgeArticle)
                    .where(
                        or_(
                            KnowledgeArticle.title.ilike(f"%{query_text}%"),
                            KnowledgeArticle.content.ilike(f"%{query_text}%"),
                        )
                    )
                    .limit(limit)
                )
                fallback_articles = (await self.db.execute(stmt)).scalars().all()
                for article in fallback_articles:
                    sources.append(
                        KnowledgeSource(
                            source_id=str(article.id),
                            title=article.title,
                            content_snippet=article.content[:500],
                            category=article.category,
                            relevance=0.2,
                            url=article.url or ""
                        )
                    )

            return sources
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return []

    async def generate_response(self, parsed: ParsedQuery, products: List[ProductCard], docs: List[KnowledgeSource]) -> ChatResponse:
        """
        Generate AI response based on intent, retrieved products, and knowledge sources.
        Synthesizes multiple sources into a coherent answer.
        """
        reply_text = ""
        
        # Handle "other" intent - ask for clarification
        if parsed.intent == "other":
            reply_text = "I'm not sure I understand your question. Could you please rephrase it or provide more details? For example, you could ask about our products, minimum order, or company policies."
        
        # Handle "smalltalk" intent
        elif parsed.intent == "smalltalk":
            reply_text = "Thank you for reaching out! I'm here to help with any questions about our products, policies, or services. What would you like to know?"
        
        # Handle "ask_info" (FAQ/Knowledge base) intent
        elif parsed.intent == "ask_info":
            if docs:
                # Synthesize knowledge sources into a response
                reply_text = await self._synthesize_knowledge_response(parsed.query_text, docs)
            else:
                reply_text = "I don't have information about that topic in my knowledge base. Could you try asking something else or rephrase your question?"
        
        # Handle "search_products" intent
        elif parsed.intent == "search_products":
            if products:
                reply_text = f"I found {len(products)} product(s) that match your search. Here are the best matches:"
            else:
                reply_text = "I couldn't find any products matching your search. Could you try different keywords?"
        
        # Handle "mixed" intent (both products and info)
        elif parsed.intent == "mixed":
            parts = []
            if docs:
                knowledge_response = await self._synthesize_knowledge_response(parsed.query_text, docs)
                parts.append(f"Information: {knowledge_response}")
            if products:
                parts.append(f"I also found {len(products)} relevant product(s).")
            
            reply_text = " ".join(parts) if parts else "I found some information that might help. Here are the details:"
        
        if docs and reply_text:
            source_lines = "\n".join(
                f"- {doc.title}{f' ({doc.url})' if doc.url else ''}" for doc in docs
            )
            reply_text = f"{reply_text}\n\nSources:\n{source_lines}"

        return ChatResponse(
            conversation_id=0,  # Placeholder, will be overwritten
            reply_text=reply_text,
            intent=parsed.intent,
            product_carousel=products,
            sources=docs
        )
    
    async def _synthesize_knowledge_response(self, query: str, docs: List[KnowledgeSource]) -> str:
        """
        Synthesize multiple knowledge sources into a coherent answer using LLM.
        """
        if not docs:
            return "I don't have information on that topic."
        
        # Combine top sources
        combined_content = "\n\n".join([
            f"[{doc.title}] {doc.content_snippet[:500]}"
            for doc in docs[:3]  # Use top 3 most relevant sources
        ])
        
        try:
            # Use LLM to synthesize a natural answer
            response = await self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant answering customer questions based on provided knowledge sources. Provide clear, concise answers."
                    },
                    {
                        "role": "user",
                        "content": f"Based on this knowledge:\n{combined_content}\n\nAnswer this question: {query}"
                    }
                ],
                temperature=0.7,
                max_tokens=500
            )
            
            return response.choices[0].message.content
        except Exception as e:
            # Fallback: simple concatenation if LLM fails
            return " ".join([doc.content_snippet[:300] for doc in docs[:2]])

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
            docs = await self.search_knowledge(parsed.query_text, emb)
            
        # 6. Generation
        response = await self.generate_response(parsed, products, docs)
        response.conversation_id = conversation.id
        
        # 7. Save Messages
        await self.save_message(conversation.id, MessageRole.USER, req.message)
        await self.save_message(conversation.id, MessageRole.ASSISTANT, response.reply_text)
        
        return response
