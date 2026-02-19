from pydantic import ValidationError

from app.services.agent_tools import (
    GetProductDetailsArgs,
    SearchKnowledgeBaseArgs,
    SearchProductsArgs,
    AgentToolRegistry,
)


def test_search_products_args_accepts_page_size_alias() -> None:
    args = SearchProductsArgs.model_validate(
        {
            "query": "Titanium ring",
            "page": 2,
            "pageSize": 5,
            "filters": {"material": "Titanium"},
        }
    )
    assert args.page == 2
    assert args.page_size == 5
    assert args.filters == {"material": "Titanium"}


def test_search_products_args_rejects_unsupported_filter() -> None:
    try:
        SearchProductsArgs.model_validate(
            {
                "query": "Ring",
                "filters": {"brand": "X"},
            }
        )
    except ValidationError as exc:
        assert "unsupported filter keys" in str(exc)
        return
    raise AssertionError("Expected ValidationError")


def test_get_product_details_args_validates_empty_sku() -> None:
    try:
        GetProductDetailsArgs.model_validate({"sku": "   "})
    except ValidationError as exc:
        assert "sku cannot be empty" in str(exc)
        return
    raise AssertionError("Expected ValidationError")


def test_search_knowledge_base_limit_range() -> None:
    try:
        SearchKnowledgeBaseArgs.model_validate({"query": "shipping", "limit": 99})
    except ValidationError as exc:
        assert "less than or equal to 5" in str(exc)
        return
    raise AssertionError("Expected ValidationError")


def test_is_tool_suitable_for_inventory_query() -> None:
    result = AgentToolRegistry.is_tool_suitable(
        user_text="Can you check inventory for this item?",
        intent="knowledge_query",
        sku_token=None,
    )
    assert result is True

