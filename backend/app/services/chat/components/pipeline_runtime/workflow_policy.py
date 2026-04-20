from __future__ import annotations

from typing import Sequence

from app.schemas.chat import KnowledgeSource
from app.services.chat.text_normalization import normalize_user_text

class PipelineWorkflowPolicyMixin:
    @classmethod
    def _contains_any_term(cls, *, text: str, terms: Sequence[str]) -> bool:
            normalized = normalize_user_text(text)
            return bool(normalized and any(term in normalized for term in terms))

    @classmethod
    def _is_high_risk_knowledge_request(cls, *, text: str) -> bool:
            return cls._contains_any_term(text=text, terms=cls._HIGH_RISK_KNOWLEDGE_TERMS)

    @staticmethod
    def _knowledge_sources_are_weak(*, sources: Sequence[KnowledgeSource], min_relevance: float) -> bool:
            if not sources:
                return True
            top_relevance = max(float(getattr(source, "relevance", 0.0) or 0.0) for source in list(sources or []))
            return top_relevance < float(min_relevance)
