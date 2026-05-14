from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

from app.services.chat.text_normalization import normalize_user_text


@dataclass(frozen=True)
class SearchPlan:
    workflow: str
    required_filters: Dict[str, str] = field(default_factory=dict)
    optional_filters: Dict[str, str] = field(default_factory=dict)
    semantic_terms: List[str] = field(default_factory=list)
    sku_tokens: List[str] = field(default_factory=list)
    knowledge_topics: List[str] = field(default_factory=list)
    conversation_anchor: Dict[str, Any] = field(default_factory=dict)
    context_allowed: bool = False
    context_reason: str = ""
    negative_constraints: List[str] = field(default_factory=list)
    strictness: Dict[str, str] = field(default_factory=dict)
    unresolved_constraints: List[Dict[str, str]] = field(default_factory=list)
    semantic_query: str = ""
    uses_previous_context: bool = False
    product_anchor_required: bool = False

    def to_debug_dict(self) -> Dict[str, Any]:
        return {
            "workflow": self.workflow,
            "required_filters": dict(self.required_filters),
            "optional_filters": dict(self.optional_filters),
            "semantic_terms": list(self.semantic_terms),
            "sku_tokens": list(self.sku_tokens),
            "knowledge_topics": list(self.knowledge_topics),
            "conversation_anchor": dict(self.conversation_anchor),
            "context_allowed": bool(self.context_allowed),
            "context_reason": self.context_reason,
            "negative_constraints": list(self.negative_constraints),
            "strictness": dict(self.strictness),
            "unresolved_constraints": [dict(item) for item in list(self.unresolved_constraints or [])],
            "semantic_query": self.semantic_query,
            "uses_previous_context": bool(self.uses_previous_context),
            "product_anchor_required": bool(self.product_anchor_required),
        }


def _clean_filter_map(filters: Mapping[str, Any] | None) -> Dict[str, str]:
    clean: Dict[str, str] = {}
    for key, value in dict(filters or {}).items():
        clean_key = str(key or "").strip().lower()
        clean_value = str(value or "").strip()
        if clean_key and clean_value:
            clean[clean_key] = clean_value
    return clean


def _clean_terms(items: Sequence[Any] | None) -> List[str]:
    clean: List[str] = []
    seen: set[str] = set()
    for item in list(items or []):
        text = normalize_user_text(str(item or ""))
        if not text or text in seen:
            continue
        seen.add(text)
        clean.append(text)
    return clean


def _knowledge_topics(*, workflow: str, knowledge_query: str, user_text: str) -> List[str]:
    workflow_norm = str(workflow or "").strip().lower()
    if workflow_norm not in {"knowledge", "catalog"}:
        return []
    query = normalize_user_text(knowledge_query) or normalize_user_text(user_text)
    if not query:
        return []
    return [query]


def build_search_plan(
    *,
    user_text: str,
    workflow: str,
    detail: Any,
    sku_tokens: Sequence[str],
    knowledge_query: str = "",
    conversation_anchor: Mapping[str, Any] | None = None,
    context_allowed: bool = False,
    context_reason: str = "",
    strictness: Mapping[str, Any] | None = None,
    unresolved_constraints: Sequence[Mapping[str, Any]] | None = None,
    semantic_query: str = "",
    uses_previous_context: bool = False,
    product_anchor_required: bool = False,
) -> SearchPlan:
    workflow_norm = str(workflow or "fallback").strip().lower() or "fallback"
    required_filters = _clean_filter_map(getattr(detail, "attribute_filters", {}) or {})
    semantic_terms = _clean_terms(getattr(detail, "semantic_hints", []) or [])
    clean_strictness: Dict[str, str] = {}
    for key, value in dict(strictness or {}).items():
        clean_key = str(key or "").strip().lower()
        clean_value = str(value or "").strip().lower()
        if clean_key and clean_value in {"required", "preferred", "optional"}:
            clean_strictness[clean_key] = clean_value
    clean_unresolved: List[Dict[str, str]] = []
    for item in list(unresolved_constraints or []):
        if not isinstance(item, Mapping):
            continue
        attribute = str(item.get("attribute") or "").strip().lower()
        value = str(item.get("value") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if attribute or value:
            clean_unresolved.append(
                {
                    "attribute": attribute,
                    "value": value,
                    "reason": reason,
                }
            )
    clean_skus = [
        str(token or "").strip()
        for token in list(sku_tokens or [])
        if str(token or "").strip()
    ]
    return SearchPlan(
        workflow=workflow_norm,
        required_filters=required_filters,
        optional_filters={},
        semantic_terms=semantic_terms,
        sku_tokens=list(dict.fromkeys(clean_skus)),
        knowledge_topics=_knowledge_topics(
            workflow=workflow_norm,
            knowledge_query=knowledge_query,
            user_text=user_text,
        ),
        conversation_anchor=dict(conversation_anchor or {}),
        context_allowed=bool(context_allowed),
        context_reason=str(context_reason or "").strip(),
        negative_constraints=[],
        strictness=clean_strictness,
        unresolved_constraints=clean_unresolved,
        semantic_query=normalize_user_text(semantic_query),
        uses_previous_context=bool(uses_previous_context),
        product_anchor_required=bool(product_anchor_required),
    )

