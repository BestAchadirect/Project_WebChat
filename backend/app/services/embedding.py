from typing import List

from app.services.llm_service import llm_service

class EmbeddingService:
    @staticmethod
    async def get_embedding(text: str) -> List[float]:
        return await llm_service.generate_embedding(text)
