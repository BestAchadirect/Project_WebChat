from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings
from app.services.chat import conversation_state


_CONFIRMATION_PHRASES: Sequence[str] = (
    "are you sure",
    "really",
    "wrong info",
    "wrong information",
    "this is not ok",
    "this is not okay",
    "not correct",
    "incorrect",
    "confusing",
    "confused",
)
_STOCK_DISPUTE_PHRASES: Sequence[str] = (
    "out of stock",
    "not available",
    "inventory wrong",
    "inventory mismatch",
    "stock is wrong",
    "should update your inventory",
)
_STOCK_TERMS: Sequence[str] = (
    "stock",
    "inventory",
    "availability",
    "available",
    "in stock",
    "out of stock",
)
_DISPUTE_MARKERS: Sequence[str] = (
    "wrong",
    "not ok",
    "not okay",
    "not correct",
    "incorrect",
    "confusing",
    "confused",
    "you said",
    "you told",
    "i heard",
)
_INVENTORY_WORKFLOWS = {"catalog", "recommendation"}


@dataclass(frozen=True)
class ChallengeContextDecision:
    mode: str = "none"
    intent: str = "none"
    reason: str = ""
    target_sku: str = ""
    base_question: str = ""

    @property
    def active(self) -> bool:
        return self.mode != "none"


def _normalize_text(text: str) -> str:
    lowered = str(text or "").strip().lower()
    lowered = re.sub(r"[\s]+", " ", lowered)
    return lowered


def _channel_enabled(*, channel: str | None) -> bool:
    if not bool(getattr(settings, "CHAT_CHALLENGE_CONTEXT_ENABLED", False)):
        return False
    allowed_raw = str(getattr(settings, "CHAT_CHALLENGE_CONTEXT_CHANNELS", "") or "")
    allowed = {part.strip().lower() for part in allowed_raw.split(",") if part.strip()}
    if not allowed:
        return True
    return str(channel or "").strip().lower() in allowed


def _detect_intent(*, normalized_text: str) -> str:
    if not normalized_text:
        return "none"
    has_stock_term = any(token in normalized_text for token in _STOCK_TERMS)
    has_dispute_marker = any(token in normalized_text for token in _DISPUTE_MARKERS)
    if has_stock_term and has_dispute_marker:
        return "stock_dispute"
    if any(token in normalized_text for token in _STOCK_DISPUTE_PHRASES):
        return "stock_dispute"
    if any(token in normalized_text for token in _CONFIRMATION_PHRASES):
        return "confirmation_challenge"
    if "sure" in normalized_text and "?" in str(normalized_text):
        return "confirmation_challenge"
    return "none"


def detect_challenge_intent(*, user_text: str) -> str:
    normalized_text = _normalize_text(user_text)
    return _detect_intent(normalized_text=normalized_text)


def _resolve_history_sku(history: Sequence[Dict[str, Any]]) -> str:
    for item in reversed(list(history or [])):
        if str(item.get("role") or "").strip().lower() != "assistant":
            continue
        product_data = item.get("product_data")
        if not isinstance(product_data, list):
            continue
        for raw in product_data:
            if not isinstance(raw, dict):
                continue
            sku = str(raw.get("sku") or "").strip()
            if sku:
                return sku
    return ""


def _resolve_sku(*, state: Dict[str, Any], history: Sequence[Dict[str, Any]], sku_tokens: Sequence[str]) -> str:
    explicit = ""
    if list(sku_tokens or []):
        explicit = str(list(sku_tokens)[0] or "").strip()
    if explicit:
        return explicit

    claim = state.get("last_inventory_claim")
    if isinstance(claim, dict):
        claimed_sku = str(claim.get("sku") or "").strip()
        if claimed_sku:
            return claimed_sku

    last_skus = state.get("last_product_skus")
    if isinstance(last_skus, list):
        for raw in last_skus:
            sku = str(raw or "").strip()
            if sku:
                return sku

    return _resolve_history_sku(history)


def _resolve_base_question(*, state: Dict[str, Any], history: Sequence[Dict[str, Any]]) -> str:
    last_user_query = str(state.get("last_user_query") or "").strip()
    if last_user_query:
        return last_user_query
    last_refined_query = str(state.get("last_refined_query") or "").strip()
    if last_refined_query:
        return last_refined_query

    for item in reversed(list(history or [])):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        content = str(item.get("content") or "").strip()
        if content:
            return content
    return ""


def resolve_challenge_context(
    *,
    user_text: str,
    channel: str | None,
    state_raw: Any,
    history: Sequence[Dict[str, Any]],
    sku_tokens: Sequence[str],
) -> ChallengeContextDecision:
    if not _channel_enabled(channel=channel):
        return ChallengeContextDecision()

    normalized_text = _normalize_text(user_text)
    intent = _detect_intent(normalized_text=normalized_text)
    if intent == "none":
        return ChallengeContextDecision()

    state = conversation_state.load_state(state_raw)
    target_sku = _resolve_sku(state=state, history=history, sku_tokens=sku_tokens)
    base_question = _resolve_base_question(state=state, history=history)
    last_workflow = str(state.get("last_workflow") or state.get("last_route") or "").strip().lower()

    if intent == "stock_dispute":
        if target_sku:
            return ChallengeContextDecision(
                mode="inventory_reverify",
                intent=intent,
                reason="stock_dispute_detected",
                target_sku=target_sku,
            )
        return ChallengeContextDecision(
            mode="needs_target_clarification",
            intent=intent,
            reason="stock_dispute_missing_target",
        )

    if last_workflow == "knowledge" and base_question:
        return ChallengeContextDecision(
            mode="knowledge_reconfirm",
            intent=intent,
            reason="confirmation_challenge_on_knowledge",
            base_question=base_question,
        )

    if target_sku and (
        any(token in normalized_text for token in _STOCK_TERMS) or last_workflow in _INVENTORY_WORKFLOWS
    ):
        return ChallengeContextDecision(
            mode="inventory_reverify",
            intent=intent,
            reason="confirmation_challenge_with_inventory_target",
            target_sku=target_sku,
        )

    if base_question:
        return ChallengeContextDecision(
            mode="knowledge_reconfirm",
            intent=intent,
            reason="confirmation_challenge_with_base_question",
            base_question=base_question,
        )

    if target_sku:
        return ChallengeContextDecision(
            mode="inventory_reverify",
            intent=intent,
            reason="confirmation_challenge_with_sku",
            target_sku=target_sku,
        )

    return ChallengeContextDecision(
        mode="needs_target_clarification",
        intent=intent,
        reason="confirmation_challenge_missing_context",
    )


def is_challenge_context_enabled(*, channel: str | None) -> bool:
    return _channel_enabled(channel=channel)
