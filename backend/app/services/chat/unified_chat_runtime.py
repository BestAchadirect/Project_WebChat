from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.core.config import settings
from app.schemas.chat import ChatComponent, ChatRequest, ChatResponse, ChatResponseMeta
from app.services.ai.llm_service import llm_service


async def process_chat(self, req: ChatRequest, channel: Optional[str] = None) -> ChatResponse:
    total_started = time.perf_counter()
    spans = self._new_latency_spans()

    run_id = f"chat-{int(time.time() * 1000)}"
    channel = channel or "widget"
    config_fingerprint = self._config_fingerprint()
    debug_meta: Dict[str, Any] = {
        "run_id": run_id,
        "route": "component_primary",
        "channel": channel,
        "config_fingerprint": config_fingerprint,
        "openai_timeout_seconds": float(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 12.0)),
        "openai_max_retries": int(getattr(settings, "OPENAI_MAX_RETRIES", 1)),
        "component_mode": "primary",
        "component_channel_allowed": True,
    }
    llm_service.begin_token_tracking()

    text = req.message or ""
    detail_mode_enabled = False
    conversation_id_value: int = int(req.conversation_id or 0) if req.conversation_id else 0

    def _safe_conversation_id(conv: Any, fallback: int = 0) -> int:
        try:
            return int(getattr(conv, "id", 0) or 0)
        except Exception:
            return int(fallback or 0)

    def _apply_component_debug(component_result: Any) -> None:
        debug_meta.update(dict(getattr(component_result, "debug", {}) or {}))
        debug_meta["component_mode"] = "primary"
        debug_meta["component_plan"] = list(debug_meta.get("component_plan") or [])
        external_call_counts = dict(getattr(component_result, "external_call_counts", {}) or {})
        debug_meta["external_call_counts"] = external_call_counts
        debug_meta["external_call_count"] = int(sum(external_call_counts.values()))
        debug_meta["llm_call_count"] = int(getattr(component_result, "llm_calls", 0) or 0)
        debug_meta["external_call_retries_used"] = 0

    async def _finalize_component_response(component_result: Any) -> ChatResponse:
        nonlocal detail_mode_enabled
        detail_mode_enabled = bool(getattr(component_result, "detail_mode_triggered", False))
        for span_key, span_value in dict(getattr(component_result, "spans", {}) or {}).items():
            self._add_latency_span(spans, str(span_key), float(span_value or 0.0))
        _apply_component_debug(component_result)
        token_usage = llm_service.consume_token_usage()
        return await self._finalize_with_latency(
            conversation_id=conversation_id_value,
            user_text=text,
            response=component_result.response,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
            channel=channel,
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_enabled,
            conversation_state=getattr(component_result, "conversation_state", None),
        )

    try:
        user = await self.get_or_create_user(req.user_id, req.customer_name, req.email)
        conversation = await self.get_or_create_conversation(user, req.conversation_id)
        conversation_id_value = _safe_conversation_id(conversation, conversation_id_value)

        component_started = time.perf_counter()
        component_result = await self._run_component_pipeline(
            request=req,
            conversation_id=conversation_id_value,
            run_id=run_id,
        )
        self._add_latency_span(
            spans,
            "component_pipeline_ms",
            (time.perf_counter() - component_started) * 1000.0,
        )
        return await _finalize_component_response(component_result)
    except Exception as exc:
        try:
            if hasattr(self.db, "rollback"):
                await self.db.rollback()
                debug_meta["component_pipeline_rollback"] = True
        except Exception as rollback_exc:
            debug_meta["component_pipeline_rollback"] = False
            debug_meta["component_pipeline_rollback_error"] = str(rollback_exc)

        debug_meta["component_mode"] = "error"
        debug_meta["component_pipeline_error"] = str(exc)

        token_usage = llm_service.consume_token_usage()
        self._log_latency_error(
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_enabled,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
            error=exc,
        )

        error_response = ChatResponse(
            conversation_id=conversation_id_value,
            reply_text="I could not process that request right now.",
            carousel_msg="",
            product_carousel=[],
            follow_up_questions=[],
            intent="fallback_general",
            sources=[],
            debug={},
            components=[
                ChatComponent(
                    type="error",
                    data={"message": "I could not process that request right now."},
                )
            ],
            meta=ChatResponseMeta(
                query_summary=text,
                latency_ms=0.0,
                source="error",
                llm_calls=0,
                embedding_calls=0,
            ),
        )
        return await self._finalize_with_latency(
            conversation_id=conversation_id_value,
            user_text=text,
            response=error_response,
            token_usage=token_usage if isinstance(token_usage, dict) else None,
            channel=channel,
            run_id=run_id,
            debug_meta=debug_meta,
            spans=spans,
            total_started=total_started,
            detail_mode_triggered=detail_mode_enabled,
        )
