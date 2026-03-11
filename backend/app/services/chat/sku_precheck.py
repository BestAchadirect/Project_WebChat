from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.core.config import settings
from app.schemas.chat import ProductCard
from app.services.chat.detail_query_parser import DetailQueryParser


def is_probable_sku_token(token: str) -> bool:
    cleaned = (token or "").strip().strip(".,!?;:'\"()[]{}<>")
    if not cleaned:
        return False
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,31}", cleaned):
        return False
    has_alpha = any(ch.isalpha() for ch in cleaned)
    has_digit = any(ch.isdigit() for ch in cleaned)
    if not has_alpha:
        return False
    if has_digit:
        return True
    return cleaned == cleaned.upper() and any(ch in "._-" for ch in cleaned)


def clean_code_candidate(token: str) -> str:
    return (token or "").strip(".,!?;:'\"()[]{}<>")


def extract_sku(text: str) -> Optional[str]:
    if not text:
        return None
    explicit = re.search(
        r"\bsku\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9._-]{1,31})\b",
        text,
        flags=re.IGNORECASE,
    )
    if explicit:
        candidate = str(explicit.group(1) or "").strip()
        if is_probable_sku_token(candidate):
            return candidate.lower()
    for candidate in re.findall(r"\b([A-Za-z0-9]{2,}(?:[-._][A-Za-z0-9]{1,})+)\b", text):
        normalized = str(candidate or "").strip()
        if is_probable_sku_token(normalized):
            return normalized.lower()
    return None


def looks_like_code(token: str) -> bool:
    if not token:
        return False
    t = token.strip()
    if " " in t:
        return False
    if len(t) < 3 or len(t) > 32:
        return False
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", t):
        return False
    has_digit = any(c.isdigit() for c in t)
    has_sep = any(c in "._-" for c in t)
    if has_sep and not has_digit and not is_probable_sku_token(t):
        return False
    is_all_upper = t.isupper()
    return has_digit or has_sep or (is_all_upper and len(t) <= 10)


def parse_enabled_channels(raw: str) -> set[str]:
    values = [str(item or "").strip().lower() for item in str(raw or "").split(",")]
    return {item for item in values if item}


def is_component_channel_allowed(*, channel: str) -> bool:
    configured = str(getattr(settings, "CHAT_COMPONENT_BUCKETS_ENABLED_CHANNELS", "widget") or "widget")
    allowed = parse_enabled_channels(configured)
    if not allowed:
        return False
    return str(channel or "").strip().lower() in allowed


def collect_sku_precheck_candidates(*, user_text: str) -> List[str]:
    text = str(user_text or "").strip()
    if not text:
        return []
    candidates: List[str] = []
    sku = extract_sku(text)
    if sku:
        candidates.append(clean_code_candidate(sku))
    for token in re.split(r"\s+", text):
        clean = clean_code_candidate(token)
        if looks_like_code(clean):
            candidates.append(clean)
    deduped: List[str] = []
    seen: set[str] = set()
    for raw in candidates:
        key = str(raw or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def sku_precheck_bypass_reason(*, user_text: str) -> str:
    normalized = " ".join(str(user_text or "").strip().lower().split())
    if not normalized:
        return "empty_query"
    if re.search(r"\b(compare|vs)\b", normalized):
        return "compare_requested"
    if re.search(r"\b(table|grid|spreadsheet)\b", normalized):
        return "table_requested"
    if re.search(r"\b(image|images|picture|photo)\b", normalized):
        return "image_requested"
    if re.search(r"\b(price|stock|availability|attribute|attributes|spec|specs|detail|details)\b", normalized):
        return "detail_control_requested"
    return ""


def should_run_sku_precheck(*, user_text: str, channel: str) -> Tuple[bool, str, List[str]]:
    text = str(user_text or "").strip()
    if not text:
        return False, "empty_query", []
    bypass_reason = sku_precheck_bypass_reason(user_text=text)
    if bypass_reason:
        return False, bypass_reason, []
    detail_guess = DetailQueryParser.parse(user_text=text, nlu_data={})
    if bool(detail_guess.is_detail_request):
        return False, "detail_request", []
    candidates = collect_sku_precheck_candidates(user_text=text)
    if len(candidates) != 1:
        return False, "requires_single_sku_token", candidates
    return True, "", candidates


async def cheap_sku_precheck(
    *,
    user_text: str,
    search_by_exact_sku,
    limit: int = 3,
    candidates: Optional[List[str]] = None,
) -> tuple[Optional[str], List[ProductCard]]:
    text = str(user_text or "").strip()
    if not text:
        return None, []
    deduped = [item for item in list(candidates or collect_sku_precheck_candidates(user_text=text)) if item]
    for candidate in deduped[:3]:
        try:
            cards = await search_by_exact_sku(sku=candidate, limit=max(1, int(limit)))
        except Exception:
            return None, []
        if cards:
            return candidate, cards
    return None, []
