from __future__ import annotations

from typing import Dict, List, Set, Type

from app.schemas.chat import ChatComponent
from app.services.chat.components.base import BaseComponent
from app.services.chat.components.builders import (
    ActionResultComponent,
    ClarifyComponent,
    CompareComponent,
    ErrorComponent,
    KnowledgeAnswerComponent,
    ProductBulletsComponent,
    ProductCardsComponent,
    ProductDetailComponent,
    ProductTableComponent,
    QuerySummaryComponent,
    RecommendationsComponent,
    ResultCountComponent,
)
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentType


class ComponentRegistry:
    _registry: Dict[ComponentType, Type[BaseComponent]] = {
        ComponentType.QUERY_SUMMARY: QuerySummaryComponent,
        ComponentType.RESULT_COUNT: ResultCountComponent,
        ComponentType.PRODUCT_CARDS: ProductCardsComponent,
        ComponentType.PRODUCT_TABLE: ProductTableComponent,
        ComponentType.PRODUCT_BULLETS: ProductBulletsComponent,
        ComponentType.PRODUCT_DETAIL: ProductDetailComponent,
        ComponentType.COMPARE: CompareComponent,
        ComponentType.RECOMMENDATIONS: RecommendationsComponent,
        ComponentType.CLARIFY: ClarifyComponent,
        ComponentType.KNOWLEDGE_ANSWER: KnowledgeAnswerComponent,
        ComponentType.ACTION_RESULT: ActionResultComponent,
        ComponentType.ERROR: ErrorComponent,
    }

    @classmethod
    def builder_for(cls, component_type: ComponentType) -> BaseComponent:
        builder_cls = cls._registry.get(component_type)
        if builder_cls is None:
            raise KeyError(f"missing builder for component_type={component_type.value}")
        return builder_cls()

    @classmethod
    def required_fields_for(cls, component_types: List[ComponentType]) -> Set[str]:
        required: Set[str] = set()
        for component_type in component_types:
            builder = cls.builder_for(component_type)
            required.update(set(builder.required_fields or set()))
        return required

    @classmethod
    async def build_components(
        cls,
        *,
        component_types: List[ComponentType],
        context: ComponentContext,
    ) -> List[ChatComponent]:
        built: List[ChatComponent] = []
        for component_type in component_types:
            builder = cls.builder_for(component_type)
            built.append(await builder.build(context))
        return built

