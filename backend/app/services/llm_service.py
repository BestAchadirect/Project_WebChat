import json
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class LLMService:
    """Service for interacting with OpenAI LLM and embeddings."""
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL
        self.embedding_model = settings.EMBEDDING_MODEL
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a text."""
        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise
    
    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=texts
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            raise
    
    async def generate_chat_response(
        self,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        """Generate a chat response using the LLM."""
        try:
            response = await self.client.chat.completions.create(
                model=model or self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error generating chat response: {e}")
            raise

    async def generate_chat_json(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = 300,
    ) -> Dict[str, Any]:
        """Generate strict JSON output using response_format=json_object."""
        response = await self.client.chat.completions.create(
            model=model or self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
    
    async def classify_intent(self, user_message: str) -> dict:
        """
        Classify user intent as 'product', 'faq', 'both', or 'general'.
        Returns: {"intent": str, "confidence": float, "reasoning": str}
        """
        system_prompt = """You are an intent classifier for an e-commerce chatbot.
Classify the user's message into one of these categories:
- "product": User is looking for product recommendations or product information
- "faq": User has a general question (shipping, returns, policies, etc.)
- "both": User's question involves both products and general information
- "general": General conversation or greeting

Respond in JSON format: {"intent": "...", "confidence": 0.0-1.0, "reasoning": "..."}"""
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            return result
        except Exception as e:
            logger.error(f"Error classifying intent: {e}")
            # Fallback to general
            return {"intent": "general", "confidence": 0.5, "reasoning": "Classification failed"}

# Singleton instance
llm_service = LLMService()
