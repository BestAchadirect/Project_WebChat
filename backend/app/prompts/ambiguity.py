from __future__ import annotations

from typing import Any, Dict, Optional


_AMBIGUITY_REGISTRY: Dict[str, Dict[str, Any]] = {
    "sterilization_meaning": {
        "block_retrieval": True,
        "reason": "semantic_concept_unclear",
        "message_key": "clarify:semantic_concept_unclear:sterilization",
        "message_variants": [
            "Do you mean pre-sterilized jewelry, surgical steel jewelry, or sterile-packed products?",
            "When you say sterilization, do you mean pre-sterilized jewelry, surgical steel, or sterile-packed items?",
            "To narrow this down, do you mean pre-sterilized jewelry, surgical steel jewelry, or sterile-packed products?",
        ],
        "questions": ["Which sterilization-related option do you mean?"],
        "suggestions": [
            "Show surgical steel jewelry",
            "Show pre-sterilized jewelry",
            "Show sterile-packed products",
        ],
    }
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
    return dict(entry)


def ambiguity_blocks_retrieval(focus: Any) -> bool:
    entry = get_ambiguity_policy(focus)
    if not entry:
        return False
    return bool(entry.get("block_retrieval", False))
