from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.api.routes.products import _apply_category_filter, _apply_dual_source_attr_filter
from app.models.product import Product


def _to_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


def test_category_filter_any_mode_matches_any_single_category() -> None:
    query = select(Product.id)
    count_query = select(func.count()).select_from(Product)
    query, _ = _apply_category_filter(
        query,
        count_query,
        ["Belly Piercing", "Ear Piercing"],
        category_mode="any",
    )

    sql = _to_sql(query)
    assert "product_categories.category_id)) >=" not in sql


def test_category_filter_all_mode_requires_all_single_categories() -> None:
    query = select(Product.id)
    count_query = select(func.count()).select_from(Product)
    query, _ = _apply_category_filter(
        query,
        count_query,
        ["Belly Piercing", "Ear Piercing"],
        category_mode="all",
    )

    sql = _to_sql(query)
    assert "product_categories.category_id)) >= 2" in sql


def test_dual_source_attribute_filter_does_not_use_search_text_fallback() -> None:
    query = select(Product.id)
    count_query = select(func.count()).select_from(Product)
    query, _ = _apply_dual_source_attr_filter(
        query,
        count_query,
        field="material",
        normalized_values=["steel"],
        attribute_id=None,
    )

    sql = _to_sql(query)
    assert "search_text" not in sql
