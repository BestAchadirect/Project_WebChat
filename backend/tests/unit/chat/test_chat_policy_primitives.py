from __future__ import annotations

from app.prompts.ambiguity import (
    ambiguity_blocks_retrieval,
    get_ambiguity_policy,
    normalize_focus_key,
)
from app.services.chat.parsing.attribute_normalization import (
    clean_attribute_filters,
    normalize_attribute_value,
    normalize_lexical_alias_map,
    normalize_text,
)
from app.services.chat.parsing.search_policy import (
    ALLOWED_PRODUCT_FILTERS,
    detect_attribute_list_target,
    normalize_filter_map,
    needs_body_part_suitability_clarification,
    split_hard_and_soft_filters,
)
from app.services.chat.retrieval.result_policy import classify_match_tier
from app.services.chat.retrieval.retrieval_outcome import build_retrieval_outcome
from app.services.chat.components.types import ComponentSource


def _normalize_attribute_list_target(raw_target: object) -> str:
    text = normalize_text(raw_target)
    if not text:
        return ""
    normalized = text.replace("-", "_").replace(" ", "_").strip("_")
    allowed = {
        "body_part",
        "feature",
        "jewelry_type",
        "material",
        "presentation_type",
        "color",
        "gauge",
        "threading",
        "theme",
    }
    return normalized if normalized in allowed else ""


def _resolve_attribute_conflicts(attribute_filters: dict[str, str] | None) -> dict[str, str]:
    filters = dict(attribute_filters or {})
    if "opal_color" in filters:
        filters.pop("color", None)
        filters.pop("size", None)
    if "ring_size" in filters:
        filters.pop("size", None)
    if "size_in_pack" in filters:
        filters.pop("size", None)
    if "pincher_size" in filters:
        filters.pop("size", None)
    return filters


def test_detect_attribute_list_target_maps_list_queries() -> None:
    assert detect_attribute_list_target("What materials do you have?") == ""
    assert detect_attribute_list_target("Show gauges") == ""
    assert detect_attribute_list_target("How many gauges do you have for titanium jewelry?") == ""
    assert detect_attribute_list_target("What jewelry types do you have?") == ""
    assert detect_attribute_list_target("What body jewelry types do you have?") == ""
    assert detect_attribute_list_target("What body parts do you have?") == ""
    assert detect_attribute_list_target("Show presentation types") == ""
    assert detect_attribute_list_target("What features do you have?") == ""
    assert detect_attribute_list_target("Show themes") == ""
    assert detect_attribute_list_target("Tell me more about the store") == ""


def test_normalize_attribute_list_target_uses_shared_synonyms() -> None:
    assert _normalize_attribute_list_target("presentation type") == "presentation_type"
    assert _normalize_attribute_list_target("body jewelry types") == ""
    assert _normalize_attribute_list_target("unknown target") == ""


def test_needs_body_part_suitability_clarification_detects_fake_body_part_phrases() -> None:
    assert needs_body_part_suitability_clarification("fake nipple") is False
    assert needs_body_part_suitability_clarification("nipple piercing") is False
    assert needs_body_part_suitability_clarification("fake jewelry") is False


def test_split_hard_and_soft_filters_uses_shared_policy_keys() -> None:
    hard_filters, soft_filters = split_hard_and_soft_filters(
        attribute_filters={
            "gauge": "14g",
            "presentation_type": "Sold by Pack",
            "feature": "PVD Plated",
            "material": "titanium",
            "color": "opal",
            "theme": "skulls",
            "source_raw_sku": "ABC-123",
        }
    )

    assert hard_filters == {
        "gauge": "14g",
        "feature": "PVD Plated",
        "presentation_type": "Sold by Pack",
        "material": "titanium",
    }
    assert soft_filters == {
        "color": "opal",
        "theme": "skulls",
        "source_raw_sku": "ABC-123",
    }


def test_split_hard_and_soft_filters_honors_required_strictness() -> None:
    hard_filters, soft_filters = split_hard_and_soft_filters(
        attribute_filters={"color": "black", "theme": "gothic"},
        strictness={"color": "required", "theme": "preferred"},
    )

    assert hard_filters == {"color": "black"}
    assert soft_filters == {"theme": "gothic"}


def test_resolve_attribute_conflicts_prefers_specific_filters() -> None:
    resolved = _resolve_attribute_conflicts(
        {
            "color": "opal",
            "opal_color": "opal",
            "size": "8mm",
            "ring_size": "8mm",
            "size_in_pack": "20",
            "pincher_size": "1.2mm",
        }
    )

    assert resolved == {
        "opal_color": "opal",
        "ring_size": "8mm",
        "size_in_pack": "20",
        "pincher_size": "1.2mm",
    }


def test_allowed_product_filters_remain_stable() -> None:
    assert {"material", "jewelry_type", "color", "presentation_type", "body_location", "theme", "feature"}.issubset(ALLOWED_PRODUCT_FILTERS)


def test_normalize_filter_map_applies_aliases_and_allowlist() -> None:
    normalized = normalize_filter_map(
        {
            "Type": "Labret",
            "diameter": "8mm",
            "ignored": "x",
            "color": "  Opal  ",
            "material": "implant grade titanium",
            "threading": "internally threaded",
            "presentation_type": "Sold by Pack",
            "body_part": "Upper Lip / Monroe",
            "feature": "PVD Plated",
        },
        allowed_keys=ALLOWED_PRODUCT_FILTERS | {"outer_diameter", "threading"},
        key_aliases={"type": "jewelry_type", "diameter": "outer_diameter"},
    )

    assert normalized == {
        "jewelry_type": "labret",
        "outer_diameter": "8mm",
        "color": "opal",
        "material": "implant grade titanium",
        "threading": "internally threaded",
        "presentation_type": "sold by pack",
        "body_location": "upper lip / monroe",
        "feature": "pvd plated",
    }


def test_result_policy_classifies_match_tiers() -> None:
    assert classify_match_tier(structured_found=True, semantic_found=False) == "exact_match"
    assert classify_match_tier(structured_found=False, semantic_found=True) == "semantic_suggestion"
    assert classify_match_tier(structured_found=False, semantic_found=False) == "no_match"


def test_retrieval_outcome_distinguishes_exact_semantic_and_clarify_paths() -> None:
    exact = build_retrieval_outcome(
        retrieval_source=ComponentSource.SQL,
        product_ids=["1"],
        ambiguity_reason="",
    )
    semantic = build_retrieval_outcome(
        retrieval_source=ComponentSource.VECTOR,
        product_ids=["1"],
        ambiguity_reason="",
    )
    clarify = build_retrieval_outcome(
        retrieval_source=ComponentSource.ERROR,
        product_ids=[],
        ambiguity_reason="structured_no_match",
    )

    assert exact.is_exact_match is True
    assert exact.is_semantic_fallback is False
    assert exact.needs_clarification is False
    assert exact.retrieval_quality == "exact"
    assert semantic.is_exact_match is False
    assert semantic.is_semantic_fallback is True
    assert semantic.needs_clarification is False
    assert semantic.retrieval_quality == "approximate"
    assert clarify.match_tier == "no_match"
    assert clarify.is_exact_match is False
    assert clarify.is_semantic_fallback is False
    assert clarify.needs_clarification is True
    assert clarify.retrieval_quality == "no_match"


def test_ambiguity_registry_normalizes_keys() -> None:
    assert normalize_focus_key("Sterilization Concept") == "sterilization_concept"
    assert normalize_focus_key("sterilization-concept") == "sterilization_concept"


def test_ambiguity_registry_exposes_condition_policy() -> None:
    policy = get_ambiguity_policy("condition")

    assert policy is not None
    assert policy["focus_family"] == "condition"
    assert policy["block_retrieval"] is True
    assert policy["questions"] == []
    assert policy["suggestions"] == []
    assert policy["message_hint"].lower().startswith("what ")
    assert ambiguity_blocks_retrieval("condition") is True


def test_ambiguity_registry_returns_none_for_unknown_focus() -> None:
    assert get_ambiguity_policy("opal_meaning") is None
    assert ambiguity_blocks_retrieval("opal_meaning") is False


def test_normalize_text_collapses_whitespace_and_case() -> None:
    assert normalize_text("  Opal   Color  ") == "opal color"


def test_normalize_db_value_trims_and_lowercases_only() -> None:
    from app.services.chat.text_normalization import normalize_db_value, normalize_user_text

    assert normalize_db_value("  Opal   Color  ") == "opal   color"
    assert normalize_user_text("  Opal   Color  ") == "opal color"


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
    ) == "sterilisation"
    assert normalize_attribute_value(
        key="color",
        value="  With Opal  ",
        alias_map=alias_map,
    ) == "opal"
    assert normalize_attribute_value(
        key="material",
        value="Implant Grade Titanium",
        alias_map=alias_map,
    ) == "implant grade titanium"
    assert normalize_attribute_value(
        key="material",
        value="14k gold",
        alias_map=alias_map,
    ) == "14k gold"
    assert normalize_attribute_value(
        key="material",
        value="sterling silver",
        alias_map=alias_map,
    ) == "sterling silver"
    assert normalize_attribute_value(
        key="jewelry_type",
        value="Labrets",
        alias_map=alias_map,
    ) == "labrets"
    assert normalize_attribute_value(
        key="threading",
        value="internally threaded",
        alias_map=alias_map,
    ) == "internally threaded"
    assert normalize_attribute_value(
        key="presentation_type",
        value="sold by pack",
        alias_map=alias_map,
    ) == "sold by pack"
    assert normalize_attribute_value(
        key="body_part",
        value="upper lip / monroe",
        alias_map=alias_map,
    ) == "upper lip / monroe"
    assert normalize_attribute_value(
        key="feature",
        value="pvd plated",
        alias_map=alias_map,
    ) == "pvd plated"
    assert normalize_attribute_value(
        key="gauge",
        value="25 gauge",
        alias_map=alias_map,
    ) == "25 gauge"


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
        "gauge": "25 gauge",
        "material": "titanium",
    }
