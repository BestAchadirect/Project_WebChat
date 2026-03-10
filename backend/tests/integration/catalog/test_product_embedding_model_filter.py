from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.services.catalog.product_search import CatalogProductSearchService


class _ExecuteResult:
    def all(self):
        return []


class _DbStub:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _ExecuteResult()


@pytest.mark.asyncio
async def test_vector_search_filters_only_configured_embedding_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "PRODUCT_EMBEDDING_MODEL", "text-embedding-3-small")
    db = _DbStub()
    service = CatalogProductSearchService(db=db)

    result = await service.vector_search(query_embedding=[0.01, 0.02], limit=5)

    assert result.cards == []
    assert db.statements, "expected at least one SQL statement"

    sql_text = str(db.statements[0]).lower()
    assert "product_embeddings.model" in sql_text
    assert " is null" not in sql_text
