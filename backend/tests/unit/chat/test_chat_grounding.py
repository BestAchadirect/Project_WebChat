from types import SimpleNamespace

from app.schemas.chat import KnowledgeSource
from app.services.chat.runtime.grounding import (
    evaluate_catalog_grounding,
    evaluate_knowledge_grounding,
)
from app.services.chat.runtime.search_plan import SearchPlan, build_search_plan


def _product(**overrides):
    attrs = {
        "material": "titanium",
        "jewelry_type": "labret",
        "opal_color": "opal",
        "color": "opal",
    }
    attrs.update(overrides.pop("attributes", {}))
    defaults = {
        "id": "product-1",
        "sku": "SKU-1",
        "legacy_sku": [],
        "name": "Titanium opal labret",
        "description": "",
        "search_text": "titanium opal labret",
        "attributes": attrs,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_search_plan_separates_filters_semantic_terms_and_context() -> None:
    detail = SimpleNamespace(
        attribute_filters={"opal_color": "opal"},
        semantic_hints=["sterilization"],
    )

    plan = build_search_plan(
        user_text="No I mean product with sterilization and opal color",
        workflow="catalog",
        detail=detail,
        sku_tokens=["SKU-1"],
        knowledge_query="",
        conversation_anchor={"last_attribute_filters": {"jewelry_type": "labret"}},
        context_allowed=True,
        context_reason="contextual_filter_merge",
    )

    assert plan.workflow == "catalog"
    assert plan.required_filters == {"opal_color": "opal"}
    assert plan.semantic_terms == ["sterilization"]
    assert plan.sku_tokens == ["SKU-1"]
    assert plan.context_allowed is True
    assert plan.context_reason == "contextual_filter_merge"
    assert plan.conversation_anchor["last_attribute_filters"] == {"jewelry_type": "labret"}


def test_search_plan_expected_tools_for_catalog_search() -> None:
    plan = build_search_plan(
        user_text="show me titanium labrets",
        workflow="catalog",
        detail=SimpleNamespace(attribute_filters={}, semantic_hints=["labrets"]),
        sku_tokens=[],
    )

    assert plan.expected_tools() == ["search_products"]
    assert plan.expected_tool_groups() == [["search_products"]]
    assert plan.to_debug_dict()["expected_tools"] == ["search_products"]


def test_search_plan_expected_tools_for_product_detail_or_stock_check() -> None:
    plan = build_search_plan(
        user_text="check stock for ABC-1",
        workflow="catalog",
        detail=SimpleNamespace(attribute_filters={}, semantic_hints=[]),
        sku_tokens=["ABC-1"],
    )

    assert plan.expected_tools() == ["get_product_details", "check_inventory_db"]
    assert plan.expected_tool_groups() == [["get_product_details", "check_inventory_db"]]


def test_search_plan_expected_tools_for_knowledge_search() -> None:
    plan = build_search_plan(
        user_text="what is your shipping policy?",
        workflow="knowledge",
        detail=SimpleNamespace(attribute_filters={}, semantic_hints=[]),
        sku_tokens=[],
        knowledge_query="what is your shipping policy?",
    )

    assert plan.expected_tools() == ["search_knowledge_base"]
    assert plan.expected_tool_groups() == [["search_knowledge_base"]]


def test_search_plan_expected_tools_for_catalog_plus_knowledge_request() -> None:
    plan = build_search_plan(
        user_text="show titanium labrets and shipping policy",
        workflow="catalog",
        detail=SimpleNamespace(attribute_filters={}, semantic_hints=["labrets"]),
        sku_tokens=[],
        knowledge_query="what is your shipping policy?",
    )

    assert plan.expected_tools() == ["search_products", "search_knowledge_base"]
    assert plan.expected_tool_groups() == [["search_products"], ["search_knowledge_base"]]


def test_catalog_grounding_allows_products_matching_required_filters() -> None:
    plan = SearchPlan(
        workflow="catalog",
        required_filters={"opal_color": "opal"},
    )
    matching = _product(id="match")
    wrong = _product(id="wrong", attributes={"opal_color": "black", "color": "black"})

    decision = evaluate_catalog_grounding(
        plan=plan,
        products=[matching, wrong],
    )

    assert decision.status == "grounded"
    assert decision.safe_customer_action == "show_cards"
    assert decision.allowed_product_ids == ["match"]
    assert "filtered_unmatched_products" in decision.reasons


def test_catalog_grounding_blocks_required_filter_mismatch() -> None:
    plan = SearchPlan(
        workflow="catalog",
        required_filters={"opal_color": "opal"},
    )
    wrong = _product(id="wrong", attributes={"opal_color": "black", "color": "black"})

    decision = evaluate_catalog_grounding(
        plan=plan,
        products=[wrong],
    )

    assert decision.status == "unrelated"
    assert decision.safe_customer_action == "no_match"
    assert decision.missing_requirements == ["opal_color"]
    assert "required_filter_no_match" in decision.reasons


def test_catalog_grounding_treats_unconfirmed_semantic_only_results_as_weak() -> None:
    plan = SearchPlan(
        workflow="catalog",
        semantic_terms=["sterilization"],
    )
    broad = _product(search_text="titanium opal labret")

    decision = evaluate_catalog_grounding(
        plan=plan,
        products=[broad],
    )

    assert decision.status == "weak"
    assert decision.safe_customer_action == "clarify"
    assert "semantic_terms_not_confirmed" in decision.reasons


def test_knowledge_grounding_blocks_sources_below_relevance_threshold() -> None:
    source = KnowledgeSource(
        source_id="policy-low",
        title="Policy",
        content_snippet="Some unrelated policy.",
        relevance=0.2,
    )
    plan = SearchPlan(workflow="knowledge", knowledge_topics=["returns"])

    decision = evaluate_knowledge_grounding(
        plan=plan,
        sources=[source],
        answer="Returns are available.",
        min_relevance=0.6,
    )

    assert decision.status == "weak"
    assert decision.safe_customer_action == "clarify"
    assert "knowledge_relevance_below_threshold" in decision.reasons

