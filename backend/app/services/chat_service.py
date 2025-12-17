from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.chat import ChatRequest, ChatResponse, MessageRole
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
# from app.services.product_service import product_service # Assuming this exists or will be needed
from app.core.logging import get_logger

logger = get_logger(__name__)

class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def process_chat(self, request: ChatRequest) -> ChatResponse:
        """
        Process a chat request:
        1. Save user message history? (Optional, handled by frontend usually or DB logging)
        2. Classify intent.
        3. Retrieve context if needed.
        4. Generate response.
        """
        user_msg = request.message
        history = request.history or []
        
        try:
            # 1. Classify Intent
            classification = await llm_service.classify_intent(user_msg)
            intent = classification.get("intent", "general")
            logger.info(f"Classified intent: {intent} (Confidence: {classification.get('confidence')})")

            context_str = ""
            sources = []

            # 2. Retrieval Strategy
            if intent in ["product", "faq", "both"]:
                # Fetch recent knowledge chunks
                # We can also fetch products if needed
                context_str = await rag_service.build_context(self.db, user_msg)
                
                # If product search is needed, we'd add it here:
                # product_context = await product_service.search_products(self.db, user_msg)
                # context_str += "\n" + product_context

            # 3. Build Prompt
            system_msg = {
                "role": "system",
                "content": (
                    "You are a helpful AI assistant for an e-commerce platform. "
                    "Use the provided context to answer the user's question clearly and concisely. "
                    "If the answer is not available in the context, politely state that you don't have that information. "
                    "Do not hallucinate facts."
                )
            }
            
            # Add Context if available
            if context_str:
                system_msg["content"] += f"\n\nContext Information:\n{context_str}"

            # Format history for LLM
            messages = [system_msg]
            for msg in history[-5:]: # Keep last 5 turns for context window
                messages.append({"role": msg.role, "content": msg.content})
            
            messages.append({"role": "user", "content": user_msg})

            # 4. Generate Response
            answer = await llm_service.generate_chat_response(messages)

            return ChatResponse(
                message=answer,
                intent=intent,
                sources=sources # We could parse sources from context_str if implemented
            )

        except Exception as e:
            logger.error(f"Error processing chat: {e}")
            # Fallback response
            return ChatResponse(
                message="I'm sorry, I encountered an error processing your request. Please try again later.",
                intent="error"
            )
