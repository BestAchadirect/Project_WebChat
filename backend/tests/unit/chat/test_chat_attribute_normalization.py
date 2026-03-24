from __future__ import annotations

from app.services.chat.parsing.attribute_normalization import (
    clean_attribute_filters,
    normalize_attribute_value,
    normalize_gauge_token,
    normalize_lexical_alias_map,
    normalize_measurement_token,
    normalize_text,
)
from app.services.chat.text_normalization import normalize_db_value, normalize_user_text


def test_normalize_text_collapses_whitespace_and_case() -> None:
    assert normalize_text("  Opal   Color  ") == "opal color"
    assert normalize_user_text("  Opal   Color  ") == "opal color"


def test_normalize_db_value_trims_and_lowercases_only() -> None:
    assert normalize_db_value("  Opal   Color  ") == "opal   color"


def test_normalize_lexical_alias_map_keeps_canonical_self_mapping() -> None:
    normalized = normalize_lexical_alias_map(
        {
            "Material": {
                "implant grade titanium": "Titanium G23",
                "titanium g23": "Titanium G23",
            }
        }
    )

    assert normalized == {
        "material": {
            "implant grade titanium": "titanium g23",
            "titanium g23": "titanium g23",
        }
    }


def test_normalize_value_helpers_cover_gauge_and_measurements() -> None:
    assert normalize_gauge_token("25 gauge") == "25g"
    assert normalize_gauge_token("1.2 mm") == "1.2mm"
    assert normalize_measurement_token("8 mm") == "8mm"
    assert normalize_measurement_token("1.5 inches") == "1.5inch"


def test_normalize_attribute_value_uses_aliases_and_key_rules() -> None:
    alias_map = {
        "finish": {
            "sterilisation": "sterilized",
        },
        "color": {
            "opal color": "opal",
        },
    }

    assert normalize_attribute_value(
        key="finish",
        value="Sterilisation",
        alias_map=alias_map,
    ) == "sterilized"
    assert normalize_attribute_value(
        key="color",
        value="  With Opal  ",
        alias_map=alias_map,
    ) == "opal"
    assert normalize_attribute_value(
        key="gauge",
        value="25 gauge",
        alias_map=alias_map,
    ) == "25g"


def test_clean_attribute_filters_respects_allowlist() -> None:
    normalized = clean_attribute_filters(
        {
            "gauge": "25 gauge",
            "material": "  Titanium ",
            "ignored": "x",
        },
        alias_map={"material": {"titanium": "Titanium"}},
        allowed_attribute_filters=["gauge", "material"],
    )

    assert normalized == {
        "gauge": "25g",
        "material": "titanium",
    }
