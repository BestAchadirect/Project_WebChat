from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Tuple


LocalizeTextFn = Callable[[str], Awaitable[str]]


class ResponseConsistencyPolicy:
    NO_MATCH_MARKERS = (
        "couldn't find",
        "could not find",
        "can't find",
        "cannot find",
        "didn't find",
        "did not find",
        "no match",
        "not in our current offerings",
        "don't have enough information",
        "do not have enough information",
        "check our catalog",
        "email sales@achadirect.com",
    )
    DEFAULT_PRODUCT_REPLY = "I found related products that may match your request. Please check the options below."
    DEFAULT_CAROUSEL_HINT = "Check them out below."

    @classmethod
    def is_no_match_reply_text(cls, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        return any(marker in lowered for marker in cls.NO_MATCH_MARKERS)

    @classmethod
    async def ensure_consistent_reply(
        cls,
        *,
        reply_data: Dict[str, Any],
        has_products: bool,
        localize_text: LocalizeTextFn,
    ) -> Dict[str, Any]:
        if not has_products:
            return dict(reply_data or {})

        fixed = dict(reply_data or {})
        reply_text = str(fixed.get("reply") or "").strip()
        if not reply_text or cls.is_no_match_reply_text(reply_text):
            fixed["reply"] = await localize_text(cls.DEFAULT_PRODUCT_REPLY)

        carousel_hint = str(fixed.get("carousel_hint") or "").strip()
        if not carousel_hint:
            fixed["carousel_hint"] = await localize_text(cls.DEFAULT_CAROUSEL_HINT)
        return fixed

    @classmethod
    async def normalize_cached_response(
        cls,
        *,
        reply_text: str,
        carousel_msg: str,
        has_products: bool,
        localize_text: LocalizeTextFn,
    ) -> Tuple[str, str]:
        if not has_products:
            return reply_text, carousel_msg
        fixed_reply = str(reply_text or "")
        fixed_hint = str(carousel_msg or "")
        if cls.is_no_match_reply_text(fixed_reply):
            fixed_reply = await localize_text(cls.DEFAULT_PRODUCT_REPLY)
            if not fixed_hint.strip():
                fixed_hint = await localize_text(cls.DEFAULT_CAROUSEL_HINT)
        return fixed_reply, fixed_hint
