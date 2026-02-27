from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.schemas.chat import KnowledgeSource
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.types import ComponentSource, ComponentType


@dataclass
class ComponentContext:
    user_text: str
    locale: str
    intent: str
    query_summary: str
    source: ComponentSource
    selected_components: List[ComponentType]
    canonical_products: List[CanonicalProduct] = field(default_factory=list)
    recommendations: List[CanonicalProduct] = field(default_factory=list)
    knowledge_sources: List[KnowledgeSource] = field(default_factory=list)
    knowledge_answer: str = ""
    result_count: int = 0
    attribute_filters: Dict[str, str] = field(default_factory=dict)
    sku_tokens: List[str] = field(default_factory=list)
    ambiguity_reason: Optional[str] = None
    error_message: Optional[str] = None
    debug: Dict[str, Any] = field(default_factory=dict)

