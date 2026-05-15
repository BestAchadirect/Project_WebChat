from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Sequence

from app.core.config import settings
from app.services.chat.text_normalization import normalize_user_text


def max_clarification_count() -> int:
    try:
        return max(1, int(getattr(settings, "CHAT_CLARIFICATION_LOOP_MAX", 2) or 2))
    except Exception:
        return 2


def _clean_text(value: Any, *, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _clean_missing_slots(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalize_user_text(str(value or ""))
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text[:80])
    return out


def load(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    task_id = _clean_text(raw.get("task_id"), limit=80)
    if not task_id:
        return {}
    try:
        count = int(raw.get("clarification_count", 0) or 0)
    except Exception:
        count = 0
    return {
        "task_id": task_id,
        "clarification_count": max(0, min(20, count)),
        "last_clarification_reason": _clean_text(raw.get("last_clarification_reason"), limit=120),
        "last_context_type": _clean_text(raw.get("last_context_type"), limit=80),
        "last_missing_slot": _clean_text(raw.get("last_missing_slot"), limit=80),
        "answered_missing_slot": bool(raw.get("answered_missing_slot")),
        "previous_missing_slots": _clean_missing_slots(raw.get("previous_missing_slots")),
        "previous_user_answer": _clean_text(raw.get("previous_user_answer"), limit=500),
        "merged_into_search_plan": bool(raw.get("merged_into_search_plan")),
    }


def build_task_id(
    *,
    intent: str,
    missing_slots: Sequence[str] | None = None,
    semantic_query: str = "",
    hard_constraints: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "intent": normalize_user_text(intent),
        "missing_slots": sorted(_clean_missing_slots(list(missing_slots or []))),
        "semantic_query": normalize_user_text(semantic_query),
        "hard_constraints": {
            normalize_user_text(key): normalize_user_text(value)
            for key, value in dict(hard_constraints or {}).items()
            if normalize_user_text(key) and normalize_user_text(value)
        },
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()[:16]
    return f"clarify:{digest}"


def current_count(raw: Any, *, task_id: str) -> int:
    state = load(raw)
    if not state or str(state.get("task_id") or "") != str(task_id or ""):
        return 0
    return int(state.get("clarification_count") or 0)


def should_stop_clarifying(raw: Any, *, task_id: str) -> bool:
    return current_count(raw, task_id=task_id) >= max_clarification_count()


def record_clarification(
    raw: Any,
    *,
    task_id: str,
    reason: str,
    missing_slots: Sequence[str] | None = None,
    context_type: str = "",
    missing_slot: str = "",
) -> Dict[str, Any]:
    existing = load(raw)
    same_task = bool(existing and str(existing.get("task_id") or "") == str(task_id or ""))
    count = int(existing.get("clarification_count") or 0) if same_task else 0
    return {
        "task_id": _clean_text(task_id, limit=80),
        "clarification_count": count + 1,
        "last_clarification_reason": _clean_text(reason, limit=120),
        "last_context_type": _clean_text(context_type, limit=80),
        "last_missing_slot": _clean_text(missing_slot, limit=80),
        "answered_missing_slot": False,
        "previous_missing_slots": _clean_missing_slots(list(missing_slots or [])),
        "previous_user_answer": str(existing.get("previous_user_answer") or "") if same_task else "",
        "merged_into_search_plan": False,
    }


def record_answer_merged(raw: Any, *, user_answer: str) -> Dict[str, Any]:
    existing = load(raw)
    if not existing:
        return {}
    existing["previous_user_answer"] = _clean_text(user_answer, limit=500)
    existing["merged_into_search_plan"] = True
    existing["answered_missing_slot"] = True
    return existing
