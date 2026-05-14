from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.chat.presentation import component_contract
from app.services.chat.text_normalization import normalize_user_text

FAILURE_BUCKETS = {
    "no_answer",
    "clarification_loop",
    "mixed_intent_clarification",
    "hard_constraint_no_match",
    "related_product_anchor_reuse",
    "context_leak",
    "routing_mismatch",
    "catalog_unrelated_match",
    "other",
}

_PRODUCT_HINTS = (
    "product",
    "products",
    "jewelry",
    "body jewelry",
    "labret",
    "labrets",
    "barbell",
    "barbells",
    "ring",
    "rings",
    "hoop",
    "hoops",
    "septum",
    "nose",
    "nostril",
    "belly",
    "navel",
)

_POLICY_HINTS = (
    "steril",
    "autoclave",
    "shipping",
    "return",
    "refund",
    "payment",
    "warranty",
    "contact",
    "support",
    "store",
)

_RELATED_HINTS = (
    "similar product",
    "similar products",
    "similar option",
    "similar options",
    "related product",
    "related products",
    "related option",
    "related options",
    "more of this",
    "more like this",
    "like this",
    "like these",
    "same one",
    "same style",
    "what similar",
    "similar to",
)

_HARD_CONSTRAINT_HINTS = (
    "only ",
    "must be",
    "has to be",
    "not ",
    "without ",
    "under $",
    "less than $",
    "pre-sterilized",
    "pre sterilized",
    "sterilized",
    "sterilization",
    "sterile",
    "in stock",
    "available",
    "availability",
    "sku",
    "master code",
)


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    return bool(text and any(term in text for term in terms if term))


def _product_signal(text: str) -> bool:
    return _contains_any(text, _PRODUCT_HINTS)


def _policy_signal(text: str) -> bool:
    return _contains_any(text, _POLICY_HINTS)


def _related_signal(text: str) -> bool:
    return _contains_any(text, _RELATED_HINTS)


def _hard_constraint_signal(text: str) -> bool:
    return _contains_any(text, _HARD_CONSTRAINT_HINTS)


def _clarify_text(text: str) -> bool:
    return _contains_any(
        text,
        (
            "which product",
            "which one",
            "which item",
            "which detail",
            "which size",
            "which piece",
            "what do you mean",
            "could you clarify",
            "please clarify",
        ),
    )


def _response_text(response: Any) -> str:
    if response is None:
        return ""
    text = str(getattr(response, "reply_text", "") or "").strip()
    if text:
        return text
    return str(component_contract.assistant_text_from_response(response) or "").strip()


@dataclass(frozen=True)
class FailureAnalysis:
    bucket: str
    confidence: float
    reason: str
    suggested_action: str
    severity: str = "review"
    signals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bucket": self.bucket,
            "confidence": float(self.confidence),
            "reason": self.reason,
            "suggested_action": self.suggested_action,
            "severity": self.severity,
            "signals": list(self.signals),
        }


def classify_failure(
    *,
    user_text: str,
    response: Any,
    chat_metrics: Mapping[str, Any] | None = None,
) -> FailureAnalysis:
    text = normalize_user_text(user_text)
    reply = normalize_user_text(_response_text(response))
    metrics = dict(chat_metrics or {})
    debug = dict(getattr(response, "debug", {}) or {})

    workflow = str(metrics.get("workflow") or metrics.get("response_workflow") or "").strip().lower()
    grounding_status = str(metrics.get("grounding_status") or "").strip().lower()
    grounding_action = str(metrics.get("grounding_safe_action") or "").strip().lower()
    status = str(metrics.get("status") or "").strip().lower()
    clarification_count = int(debug.get("clarification_loop_count") or 0)
    context_merge = bool(
        metrics.get("conversation_state_filter_merge_applied")
        or debug.get("conversation_state_filter_merge_applied")
    )
    context_action = str(debug.get("context_action") or "").strip().lower()
    context_followup = bool(debug.get("context_related_product_followup_used"))
    response_product_count = int(metrics.get("product_count") or 0)
    response_has_products = bool(metrics.get("has_products") or response_product_count > 0)
    response_has_clarify = bool("clarify" in reply or grounding_action == "clarify")

    signals: List[str] = []
    if _product_signal(text):
        signals.append("product_signal")
    if _policy_signal(text):
        signals.append("policy_signal")
    if _related_signal(text):
        signals.append("related_followup_signal")
    if _hard_constraint_signal(text):
        signals.append("hard_constraint_signal")
    if _clarify_text(reply):
        signals.append("clarification_reply")
    if clarification_count:
        signals.append(f"clarification_loop_count={clarification_count}")
    if context_merge:
        signals.append("context_merge_applied")
    if context_action:
        signals.append(f"context_action={context_action}")

    if not reply:
        return FailureAnalysis(
            bucket="no_answer",
            confidence=0.99,
            reason="assistant returned no answer text",
            suggested_action="Verify retrieval and response building for the selected workflow.",
            severity="high",
            signals=signals,
        )

    if clarification_count >= 2:
        return FailureAnalysis(
            bucket="clarification_loop",
            confidence=0.97,
            reason="same clarification task reached the loop limit",
            suggested_action="Stop asking again and return the safest broad results or a single concise fallback question.",
            severity="high",
            signals=signals,
        )

    if workflow in {"knowledge", "fallback"} and _product_signal(text) and _policy_signal(text):
        return FailureAnalysis(
            bucket="mixed_intent_clarification",
            confidence=0.92,
            reason="product and policy terms were both present, so the bot asked/answered from the wrong branch",
            suggested_action="Split the request into product and policy parts, then answer only the grounded part or ask one focused clarification.",
            severity="medium",
            signals=signals,
        )

    if workflow == "catalog" and grounding_status in {"unrelated", "weak"} and response_has_products:
        if _related_signal(text) or context_followup:
            return FailureAnalysis(
                bucket="related_product_anchor_reuse",
                confidence=0.93,
                reason="a related-product follow-up reused the current anchor instead of excluding it",
                suggested_action="Use the current product as the seed, but exclude the anchor/master code from the similar-product results.",
                severity="high",
                signals=signals,
            )
        if context_merge:
            return FailureAnalysis(
                bucket="context_leak",
                confidence=0.9,
                reason="conversation state was merged into a search that did not actually match the new request",
                suggested_action="Reset stale filters on topic switch and require explicit reuse only for true follow-ups.",
                severity="high",
                signals=signals,
            )
        if _hard_constraint_signal(text):
            return FailureAnalysis(
                bucket="hard_constraint_no_match",
                confidence=0.95,
                reason="the request carried hard constraints that the catalog could not satisfy exactly",
                suggested_action="Keep the hard constraint intact, label returned products as alternatives, and name the missing exact constraint.",
                severity="high",
                signals=signals,
            )
        return FailureAnalysis(
            bucket="catalog_unrelated_match",
            confidence=0.78,
            reason="catalog returned products, but grounding still considered them unrelated or weak",
            suggested_action="Tighten hard-gate filtering before response generation and be explicit that the results are approximate.",
            severity="medium",
            signals=signals,
        )

    if workflow not in {"catalog", "knowledge"} and _product_signal(text):
        return FailureAnalysis(
            bucket="routing_mismatch",
            confidence=0.8,
            reason="the user sounded product-related, but the request did not stay on the catalog path",
            suggested_action="Review routing and intent classification for product terms and follow-up phrasing.",
            severity="medium",
            signals=signals,
        )

    if response_has_clarify and _product_signal(text):
        return FailureAnalysis(
            bucket="mixed_intent_clarification",
            confidence=0.72,
            reason="the bot asked for clarification on a product-like request",
            suggested_action="Use the search path if the request is searchable enough; otherwise ask one focused question only once.",
            severity="medium",
            signals=signals,
        )

    return FailureAnalysis(
        bucket="other",
        confidence=0.5,
        reason="no high-confidence failure pattern matched",
        suggested_action="Review the turn manually and add a regression case if it represents a recurring pattern.",
        severity="low",
        signals=signals,
    )

