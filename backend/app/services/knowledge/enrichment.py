from __future__ import annotations

import json
from typing import Any, Dict, Sequence, Tuple

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.knowledge import KnowledgeChunkEnrichment
from app.services.ai.llm_service import llm_service
from app.services.knowledge.tagging import build_knowledge_chunk_tags
from app.utils.datetime import utc_now, utc_now_iso


def _normalize_text(text: str | None) -> str:
    return " ".join(str(text or "").strip().split())


def _truncate_to_sentence(text: str, *, limit: int = 220) -> str:
    cleaned = _normalize_text(text)
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    for punct in (". ", "? ", "! "):
        index = cut.rfind(punct)
        if index >= 80:
            return cut[: index + 1].strip()
    return cut.rstrip(" ,;:-") + "..."


def build_knowledge_chunk_summary_fallback(
    *,
    article_title: str | None,
    article_category: str | None,
    chunk_text: str | None,
    tags: Sequence[str] | None = None,
) -> str:
    title = _normalize_text(article_title)
    category = _normalize_text(article_category)
    snippet = _truncate_to_sentence(chunk_text or "", limit=240)
    tag_text = ", ".join([tag for tag in list(tags or [])[:3] if tag])
    prefix_parts = [part for part in (title, category) if part]
    prefix = " - ".join(prefix_parts)
    if snippet and prefix:
        base = f"{prefix}: {snippet}"
    elif snippet:
        base = snippet
    elif prefix:
        base = prefix
    else:
        base = "Knowledge chunk"
    if tag_text:
        return f"{base} [{tag_text}]"
    return base


async def generate_knowledge_chunk_summary(
    *,
    article_title: str | None,
    article_category: str | None,
    chunk_text: str,
    tags: Sequence[str] | None = None,
    model: str | None = None,
) -> Tuple[str, Dict[str, Any]]:
    summary_model = str(model or getattr(settings, "OPENAI_MODEL", "")).strip() or getattr(settings, "OPENAI_MODEL", "")
    system_prompt = (
        "You summarize a knowledge base chunk for retrieval in a jewelry ecommerce assistant. "
        "Return strict JSON with keys: summary, confidence. "
        "Write one concise sentence, ideally 12-25 words, that captures the user-facing meaning of the chunk. "
        "Preserve exact policy limits, contact details, and factual constraints when present. "
        "Do not invent facts or product claims."
    )
    user_payload = {
        "article_title": _normalize_text(article_title),
        "article_category": _normalize_text(article_category),
        "chunk_text": _normalize_text(chunk_text),
        "tags": list(tags or []),
    }
    try:
        data = await llm_service.generate_chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
            ],
            model=summary_model,
            temperature=0.0,
            max_tokens=120,
            usage_kind="knowledge_chunk_summary",
        )
        summary = _normalize_text(data.get("summary"))
        if not summary:
            summary = build_knowledge_chunk_summary_fallback(
                article_title=article_title,
                article_category=article_category,
                chunk_text=chunk_text,
                tags=tags,
            )
        meta = {
            "source": "llm",
            "model": summary_model,
            "confidence": float(data.get("confidence") or 0.0),
            "generated_at": utc_now_iso(),
        }
        return summary, meta
    except Exception:
        summary = build_knowledge_chunk_summary_fallback(
            article_title=article_title,
            article_category=article_category,
            chunk_text=chunk_text,
            tags=tags,
        )
        meta = {
            "source": "fallback",
            "model": summary_model,
            "generated_at": utc_now_iso(),
        }
        return summary, meta


async def upsert_knowledge_chunk_enrichment(
    db: AsyncSession,
    *,
    chunk_id,
    summary_text: str,
    summary_meta: Dict[str, Any],
    generated_by: str | None = None,
) -> None:
    stmt = (
        pg_insert(KnowledgeChunkEnrichment)
        .values(
            chunk_id=chunk_id,
            summary_text=summary_text,
            summary_meta=summary_meta,
            generated_by=generated_by,
        )
        .on_conflict_do_update(
            index_elements=[KnowledgeChunkEnrichment.chunk_id],
            set_={
                "summary_text": summary_text,
                "summary_meta": summary_meta,
                "generated_by": generated_by,
                "updated_at": utc_now(),
            },
        )
    )
    await db.execute(stmt)


async def enrich_chunk(
    *,
    db: AsyncSession,
    chunk_id,
    article_title: str | None,
    article_category: str | None,
    chunk_text: str,
    generated_by: str | None = None,
) -> Dict[str, Any]:
    tags = build_knowledge_chunk_tags(
        article_title=article_title,
        article_category=article_category,
        chunk_text=chunk_text,
    )
    summary_text, summary_meta = await generate_knowledge_chunk_summary(
        article_title=article_title,
        article_category=article_category,
        chunk_text=chunk_text,
        tags=tags,
    )
    summary_meta = {**summary_meta, "tags": list(tags)}
    await upsert_knowledge_chunk_enrichment(
        db,
        chunk_id=chunk_id,
        summary_text=summary_text,
        summary_meta=summary_meta,
        generated_by=generated_by,
    )
    return {"tags": tags, "summary_text": summary_text, "summary_meta": summary_meta}
