from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.services.ai.llm_service import llm_service
from app.services.currency_service import currency_service
from app.services.chat.detail_query_parser import DetailQueryParser


def format_language_instruction(*, language: Optional[str], locale: Optional[str]) -> str:
    default_locale = str(getattr(settings, "DEFAULT_LOCALE", "en-US") or "en-US")
    language = (language or "").strip()
    locale = (locale or "").strip()
    if language and locale:
        if locale.lower() in language.lower():
            return language
        return f"{language} ({locale})"
    if language:
        return language
    if locale:
        return locale
    return default_locale


def looks_vague_query(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return True
    if len(normalized.split()) <= 2:
        return True
    vague_terms = {"something", "anything", "stuff", "maybe", "ideas", "help me choose"}
    return any(term in normalized for term in vague_terms)


def is_connectivity_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    signals = ("timeout", "connection", "connect", "dns", "network", "unreachable", "reset")
    if any(signal in name for signal in signals):
        return True
    return any(signal in msg for signal in signals)


def is_llm_textual_call(call_name: str) -> bool:
    normalized = str(call_name or "").strip().lower()
    return normalized in {"nlu", "llm_answer", "answer_polish", "ui_localization", "agentic_llm"}


def heuristic_nlu_fast_path(*, service: Any, user_text: str, locale: Optional[str]) -> Tuple[Optional[Dict[str, Any]], float]:
    if not bool(getattr(settings, "NLU_FAST_PATH_ENABLED", True)):
        return None, 0.0
    text = str(user_text or "").strip()
    if len(text) < 3:
        return None, 0.0

    detail_guess = DetailQueryParser.parse(user_text=text, nlu_data={})
    sku_token = service._extract_sku(text)
    explicit_product_signal = bool(
        sku_token
        or detail_guess.attribute_filters
        or service._infer_jewelry_type_filter(text)
    )
    if not explicit_product_signal:
        return None, 0.0

    normalized_locale = str(locale or "").strip() or "en-US"
    intent = "search_specific" if (sku_token or detail_guess.is_detail_request) else "browse_products"
    confidence = 0.6
    if sku_token:
        confidence = 0.99
    elif detail_guess.is_detail_request:
        confidence = 0.92
    elif detail_guess.attribute_filters:
        confidence = 0.88
    fast_path = {
        "language": "English",
        "locale": normalized_locale,
        "intent": intent,
        "show_products": True,
        "currency": "",
        "refined_query": text,
        "product_code": sku_token or "",
        "requested_fields": list(detail_guess.requested_fields),
        "attribute_filters": dict(detail_guess.attribute_filters),
        "wants_image": bool(detail_guess.wants_image),
        "nlu_fast_path": True,
        "nlu_heuristic_confidence": confidence,
    }
    return fast_path, confidence


async def run_external_call(
    *,
    service: Any,
    external_state: Dict[str, Any],
    call_name: str,
    call_factory,
    run_id: str,
    debug_meta: Dict[str, Any],
) -> Any:
    hard_llm_cap = max(0, int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0)))
    is_llm_call = is_llm_textual_call(call_name)
    if is_llm_call and hard_llm_cap > 0:
        current_llm_calls = int(external_state.get("llm_count", 0))
        if current_llm_calls >= hard_llm_cap:
            external_state["budget_exceeded_reason"] = "llm_call_cap"
            raise RuntimeError("llm call cap exceeded")

    budget = max(1, int(getattr(settings, "CHAT_EXTERNAL_CALL_BUDGET", 3)))
    if int(external_state.get("count", 0)) >= budget:
        external_state["budget_exceeded_reason"] = "external_call_budget"
        raise RuntimeError("external call budget exceeded")

    external_state["count"] = int(external_state.get("count", 0)) + 1
    if is_llm_call:
        external_state["llm_count"] = int(external_state.get("llm_count", 0)) + 1
    by_name = external_state.setdefault("by_name", {})
    by_name[call_name] = int(by_name.get(call_name, 0)) + 1
    timeout_seconds = max(0.1, float(getattr(settings, "CHAT_EXTERNAL_CALL_FAIL_FAST_SECONDS", 3.5)))
    retry_max = max(0, int(getattr(settings, "CHAT_EXTERNAL_CALL_RETRY_MAX", 1)))
    retries_used = 0
    last_error: Optional[Exception] = None

    for attempt in range(retry_max + 1):
        try:
            call_started = time.perf_counter()
            result = await asyncio.wait_for(call_factory(), timeout=timeout_seconds)
            elapsed_ms = (time.perf_counter() - call_started) * 1000.0
            if elapsed_ms > float(external_state.get("slowest_call_ms", 0.0)):
                external_state["slowest_call_ms"] = round(float(elapsed_ms), 2)
                external_state["slowest_call_name"] = call_name
            external_state["retries_used"] = int(external_state.get("retries_used", 0)) + retries_used
            return result
        except asyncio.TimeoutError as exc:
            last_error = exc
            retries_used += 1
            if attempt >= retry_max:
                external_state["budget_exceeded_reason"] = "external_timeout"
                raise
        except Exception as exc:
            last_error = exc
            if is_connectivity_error(exc):
                debug_meta["network_error_type"] = type(exc).__name__
                retries_used += 1
                if attempt < retry_max:
                    continue
                external_state["budget_exceeded_reason"] = "external_connectivity"
            raise

    if last_error:
        raise last_error
    raise RuntimeError("external call failed")


async def run_nlu(
    *,
    service: Any,
    user_text: str,
    history: List[Dict[str, str]] = None,
    locale: Optional[str],
    run_id: str,
    external_state: Dict[str, Any],
    debug_meta: Dict[str, Any],
) -> Dict[str, Any]:
    if not user_text or len(user_text.strip()) < 3:
        return {
            "language": "English",
            "locale": "en-US",
            "intent": "knowledge_query",
            "show_products": False,
            "currency": "",
            "requested_fields": [],
            "attribute_filters": {},
            "wants_image": False,
        }

    fast_path, confidence = heuristic_nlu_fast_path(service=service, user_text=user_text, locale=locale)
    threshold = float(getattr(settings, "CHAT_NLU_HEURISTIC_THRESHOLD", 0.85))
    hard_llm_cap = max(0, int(getattr(settings, "CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST", 0)))
    if hard_llm_cap == 1:
        if isinstance(fast_path, dict):
            debug_meta["nlu_fast_path_forced_by_llm_cap"] = True
            return fast_path
        normalized_locale = str(locale or "").strip() or "en-US"
        debug_meta["nlu_deterministic_fallback"] = True
        return {
            "language": "English",
            "locale": normalized_locale,
            "intent": "knowledge_query",
            "show_products": False,
            "currency": "",
            "refined_query": str(user_text or "").strip(),
            "product_code": "",
            "requested_fields": [],
            "attribute_filters": {},
            "wants_image": False,
            "nlu_fast_path": False,
            "nlu_heuristic_confidence": round(float(confidence), 3),
        }

    if isinstance(fast_path, dict) and float(confidence) >= threshold:
        service._log_event(
            run_id=run_id,
            location="chat_service.nlu.fast_path",
            data={
                "intent": fast_path.get("intent"),
                "show_products": fast_path.get("show_products"),
                "requested_fields": fast_path.get("requested_fields", []),
                "attribute_filters": fast_path.get("attribute_filters", {}),
                "confidence": round(float(confidence), 3),
                "threshold": round(float(threshold), 3),
            },
        )
        return fast_path

    supported = currency_service.supported_currencies()
    data = await run_external_call(
        service=service,
        external_state=external_state,
        call_name="nlu",
        call_factory=lambda: llm_service.run_nlu(
            user_message=user_text,
            history=history,
            locale=locale,
            supported_currencies=supported,
            model=getattr(settings, "NLU_MODEL", None),
            max_tokens=int(getattr(settings, "NLU_MAX_TOKENS", 250)),
        ),
        run_id=run_id,
        debug_meta=debug_meta,
    )
    if not isinstance(data, dict):
        data = {}

    raw_fields = data.get("requested_fields")
    if not isinstance(raw_fields, list):
        data["requested_fields"] = []
    else:
        data["requested_fields"] = [str(item).strip().lower() for item in raw_fields if str(item).strip()]

    raw_filters = data.get("attribute_filters")
    if not isinstance(raw_filters, dict):
        data["attribute_filters"] = {}
    else:
        clean_filters: Dict[str, str] = {}
        for key, value in raw_filters.items():
            clean_key = str(key or "").strip().lower()
            clean_val = str(value or "").strip()
            if clean_key and clean_val:
                clean_filters[clean_key] = clean_val
        data["attribute_filters"] = clean_filters

    data["wants_image"] = bool(data.get("wants_image", False))
    data["nlu_heuristic_confidence"] = round(float(confidence), 3)

    service._log_event(
        run_id=run_id,
        location="chat_service.nlu.run",
        data=data,
    )
    return data


async def resolve_reply_language(*, nlu_data: Dict[str, Any], user_text: str, locale: Optional[str], run_id: str) -> str:
    mode = str(getattr(settings, "CHAT_LANGUAGE_MODE", "auto") or "auto").lower()
    default_locale = str(getattr(settings, "DEFAULT_LOCALE", "en-US") or "en-US")
    locale = str(locale or "").strip() or None

    if mode == "fixed":
        return str(getattr(settings, "FIXED_REPLY_LANGUAGE", "") or "").strip() or default_locale

    if mode == "locale" and locale:
        return locale

    language = nlu_data.get("language")
    loc = nlu_data.get("locale")
    reply_language = format_language_instruction(language=language, locale=loc)

    if not reply_language or reply_language.lower() in {"unknown", "none"}:
        reply_language = locale or default_locale

    return reply_language


async def resolve_target_currency(*, nlu_data: Dict[str, Any], user_text: str) -> str:
    default_display = (
        getattr(settings, "PRICE_DISPLAY_CURRENCY", None)
        or getattr(settings, "BASE_CURRENCY", None)
        or "USD"
    )

    nlu_currency = str(nlu_data.get("currency") or "").strip().upper()
    if nlu_currency and currency_service.supports(nlu_currency):
        return nlu_currency

    heuristic = currency_service.extract_requested_currency(user_text)
    if heuristic and currency_service.supports(heuristic):
        return heuristic

    return default_display.upper()
