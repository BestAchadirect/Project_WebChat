from openai import AsyncOpenAI
from app.core.config import settings
from typing import List

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

class EmbeddingService:
    @staticmethod
    async def get_embedding(text: str) -> List[float]:
        text = text.replace("\n", " ")
        response = await client.embeddings.create(
            input=[text],
            model=settings.EMBEDDING_MODEL
        )
        return response.data[0].embedding
