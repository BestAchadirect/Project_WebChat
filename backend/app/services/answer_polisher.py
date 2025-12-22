import re
from dataclasses import dataclass
from typing import List, Optional, Set

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm_service import llm_service

logger = get_logger(__name__)


_URL_RE = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
_SKU_RE = re.compile(r"\b[a-z0-9]{2,}-[a-z0-9]{2,}\b", re.IGNORECASE)
_NUM_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")


@dataclass(frozen=True)
class ExtractedArtifacts:
    urls: Set[str]
    skus: Set[str]
    numbers: Set[str]


def _extract_artifacts(text: str) -> ExtractedArtifacts:
    urls = set(_URL_RE.findall(text or ""))
    skus = {m.group(0) for m in _SKU_RE.finditer(text or "")}
    numbers = {m.group(0) for m in _NUM_RE.finditer(text or "")}
    return ExtractedArtifacts(urls=urls, skus=skus, numbers=numbers)


def _contains_all(needles: Set[str], haystack: str) -> bool:
    for n in needles:
        if n and n not in haystack:
            return False
    return True


class AnswerPolisher:
    async def polish(
        self,
        *,
        draft_text: str,
        route: str,
        user_text: str,
        has_product_carousel: bool,
    ) -> str:
        enabled = bool(getattr(settings, "ANSWER_POLISHER_ENABLED", False))
        if not enabled:
            return draft_text
        if not draft_text or len(draft_text.strip()) < 20:
            return draft_text
        if route in {"smalltalk"}:
            return draft_text

        artifacts = _extract_artifacts(draft_text)
        model = getattr(settings, "ANSWER_POLISHER_MODEL", None) or settings.OPENAI_MODEL
        max_tokens = int(getattr(settings, "ANSWER_POLISHER_MAX_TOKENS", 200))

        system = (
            "You are an answer polisher for a customer-facing assistant.\n"
            "Rewrite ONLY the draft answer for clarity and friendliness.\n"
            "STRICT RULES:\n"
            "- Do NOT add new facts, policies, prices, or commitments.\n"
            "- Do NOT remove or change any URLs.\n"
            "- Do NOT remove or change any SKUs.\n"
            "- Do NOT change any numbers (including prices, quantities, dates).\n"
            "- Do NOT include a 'Sources' or 'References' section.\n"
            "- Keep it concise.\n"
        )
        if has_product_carousel:
            system += (
                "- A product carousel will be shown separately; do NOT list products. "
                "Keep the text to a brief intro.\n"
            )

        user = (
            f"User message:\n{user_text}\n\n"
            f"Draft answer:\n{draft_text}\n\n"
            "Return ONLY the rewritten answer text."
        )

        try:
            polished = await llm_service.generate_chat_response(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                model=model,
            )
        except Exception as e:
            logger.warning(f"answer_polisher failed: {e}")
            return draft_text

        if not polished:
            return draft_text

        # Validate critical artifacts were preserved
        if not _contains_all(artifacts.urls, polished):
            logger.info("answer_polisher validation failed: urls changed/removed")
            return draft_text
        if not _contains_all(artifacts.skus, polished):
            logger.info("answer_polisher validation failed: skus changed/removed")
            return draft_text
        if not _contains_all(artifacts.numbers, polished):
            logger.info("answer_polisher validation failed: numbers changed/removed")
            return draft_text

        return polished.strip()


answer_polisher = AnswerPolisher()

