from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Sequence

from app.db.session import AsyncSessionLocal
from app.schemas.chat import ChatRequest
from app.services.chat.service import ChatService


CAPTURE_SUPPORTED_KINDS = {"response_contract"}


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
            outputs[case_id] = response.model_dump(mode="json")
    return outputs


def write_capture_results(path: str | Path, outputs: Dict[str, Dict[str, Any]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(outputs, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
