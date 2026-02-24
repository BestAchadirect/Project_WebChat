import pytest

from app.services.chat.response_consistency import ResponseConsistencyPolicy


@pytest.mark.regression
@pytest.mark.asyncio
async def test_reply_consistency_rewrites_not_found_when_products_exist() -> None:
    async def passthrough(text: str) -> str:
        return text

    fixed = await ResponseConsistencyPolicy.ensure_consistent_reply(
        reply_data={
            "reply": "I couldn't find specific 16 gauge options in our current offerings.",
            "carousel_hint": "",
        },
        has_products=True,
        localize_text=passthrough,
    )

    assert fixed["reply"] == ResponseConsistencyPolicy.DEFAULT_PRODUCT_REPLY
    assert fixed["carousel_hint"] == ResponseConsistencyPolicy.DEFAULT_CAROUSEL_HINT


@pytest.mark.regression
@pytest.mark.asyncio
async def test_cached_response_normalization_keeps_existing_hint() -> None:
    async def passthrough(text: str) -> str:
        return text

    reply, hint = await ResponseConsistencyPolicy.normalize_cached_response(
        reply_text="Could not find matching products.",
        carousel_msg="Already has hint",
        has_products=True,
        localize_text=passthrough,
    )

    assert reply == ResponseConsistencyPolicy.DEFAULT_PRODUCT_REPLY
    assert hint == "Already has hint"
