from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_URL

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")

from app.core.config import settings
from app.db.base import Base
from app.models import (  # noqa: F401 - importing registers all metadata tables.
    KnowledgeArticle,
    KnowledgeChunk,
    KnowledgeChunkEnrichment,
    KnowledgeChunkTag,
    KnowledgeEmbedding,
    Product,
    ProductEmbedding,
    ProductGroup,
)
from app.models.product import StockStatus


SEED_PATH = Path(__file__).resolve().parents[1] / "regression" / "data" / "grounded_chat_seed.json"
SEED_NAMESPACE = "project-webchat-grounded-chat"


@dataclass(frozen=True)
class GroundedSeed:
    products: dict[str, dict[str, Any]]
    knowledge: dict[str, dict[str, Any]]


def _db_url_from_env() -> str:
    raw = str(os.environ.get("TEST_DATABASE_URL") or getattr(settings, "TEST_DATABASE_URL", "") or "").strip()
    if not raw:
        pytest.skip("TEST_DATABASE_URL is required for db_grounded tests")
    if raw.startswith("postgresql://"):
        raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    url = make_url(raw)
    if not str(url.drivername or "").startswith("postgresql"):
        pytest.skip("db_grounded tests require PostgreSQL")
    db_name = str(url.database or "").strip().lower()
    if "test" not in db_name:
        pytest.fail(
            "Refusing to run db_grounded tests because TEST_DATABASE_URL database name "
            f"{url.database!r} does not contain 'test'."
        )
    return raw


def _stable_uuid(kind: str, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"{SEED_NAMESPACE}:{kind}:{key}")


def _vector(key: str) -> list[float]:
    dimensions = max(2, int(getattr(settings, "VECTOR_DIMENSIONS", 1536) or 1536))
    vector = [0.0 for _ in range(dimensions)]
    axis_by_key = {
        "titanium_labret": 0,
        "gold_labret": 1,
        "steel_ring": 2,
        "shipping": 3,
        "returns": 4,
        "payment": 5,
        "dmbj38_detail": 6,
    }
    axis = axis_by_key.get(str(key or "").strip(), 0) % dimensions
    vector[axis] = 1.0
    return vector


def grounded_query_embedding(query: str) -> list[float]:
    normalized = str(query or "").strip().lower()
    if "return" in normalized:
        return _vector("returns")
    if "payment" in normalized or "pay" in normalized or "visa" in normalized:
        return _vector("payment")
    if "dmbj38" in normalized:
        return _vector("dmbj38_detail")
    if "shipping" in normalized or "ship" in normalized or "delivery" in normalized:
        return _vector("shipping")
    if "gold" in normalized:
        return _vector("gold_labret")
    if "ring" in normalized and "labret" not in normalized:
        return _vector("steel_ring")
    return _vector("titanium_labret")


def _load_seed() -> dict[str, Any]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


async def _delete_seeded_rows(session: AsyncSession, seed: dict[str, Any]) -> None:
    product_skus = [str(item["sku"]) for item in seed.get("products", [])]
    product_ids = [_stable_uuid("product", sku) for sku in product_skus]
    group_keys = {
        str(item.get("group_key") or item["sku"])
        for item in seed.get("products", [])
    }
    group_ids = [_stable_uuid("product-group", key) for key in sorted(group_keys)]
    legacy_group_ids = [_stable_uuid("product-group", sku) for sku in product_skus]
    article_titles = [str(item["title"]) for item in seed.get("knowledge", [])]
    article_ids = [_stable_uuid("article", title) for title in article_titles]

    await session.execute(delete(ProductEmbedding).where(ProductEmbedding.product_id.in_(product_ids)))
    await session.execute(delete(Product).where(Product.id.in_(product_ids)))
    await session.execute(delete(ProductGroup).where(ProductGroup.id.in_(group_ids + legacy_group_ids)))

    chunk_ids: list[UUID] = []
    for article in seed.get("knowledge", []):
        title = str(article["title"])
        for index, _chunk in enumerate(article.get("chunks", [])):
            chunk_ids.append(_stable_uuid("chunk", f"{title}:{index}"))

    if chunk_ids:
        await session.execute(delete(KnowledgeChunkTag).where(KnowledgeChunkTag.chunk_id.in_(chunk_ids)))
        await session.execute(delete(KnowledgeChunkEnrichment).where(KnowledgeChunkEnrichment.chunk_id.in_(chunk_ids)))
        await session.execute(delete(KnowledgeEmbedding).where(KnowledgeEmbedding.chunk_id.in_(chunk_ids)))
        await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids)))
    await session.execute(delete(KnowledgeArticle).where(KnowledgeArticle.id.in_(article_ids)))
    await session.commit()


async def _insert_seeded_rows(session: AsyncSession, seed: dict[str, Any]) -> GroundedSeed:
    products_by_sku: dict[str, dict[str, Any]] = {}
    knowledge_by_title: dict[str, dict[str, Any]] = {}
    product_model = str(getattr(settings, "PRODUCT_EMBEDDING_MODEL", settings.EMBEDDING_MODEL) or "")
    knowledge_model = str(getattr(settings, "KNOWLEDGE_EMBEDDING_MODEL", settings.EMBEDDING_MODEL) or "")
    groups_by_key: dict[str, ProductGroup] = {}

    for item in seed.get("products", []):
        sku = str(item["sku"])
        group_key = str(item.get("group_key") or sku)
        group = groups_by_key.get(group_key)
        if group is None:
            group = ProductGroup(
                id=_stable_uuid("product-group", group_key),
                master_code=group_key,
                display_title=str(item.get("group_title") or item["master_code"]),
            )
            groups_by_key[group_key] = group
            session.add(group)
        product = Product(
            id=_stable_uuid("product", sku),
            sku=sku,
            object_id=str(item["object_id"]),
            legacy_sku=[],
            master_code=str(item["master_code"]),
            description=str(item["description"]),
            price=float(item["price"]),
            currency=str(item["currency"]),
            stock_status=StockStatus(str(item["stock_status"])),
            stock_qty=int(item["stock_qty"]),
            image_url=str(item["image_url"]),
            product_url=str(item["product_url"]),
            attributes=dict(item["attributes"]),
            search_text=str(item["search_text"]),
            search_keywords=[],
            is_active=True,
            visibility=True,
            group_id=group.id,
        )
        embedding = ProductEmbedding(
            id=_stable_uuid("product-embedding", sku),
            product_id=product.id,
            category_id=str(item["attributes"].get("jewelry_type") or ""),
            price_cache=float(item["price"]),
            embedding=_vector(str(item["vector_key"])),
            model=product_model,
            source_hash=f"grounded:{sku}",
        )
        session.add(product)
        session.add(embedding)
        products_by_sku[sku] = {**item, "id": str(product.id), "group_id": str(group.id)}

    for article_data in seed.get("knowledge", []):
        title = str(article_data["title"])
        article = KnowledgeArticle(
            id=_stable_uuid("article", title),
            title=title,
            content=str(article_data["content"]),
            url=str(article_data["url"]),
            category=str(article_data["category"]),
            active_version=1,
        )
        session.add(article)
        chunks: list[dict[str, Any]] = []
        for index, chunk_data in enumerate(article_data.get("chunks", [])):
            chunk_id = _stable_uuid("chunk", f"{title}:{index}")
            chunk = KnowledgeChunk(
                id=chunk_id,
                article_id=article.id,
                version=1,
                chunk_index=index,
                chunk_text=str(chunk_data["text"]),
                chunk_hash=f"grounded:{title}:{index}",
            )
            enrichment = KnowledgeChunkEnrichment(
                chunk_id=chunk.id,
                summary_text=str(chunk_data["summary"]),
                summary_meta={"source": "grounded_seed"},
                generated_by="grounded_seed",
            )
            embedding = KnowledgeEmbedding(
                id=_stable_uuid("knowledge-embedding", f"{title}:{index}"),
                article_id=article.id,
                chunk_id=chunk.id,
                chunk_text=str(chunk_data["text"]),
                embedding=_vector(str(chunk_data["vector_key"])),
                model=knowledge_model,
                version=1,
            )
            session.add(chunk)
            session.add(enrichment)
            session.add(embedding)
            for tag in list(chunk_data.get("tags") or []):
                session.add(KnowledgeChunkTag(chunk_id=chunk.id, tag=str(tag)))
            chunks.append({**chunk_data, "id": str(chunk.id)})
        knowledge_by_title[title] = {**article_data, "id": str(article.id), "chunks": chunks}

    await session.commit()
    return GroundedSeed(products=products_by_sku, knowledge=knowledge_by_title)


@pytest.fixture()
async def grounded_db_engine():
    engine = create_async_engine(
        _db_url_from_env(),
        future=True,
        pool_pre_ping=True,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
    except SQLAlchemyError as exc:
        await engine.dispose()
        pytest.skip(f"db_grounded database is unavailable or missing pgvector support: {exc}")
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture()
async def grounded_db_session(grounded_db_engine):
    session_factory = async_sessionmaker(
        grounded_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        yield session


@pytest.fixture()
async def grounded_seed(grounded_db_session: AsyncSession) -> GroundedSeed:
    seed = _load_seed()
    await _delete_seeded_rows(grounded_db_session, seed)
    inserted = await _insert_seeded_rows(grounded_db_session, seed)
    try:
        yield inserted
    finally:
        await _delete_seeded_rows(grounded_db_session, seed)


async def fetch_seeded_product(session: AsyncSession, sku: str) -> Product:
    result = await session.execute(select(Product).where(Product.sku == sku))
    product = result.scalar_one()
    return product
