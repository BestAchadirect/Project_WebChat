from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.schemas.chat import KnowledgeSource
from app.services.chat.components.builders.action_result import ActionResultComponent
from app.services.chat.components.builders.clarify import ClarifyComponent
from app.services.chat.components.builders.compare import CompareComponent
from app.services.chat.components.builders.error import ErrorComponent
from app.services.chat.components.builders.knowledge_answer import KnowledgeAnswerComponent
from app.services.chat.components.builders.product_bullets import ProductBulletsComponent
from app.services.chat.components.builders.product_cards import ProductCardsComponent
from app.services.chat.components.builders.product_detail import ProductDetailComponent
from app.services.chat.components.builders.product_table import ProductTableComponent
from app.services.chat.components.builders.query_summary import QuerySummaryComponent
from app.services.chat.components.builders.recommendations import RecommendationsComponent
from app.services.chat.components.builders.result_count import ResultCountComponent
from app.services.chat.components.canonical_model import CanonicalProduct
from app.services.chat.components.context import ComponentContext
from app.services.chat.components.types import ComponentSource, ComponentType


def _sample_products() -> list[CanonicalProduct]:
    return [
        CanonicalProduct(
            product_id=uuid4(),
            sku="SKU-1",
            title="Ring One",
            price=Decimal("12.50"),
            currency="USD",
            in_stock=True,
            stock_qty=5,
            material="Steel",
            gauge="16g",
            image_url="https://example.com/1.jpg",
            attributes={"material": "Steel", "gauge": "16g"},
            product_url="https://example.com/p1",
        ),
        CanonicalProduct(
            product_id=uuid4(),
            sku="SKU-2",
            title="Ring Two",
            price=Decimal("20.00"),
            currency="USD",
            in_stock=False,
            stock_qty=0,
            material="Titanium",
            gauge="14g",
            image_url="https://example.com/2.jpg",
            attributes={"material": "Titanium", "gauge": "14g"},
            product_url="https://example.com/p2",
        ),
    ]


def _sample_context() -> ComponentContext:
    products = _sample_products()
    return ComponentContext(
        user_text="compare SKU-1 and SKU-2",
        locale="en-US",
        intent="browse_products",
        query_summary="compare products",
        source=ComponentSource.SQL,
        selected_components=[ComponentType.QUERY_SUMMARY],
        canonical_products=products,
        recommendations=[products[1]],
        knowledge_sources=[
            KnowledgeSource(
                source_id="kb-1",
                title="Shipping",
                content_snippet="Ships in 3-5 days",
                relevance=0.9,
            )
        ],
        knowledge_answer="Shipping takes 3-5 days.",
        result_count=len(products),
        ambiguity_reason="need_more_context",
        error_message="component error",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder_cls, expected_type, expected_key",
    [
        (QuerySummaryComponent, ComponentType.QUERY_SUMMARY, "text"),
        (ResultCountComponent, ComponentType.RESULT_COUNT, "count"),
        (ProductCardsComponent, ComponentType.PRODUCT_CARDS, "cards"),
        (ProductTableComponent, ComponentType.PRODUCT_TABLE, "rows"),
        (ProductBulletsComponent, ComponentType.PRODUCT_BULLETS, "items"),
        (ProductDetailComponent, ComponentType.PRODUCT_DETAIL, "product"),
        (CompareComponent, ComponentType.COMPARE, "items"),
        (RecommendationsComponent, ComponentType.RECOMMENDATIONS, "items"),
        (ClarifyComponent, ComponentType.CLARIFY, "message"),
        (KnowledgeAnswerComponent, ComponentType.KNOWLEDGE_ANSWER, "answer"),
        (ActionResultComponent, ComponentType.ACTION_RESULT, "status"),
        (ErrorComponent, ComponentType.ERROR, "message"),
    ],
)
async def test_builder_outputs_shape(builder_cls, expected_type: ComponentType, expected_key: str) -> None:
    context = _sample_context()
    component = await builder_cls().build(context)
    assert str(component.type.value) == expected_type.value
    assert expected_key in component.data
