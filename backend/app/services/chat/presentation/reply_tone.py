from __future__ import annotations

from dataclasses import dataclass
import re
import zlib
from typing import Any, Dict, List, Sequence


def normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().split())


@dataclass(frozen=True)
class ToneDecision:
    text: str
    key: str
    style: str
    variant_id: int
    anti_repeat_applied: bool = False
    filler_stripped: bool = False


def infer_style(user_text: str) -> str:
    text = " ".join(str(user_text or "").strip().lower().split())
    if not text:
        return "neutral"
    casual_patterns = (
        r"\bhey\b",
        r"\bhi\b",
        r"\byo\b",
        r"\bpls\b",
        r"\bplease\b",
        r"\bthx\b",
        r"\bthanks\b",
        r"\bcan u\b",
        r"\bwanna\b",
    )
    if any(re.search(pattern, text) for pattern in casual_patterns):
        return "casual"
    direct_markers = (
        "show ",
        "give ",
        "need ",
        "want ",
        "find ",
        "check ",
    )
    if text.startswith(direct_markers):
        return "direct"
    return "neutral"


def _sentences(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalize_text(text)) if part.strip()]


def _apply_length_limits(*, text: str, max_sentences: int, max_chars: int) -> str:
    limited = normalize_text(text)
    sentence_cap = max(1, int(max_sentences or 1))
    char_cap = max(40, int(max_chars or 40))
    parts = _sentences(limited)
    if parts:
        limited = " ".join(parts[:sentence_cap])
    if len(limited) > char_cap:
        trimmed = limited[:char_cap].rstrip()
        if " " in trimmed:
            trimmed = trimmed.rsplit(" ", 1)[0]
        limited = trimmed.rstrip(" ,;:.!?") + "..."
    return normalize_text(limited)


def normalize_recent(values: Sequence[Dict[str, Any]] | None, *, max_items: int = 8) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not values:
        return out
    for item in list(values):
        if not isinstance(item, dict):
            continue
        key = normalize_text(str(item.get("key") or "")).lower()
        style = normalize_text(str(item.get("style") or "")).lower()
        if style not in {"casual", "neutral", "direct"}:
            style = "neutral"
        try:
            variant_id = int(item.get("variant_id", -1))
        except Exception:
            variant_id = -1
        if not key or variant_id < 0:
            continue
        out.append({"key": key, "style": style, "variant_id": int(variant_id)})
    return out[-max(1, int(max_items)) :]


def push_recent(
    recent: Sequence[Dict[str, Any]] | None,
    *,
    decision: ToneDecision,
    max_items: int = 8,
) -> List[Dict[str, Any]]:
    normalized = normalize_recent(recent, max_items=max_items)
    if decision.key and int(decision.variant_id) >= 0:
        normalized.append(
            {
                "key": normalize_text(decision.key).lower(),
                "style": normalize_text(decision.style).lower() or "neutral",
                "variant_id": int(decision.variant_id),
            }
        )
    return normalize_recent(normalized, max_items=max_items)


def compose_variant(
    *,
    user_text: str,
    key: str,
    variants: Sequence[str],
    recent: Sequence[Dict[str, Any]] | None = None,
    anti_repeat_window: int = 0,
    humanizer_enabled: bool = False,
    max_sentences: int = 2,
    max_chars: int = 220,
) -> ToneDecision:
    options = [normalize_text(item) for item in list(variants or []) if normalize_text(item)]
    if not options:
        return ToneDecision(text="", key=normalize_text(key).lower(), style=infer_style(user_text), variant_id=-1)

    normalized_key = normalize_text(key).lower()
    style = infer_style(user_text)
    seed = f"{normalize_text(user_text).lower()}|{normalized_key}|{style}"
    index = int(zlib.crc32(seed.encode("utf-8")) % len(options))
    anti_repeat_applied = False

    if humanizer_enabled and int(anti_repeat_window or 0) > 0:
        history = normalize_recent(recent, max_items=max(anti_repeat_window, 1))
        blocked = {
            int(item.get("variant_id"))
            for item in history[-int(anti_repeat_window) :]
            if str(item.get("key") or "").strip().lower() == normalized_key
        }
        if blocked and len(blocked) < len(options) and index in blocked:
            for offset in range(1, len(options) + 1):
                candidate = (index + offset) % len(options)
                if candidate not in blocked:
                    index = candidate
                    anti_repeat_applied = True
                    break

    text = options[index]
    filler_stripped = False
    if humanizer_enabled:
        stripped = strip_filler(text)
        filler_stripped = stripped != text
        text = stripped
        text = _apply_length_limits(
            text=text,
            max_sentences=max_sentences,
            max_chars=max_chars,
        )

    return ToneDecision(
        text=text,
        key=normalized_key,
        style=style,
        variant_id=index,
        anti_repeat_applied=anti_repeat_applied,
        filler_stripped=filler_stripped,
    )


def pick_variant(*, user_text: str, key: str, variants: Sequence[str]) -> str:
    return compose_variant(
        user_text=user_text,
        key=key,
        variants=variants,
        humanizer_enabled=False,
        anti_repeat_window=0,
        max_sentences=4,
        max_chars=480,
    ).text


def strip_filler(text: str) -> str:
    cleaned = normalize_text(text)
    patterns = (
        r"^here is what i found:\s*",
        r"^based on the information provided,\s*",
        r"^i got it\.\s*",
        r"^understood\.\s*",
        r"^thanks for the details\.\s*",
    )
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return normalize_text(cleaned)
