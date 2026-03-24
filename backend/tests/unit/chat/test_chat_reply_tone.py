from __future__ import annotations

from app.services.chat.presentation import reply_tone


def test_compose_variant_is_deterministic_without_recent_history() -> None:
    variants = ["A", "B", "C"]
    first = reply_tone.compose_variant(
        user_text="show titanium labrets",
        key="catalog:default_reply",
        variants=variants,
        humanizer_enabled=True,
    )
    second = reply_tone.compose_variant(
        user_text="show titanium labrets",
        key="catalog:default_reply",
        variants=variants,
        humanizer_enabled=True,
    )
    assert first.variant_id == second.variant_id
    assert first.text == second.text


def test_compose_variant_anti_repeat_skips_recent_variant_when_available() -> None:
    variants = ["Option A", "Option B", "Option C"]
    base = reply_tone.compose_variant(
        user_text="show titanium labrets",
        key="clarify:structured_no_match",
        variants=variants,
        humanizer_enabled=True,
    )
    recent = [{"key": base.key, "style": base.style, "variant_id": base.variant_id}]
    next_choice = reply_tone.compose_variant(
        user_text="show titanium labrets",
        key="clarify:structured_no_match",
        variants=variants,
        recent=recent,
        anti_repeat_window=4,
        humanizer_enabled=True,
    )
    assert next_choice.variant_id != base.variant_id
    assert next_choice.anti_repeat_applied is True


def test_infer_style_maps_representative_inputs() -> None:
    assert reply_tone.infer_style("hey can u help me") == "casual"
    assert reply_tone.infer_style("show me titanium") == "direct"
    assert reply_tone.infer_style("Could you share your shipping policy?") == "neutral"


def test_strip_filler_removes_robotic_lead_ins() -> None:
    assert reply_tone.strip_filler("Here is what I found: We have options.") == "We have options."
    assert reply_tone.strip_filler("Understood. I can help with that.") == "I can help with that."
