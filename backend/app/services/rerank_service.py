from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RerankResult:
    index: int
    relevance_score: float


class RerankService:
    """Cohere rerank wrapper (optional if COHERE_API_KEY is missing)."""

    COHERE_RERANK_URL = "https://api.cohere.com/v1/rerank"

    async def rerank(
        self,
        *,
        query: str,
        documents: List[str],
        top_n: int,
        model: str,
        timeout_seconds: float = 6.0,
    ) -> Optional[List[RerankResult]]:
        api_key = getattr(settings, "COHERE_API_KEY", None)
        if not api_key:
            logger.warning("COHERE_API_KEY missing; skipping rerank")
            return None

        if not documents:
            return []

        payload = {
            "model": model,
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(documents)),
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        timeout = httpx.Timeout(timeout_seconds, connect=timeout_seconds)

        # 1 retry max
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(self.COHERE_RERANK_URL, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("results", []) or []
                    parsed: List[RerankResult] = []
                    for r in results:
                        parsed.append(
                            RerankResult(
                                index=int(r["index"]),
                                relevance_score=float(r["relevance_score"]),
                            )
                        )
                    return parsed
            except Exception as e:
                logger.warning(f"Cohere rerank attempt {attempt+1} failed: {e}")
                if attempt == 1:
                    return None


rerank_service = RerankService()

