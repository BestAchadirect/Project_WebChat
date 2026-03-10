from app.services.catalog.attributes_service import EAVService


def test_split_multivalue_supports_delimited_strings_and_lists() -> None:
    service = EAVService()
    value = ["Steel", "Gold;;Silver", " Titanium ; Niobium ", None, ""]
    assert service._split_multivalue(value) == [
        "Steel",
        "Gold",
        "Silver",
        "Titanium ",
        " Niobium",
    ]


def test_normalize_value_norm_trims_and_lowercases() -> None:
    service = EAVService()
    assert service._normalize_value_norm("  Titanium G23  ") == "titanium g23"
    assert service._normalize_value_norm("   ") is None
    assert service._normalize_value_norm(None) is None


def test_canonicalize_value_uses_alias_map() -> None:
    service = EAVService()
    alias_lookup = {
        (10, "surgical steel"): ("Steel", "steel"),
    }
    value, value_norm = service._canonicalize_value(
        attribute_id=10,
        value="Surgical Steel",
        value_norm="surgical steel",
        alias_lookup=alias_lookup,
    )
    assert value == "Steel"
    assert value_norm == "steel"
