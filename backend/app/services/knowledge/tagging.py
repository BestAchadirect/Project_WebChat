from __future__ import annotations

from typing import List

from app.services.chat.routing.signals import build_tag_matches, normalize_signal_text


def build_knowledge_chunk_tags(
    *,
    article_title: str | None,
    article_category: str | None,
    chunk_text: str | None,
) -> List[str]:
    text = " ".join(
        part for part in (
            normalize_signal_text(article_title),
            normalize_signal_text(article_category),
            normalize_signal_text(chunk_text),
        )
        if part
    )
    if not text:
        return []

    return list(build_tag_matches(text))


def build_knowledge_query_tags(query_text: str | None) -> List[str]:
    return build_knowledge_chunk_tags(
        article_title=None,
        article_category=None,
        chunk_text=query_text,
    )
