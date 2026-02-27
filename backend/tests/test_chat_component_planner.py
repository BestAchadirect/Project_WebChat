from app.services.chat.components.planner import OutputPlanner
from app.services.chat.components.types import ComponentType


def test_planner_compare_rule() -> None:
    planned = OutputPlanner.plan(
        user_text="compare SKU-1 and SKU-2",
        intent="search_specific",
        sku_count=2,
        product_count=2,
        is_detail_mode=False,
        is_ambiguous=False,
    )
    assert planned == [ComponentType.QUERY_SUMMARY, ComponentType.COMPARE, ComponentType.RESULT_COUNT]


def test_planner_table_rule() -> None:
    planned = OutputPlanner.plan(
        user_text="show table for steel rings",
        intent="browse_products",
        sku_count=0,
        product_count=8,
        is_detail_mode=False,
        is_ambiguous=False,
    )
    assert ComponentType.PRODUCT_TABLE in planned
    assert ComponentType.RESULT_COUNT in planned


def test_planner_clarify_when_ambiguous() -> None:
    planned = OutputPlanner.plan(
        user_text="compare this",
        intent="browse_products",
        sku_count=0,
        product_count=0,
        is_detail_mode=False,
        is_ambiguous=True,
    )
    assert planned == [ComponentType.QUERY_SUMMARY, ComponentType.CLARIFY]


def test_planner_how_many_includes_count() -> None:
    planned = OutputPlanner.plan(
        user_text="how many titanium clickers do you have",
        intent="browse_products",
        sku_count=0,
        product_count=12,
        is_detail_mode=False,
        is_ambiguous=False,
    )
    assert ComponentType.RESULT_COUNT in planned


def test_planner_single_exact_sku_prefers_detail() -> None:
    planned = OutputPlanner.plan(
        user_text="tell me about SKU-123",
        intent="search_specific",
        sku_count=1,
        product_count=1,
        is_detail_mode=False,
        is_ambiguous=False,
    )
    assert planned == [ComponentType.QUERY_SUMMARY, ComponentType.PRODUCT_DETAIL]


def test_planner_knowledge_path() -> None:
    planned = OutputPlanner.plan(
        user_text="what is your shipping policy",
        intent="knowledge_query",
        sku_count=0,
        product_count=0,
        is_detail_mode=False,
        is_ambiguous=False,
    )
    assert planned == [ComponentType.QUERY_SUMMARY, ComponentType.KNOWLEDGE_ANSWER]
