from app.prompts.ambiguity import ambiguity_blocks_retrieval, get_ambiguity_policy, normalize_focus_key


def test_ambiguity_registry_normalizes_keys() -> None:
    assert normalize_focus_key("Sterilization Meaning") == "sterilization_meaning"
    assert normalize_focus_key("sterilization-meaning") == "sterilization_meaning"


def test_ambiguity_registry_exposes_sterilization_policy() -> None:
    policy = get_ambiguity_policy("sterilization_meaning")

    assert policy is not None
    assert policy["block_retrieval"] is True
    assert "pre-sterilized jewelry" in policy["suggestions"][1]
    assert ambiguity_blocks_retrieval("sterilization meaning") is True


def test_ambiguity_registry_returns_none_for_unknown_focus() -> None:
    assert get_ambiguity_policy("opal_meaning") is None
    assert ambiguity_blocks_retrieval("opal_meaning") is False
