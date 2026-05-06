from __future__ import annotations

from typing import Any, Dict, Optional


AMBIGUITY_FAMILY_KEYS = (
    "condition",
    "material",
    "stone",
    "finish",
    "measurement",
    "compatibility",
    "body_part",
    "policy",
)

def _build_family_policy(
    *,
    family: str,
    block_retrieval: bool,
    message_key: str,
    message_hint: str,
) -> Dict[str, Any]:
    return {
        "focus_family": family,
        "block_retrieval": block_retrieval,
        "reason": "semantic_concept_unclear",
        "message_key": message_key,
        "message_hint": str(message_hint or "").strip(),
        "questions": [],
        "suggestions": [],
    }


_AMBIGUITY_REGISTRY: Dict[str, Dict[str, Any]] = {
    "condition": _build_family_policy(
        family="condition",
        block_retrieval=True,
        message_key="clarify:semantic_concept_unclear:condition",
        message_hint="What condition are you looking for?",
    ),
    "material": _build_family_policy(
        family="material",
        block_retrieval=False,
        message_key="clarify:semantic_concept_unclear:material",
        message_hint="What material are you looking for?",
    ),
    "stone": _build_family_policy(
        family="stone",
        block_retrieval=False,
        message_key="clarify:semantic_concept_unclear:stone",
        message_hint="What stone type are you looking for?",
    ),
    "finish": _build_family_policy(
        family="finish",
        block_retrieval=False,
        message_key="clarify:semantic_concept_unclear:finish",
        message_hint="What finish do you want?",
    ),
    "measurement": _build_family_policy(
        family="measurement",
        block_retrieval=False,
        message_key="clarify:semantic_concept_unclear:measurement",
        message_hint="What size or gauge are you looking for?",
    ),
    "compatibility": _build_family_policy(
        family="compatibility",
        block_retrieval=False,
        message_key="clarify:semantic_concept_unclear:compatibility",
        message_hint="What should this be compatible with?",
    ),
    "body_part": _build_family_policy(
        family="body_part",
        block_retrieval=True,
        message_key="clarify:semantic_concept_unclear:body_part",
        message_hint="Which body part are you shopping for?",
    ),
    "policy": _build_family_policy(
        family="policy",
        block_retrieval=False,
        message_key="clarify:semantic_concept_unclear:policy",
        message_hint="Which policy detail do you need?",
    ),
}


def normalize_focus_key(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return "_".join(part for part in raw.replace("-", "_").split() if part)


def get_ambiguity_policy(focus: Any) -> Optional[Dict[str, Any]]:
    key = normalize_focus_key(focus)
    if not key:
        return None
    entry = _AMBIGUITY_REGISTRY.get(key)
    if not isinstance(entry, dict):
        return None
    policy = dict(entry)
    policy.setdefault("focus_key", normalize_focus_key(focus))
    policy.setdefault("focus_family", key)
    return policy


def ambiguity_blocks_retrieval(focus: Any) -> bool:
    entry = get_ambiguity_policy(focus)
    if not entry:
        return False
    return bool(entry.get("block_retrieval", False))
