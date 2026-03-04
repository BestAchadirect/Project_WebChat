from app.api.routes.products import _prepare_category_filter_groups
from app.services.catalog.category_taxonomy_service import category_taxonomy_service


def test_normalize_category_tokens_from_compound_string() -> None:
    tokens = category_taxonomy_service.normalize_category_tokens(
        "KLEVU_PRODUCT;;Belly Piercing;;Sold per piece;;Surgical Steel;;silicon;;@ku@kuCategory@ku@"
    )
    assert tokens == ["Belly Piercing", "Sold per piece", "Surgical Steel", "Silicone"]


def test_normalize_category_string_keeps_double_semicolon_contract() -> None:
    value = category_taxonomy_service.normalize_category_string(
        "Belly Piercing;;Sold per piece;;Belly Piercing;;Surgical Steel"
    )
    assert value == "Belly Piercing;;Sold per piece;;Surgical Steel"


def test_slugify_generates_stable_category_slug() -> None:
    assert category_taxonomy_service.slugify("Ear Piercing Others") == "ear-piercing-others"


def test_prepare_category_filter_groups_supports_legacy_compound_queries() -> None:
    singles, groups = _prepare_category_filter_groups(
        ["Belly Piercing", "Belly Piercing;;Sold per piece;;Surgical Steel"]
    )
    assert singles == ["Belly Piercing"]
    assert groups == [["Belly Piercing", "Sold per piece", "Surgical Steel"]]
