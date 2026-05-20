from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Sequence

from app.db.session import AsyncSessionLocal
from app.schemas.chat import ChatRequest
from app.services.chat.service import ChatService


CAPTURE_SUPPORTED_KINDS = {"response_contract"}
_TRACE_SNAPSHOT_KEYS = (
    "run_id",
    "route",
    "workflow",
    "execution_mode",
    "grounding_status",
    "fallback_used",
    "fallback_reason",
    "clarification_required",
    "clarification_reason",
    "retrieved_products",
    "retrieved_sources",
)


def filter_capture_cases(cases: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        dict(case or {})
        for case in list(cases or [])
        if str((case or {}).get("kind") or "").strip().lower() in CAPTURE_SUPPORTED_KINDS
    ]


def build_chat_request_from_case(case: Dict[str, Any]) -> ChatRequest:
    case_id = str(case.get("id") or "").strip() or "capture-case"
    inputs = dict(case.get("inputs") or {})
    message = str(inputs.get("message") or "").strip()
    if not message:
        raise ValueError(f"capture case {case_id!r} missing inputs.message")

    request_payload: Dict[str, Any] = {
        "user_id": str(inputs.get("user_id") or f"accuracy-{case_id}"),
        "customer_name": inputs.get("customer_name"),
        "email": inputs.get("email"),
        "conversation_id": inputs.get("conversation_id"),
        "message": message,
        "locale": str(inputs.get("locale") or "en-US"),
        "client_action": inputs.get("client_action"),
        "client_action_payload": dict(inputs.get("client_action_payload") or {}),
    }
    return ChatRequest.model_validate(request_payload)


async def capture_case_outputs(
    cases: Sequence[Dict[str, Any]],
    *,
    channel: str = "widget",
    db_session_factory: Callable[[], Awaitable[Any]] | Any = AsyncSessionLocal,
    service_cls: type[ChatService] = ChatService,
) -> Dict[str, Dict[str, Any]]:
    outputs: Dict[str, Dict[str, Any]] = {}
    for case in filter_capture_cases(cases):
        case_id = str(case.get("id") or "").strip()
        request = build_chat_request_from_case(case)
        async with db_session_factory() as db:
            service = service_cls(db)
            response = await service.process_chat(request, channel=channel)
            payload = response.model_dump(mode="json")
            trace_snapshot = build_harness_trace_snapshot(payload)
            if trace_snapshot:
                payload["harness_trace_snapshot"] = trace_snapshot
            outputs[case_id] = payload
    return outputs


def build_harness_trace_snapshot(response_payload: Dict[str, Any]) -> Dict[str, Any]:
    debug = response_payload.get("debug") if isinstance(response_payload, dict) else None
    debug_payload = dict(debug or {}) if isinstance(debug, dict) else {}
    raw_trace = debug_payload.get("harness_trace")
    if not isinstance(raw_trace, dict):
        return {}

    snapshot: Dict[str, Any] = {
        key: raw_trace.get(key)
        for key in _TRACE_SNAPSHOT_KEYS
        if raw_trace.get(key) not in (None, "")
    }
    tools = raw_trace.get("tools_called") if isinstance(raw_trace.get("tools_called"), list) else []
    clean_tools = [
        str(item or "").strip()
        for item in list(tools or [])
        if str(item or "").strip()
    ]
    if clean_tools:
        snapshot["tools_called"] = clean_tools[:10]
        snapshot["tool_count"] = len(clean_tools)
    errors = raw_trace.get("errors") if isinstance(raw_trace.get("errors"), list) else []
    warnings = raw_trace.get("warnings") if isinstance(raw_trace.get("warnings"), list) else []
    if errors:
        snapshot["error_count"] = len(errors)
    if warnings:
        snapshot["warning_count"] = len(warnings)
    metadata = raw_trace.get("metadata") if isinstance(raw_trace.get("metadata"), dict) else {}
    tool_events = metadata.get("tool_events") if isinstance(metadata.get("tool_events"), list) else []
    if tool_events:
        snapshot["tool_event_count"] = len(tool_events)
    timings = raw_trace.get("timings_ms") if isinstance(raw_trace.get("timings_ms"), dict) else {}
    if timings:
        snapshot["timing_steps"] = sorted(str(key) for key in timings.keys() if str(key).strip())
    return snapshot


def write_capture_results(path: str | Path, outputs: Dict[str, Dict[str, Any]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(outputs, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
