from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.tenant import Tenant
from app.models.chat_session import ChatSession
from app.models.message import Message, MessageRole
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.services.magento_service import MagentoService
from app.schemas.chat import ChatRequest, ChatResponse, ChatMessage
from app.schemas.product import ProductCarouselItem
from app.utils.classification import classify_user_intent, extract_product_keywords
from app.core.logging import get_logger

logger = get_logger(__name__)

class ChatService:
    """Service for chat orchestration."""
    
    async def process_chat(
        self,
        db: AsyncSession,
        request: ChatRequest
    ) -> ChatResponse:
        """
        Main chat orchestration logic.
        
        1. Get or create chat session
        2. Classify intent (product, FAQ, both)
        3. Retrieve relevant context (RAG for FAQ, Magento for products)
        4. Generate LLM response
        5. Save message history
        
        Args:
            db: Database session
            request: Chat request
        
        Returns:
            Chat response with message and optional products
        """
        try:
            # Get or create session
            session = await self._get_or_create_session(
                db, request.session_id, request.tenant_id
            )
            
            # Get tenant for Magento config
            tenant = await self._get_tenant(db, request.tenant_id)
            
            # Classify intent
            intent_result = await classify_user_intent(request.message)
            intent = intent_result.get("intent", "general")
            
            logger.info(f"Classified intent: {intent} (confidence: {intent_result.get('confidence')})")
            
            # Initialize response components
            faq_context = ""
            products = []
            sources = []
            
            # Handle FAQ intent
            if intent in ["faq", "both"]:
                faq_context = await rag_service.build_context(
                    db=db,
                    tenant_id=str(request.tenant_id),
                    query=request.message,
                    max_chunks=5
                )
                
                # Get sources for citation
                chunks = await rag_service.search_similar_chunks(
                    db=db,
                    tenant_id=str(request.tenant_id),
                    query=request.message,
                    limit=3
                )
                sources = [
                    {
                        "document_name": chunk["document_name"],
                        "similarity": chunk["similarity"]
                    }
                    for chunk in chunks
                ]
            
            # Handle product intent
            if intent in ["product", "both"] and tenant.magento_base_url:
                magento = MagentoService(
                    base_url=tenant.magento_base_url,
                    access_token=tenant.magento_access_token
                )
                
                # Extract keywords for product search
                keywords = extract_product_keywords(request.message)
                search_query = " ".join(keywords) if keywords else request.message
                
                # Search products
                product_results = await magento.search_products(
                    query=search_query,
                    limit=10
                )
                
                # Convert to carousel items
                products = [
                    ProductCarouselItem(
                        product_id=p.id,
                        name=p.name,
                        price=p.price,
                        image_url=p.image_url,
                        product_url=p.url,
                        short_description=p.description[:200] if p.description else None
                    )
                    for p in product_results
                ]
            
            # Build LLM messages
            llm_messages = self._build_llm_messages(
                user_message=request.message,
                history=request.history,
                faq_context=faq_context,
                products=products,
                intent=intent
            )
            
            # Generate response
            assistant_message = await llm_service.generate_chat_response(
                messages=llm_messages,
                temperature=0.7
            )
            
            # Save messages to database
            await self._save_messages(
                db=db,
                session_id=session.id,
                user_message=request.message,
                assistant_message=assistant_message
            )
            
            # Build response
            response = ChatResponse(
                message=assistant_message,
                session_id=session.session_id,
                intent=intent,
                products=products if products else None,
                sources=sources if sources else None,
                metadata={
                    "intent_confidence": intent_result.get("confidence"),
                    "num_products": len(products),
                    "num_sources": len(sources)
                }
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Error processing chat: {e}")
            raise
    
    async def _get_or_create_session(
        self,
        db: AsyncSession,
        session_id: Optional[str],
        tenant_id: UUID
    ) -> ChatSession:
        """Get existing session or create new one."""
        if session_id:
            stmt = select(ChatSession).where(ChatSession.session_id == session_id)
            result = await db.execute(stmt)
            session = result.scalar_one_or_none()
            if session:
                return session
        
        # Create new session
        new_session = ChatSession(
            tenant_id=tenant_id,
            session_id=session_id or str(uuid4())
        )
        db.add(new_session)
        await db.commit()
        await db.refresh(new_session)
        return new_session
    
    async def _get_tenant(self, db: AsyncSession, tenant_id: UUID) -> Tenant:
        """Get tenant by ID."""
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one()
    
    def _build_llm_messages(
        self,
        user_message: str,
        history: List[ChatMessage],
        faq_context: str,
        products: List[ProductCarouselItem],
        intent: str
    ) -> List[dict]:
        """Build messages for LLM."""
        messages = []
        
        # System message
        system_content = """You are a helpful e-commerce assistant. Your role is to:
1. Answer customer questions accurately and helpfully
2. Recommend relevant products when appropriate
3. Provide information based on the company's FAQ documents

Be concise, friendly, and professional."""
        
        if faq_context:
            system_content += f"\n\nRelevant FAQ information:\n{faq_context}"
        
        if products:
            product_info = "\n".join([
                f"- {p.name} (${p.price})"
                for p in products[:5]
            ])
            system_content += f"\n\nRelevant products:\n{product_info}"
        
        messages.append({"role": "system", "content": system_content})
        
        # Add history
        for msg in history[-5:]:  # Last 5 messages
            messages.append({"role": msg.role, "content": msg.content})
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        return messages
    
    async def _save_messages(
        self,
        db: AsyncSession,
        session_id: UUID,
        user_message: str,
        assistant_message: str
    ) -> None:
        """Save messages to database."""
        # Save user message
        user_msg = Message(
            chat_session_id=session_id,
            role=MessageRole.USER,
            content=user_message
        )
        db.add(user_msg)
        
        # Save assistant message
        assistant_msg = Message(
            chat_session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=assistant_message
        )
        db.add(assistant_msg)
        
        await db.commit()

# Singleton instance
chat_service = ChatService()
