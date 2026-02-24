from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

from app.services.imports.knowledge.chunking import chunk_text


def parse_csv_knowledge(
    content: bytes,
    *,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> List[Dict[str, Any]]:
    text_content = content.decode("utf-8-sig")
    csv_reader = csv.DictReader(io.StringIO(text_content))
    items: List[Dict[str, Any]] = []
    for row in csv_reader:
        if row.get("title") and row.get("content"):
            full_text = row["content"].strip()
            chunks = chunk_text(full_text, chunk_size=chunk_size, overlap=overlap)
            items.append(
                {
                    "title": row["title"].strip(),
                    "full_text": full_text,
                    "chunks": chunks,
                    "category": row.get("category", "general").strip(),
                    "url": row.get("url", "").strip() or None,
                }
            )
    return items
