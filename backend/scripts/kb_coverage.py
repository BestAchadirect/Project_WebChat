import argparse
import asyncio
from typing import Optional

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.knowledge import KnowledgeArticle, KnowledgeChunk, KnowledgeEmbedding, KnowledgeArticleVersion
from app.services.data_import_service import data_import_service
from app.services.llm_service import llm_service


async def _get_counts(db, article_id):
    emb_stmt = select(func.count()).select_from(KnowledgeEmbedding).where(KnowledgeEmbedding.article_id == article_id)
    chunk_stmt = select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.article_id == article_id)
    ver_stmt = select(func.count()).select_from(KnowledgeArticleVersion).where(KnowledgeArticleVersion.article_id == article_id)
    emb_count = (await db.execute(emb_stmt)).scalar() or 0
    chunk_count = (await db.execute(chunk_stmt)).scalar() or 0
    ver_count = (await db.execute(ver_stmt)).scalar() or 0
    return int(ver_count), int(chunk_count), int(emb_count)


async def _ensure_article_with_embeddings(
    *,
    title: str,
    content: str,
    category: Optional[str],
    url: Optional[str],
) -> None:
    async with AsyncSessionLocal() as db:
        existing_stmt = select(KnowledgeArticle).where(KnowledgeArticle.title == title)
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing:
            ver_count, chunk_count, emb_count = await _get_counts(db, existing.id)
            print(f"Already exists: knowledge_articles.title={title!r} id={existing.id}")
            print(f"versions={ver_count} chunks={chunk_count} embeddings={emb_count}")
            return

        article = KnowledgeArticle(
            title=title,
            content=content,
            category=category,
            url=url,
            upload_session_id=None,
        )
        db.add(article)
        await db.commit()
        await db.refresh(article)

        version = KnowledgeArticleVersion(
            article_id=article.id,
            version=1,
            content_text=content,
            created_by="kb_coverage.py",
        )
        db.add(version)
        await db.commit()

        chunk_texts = data_import_service._chunk_text(content)
        chunks = []
        for idx, chunk_text in enumerate(chunk_texts):
            chunk = KnowledgeChunk(
                article_id=article.id,
                version=1,
                chunk_index=idx,
                chunk_text=chunk_text,
                chunk_hash=data_import_service._hash_text(chunk_text),
            )
            db.add(chunk)
            chunks.append(chunk)

        await db.commit()

        embeddings = await llm_service.generate_embeddings_batch([c.chunk_text for c in chunks])
        for chunk, emb in zip(chunks, embeddings):
            db.add(
                KnowledgeEmbedding(
                    article_id=article.id,
                    chunk_id=chunk.id,
                    chunk_text=chunk.chunk_text,
                    embedding=emb,
                    model=settings.EMBEDDING_MODEL,
                    version=1,
                )
            )

        await db.commit()

        ver_count, chunk_count, emb_count = await _get_counts(db, article.id)
        print(f"Created: knowledge_articles.title={title!r} id={article.id}")
        print(f"versions={ver_count} chunks={chunk_count} embeddings={emb_count}")


async def _audit(*, title_contains: str) -> None:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(KnowledgeArticle)
            .where(KnowledgeArticle.title.ilike(f"%{title_contains}%"))
            .order_by(KnowledgeArticle.created_at.desc())
            .limit(20)
        )
        rows = (await db.execute(stmt)).scalars().all()
        if not rows:
            print(f"No knowledge_articles found with title ILIKE %{title_contains}%")
            return

        print(f"Found {len(rows)} matching knowledge_articles:")
        for a in rows:
            ver_count, chunk_count, emb_count = await _get_counts(db, a.id)
            print(f"- id={a.id} title={a.title!r} category={a.category!r} versions={ver_count} chunks={chunk_count} embeddings={emb_count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit KB coverage and (optionally) create an article+embeddings.")
    parser.add_argument("--title-contains", help="Search knowledge_articles.title with ILIKE", default=None)
    parser.add_argument("--create", action="store_true", help="Create an article if missing (and generate chunks+embeddings).")
    parser.add_argument("--title", help="Exact title for create mode", default=None)
    parser.add_argument("--content", help="Article content text for create mode", default=None)
    parser.add_argument("--category", help="Optional category", default="faq")
    parser.add_argument("--url", help="Optional URL", default=None)
    args = parser.parse_args()

    if args.title_contains:
        asyncio.run(_audit(title_contains=args.title_contains))
        return

    if args.create:
        if not args.title or not args.content:
            raise SystemExit("--create requires --title and --content")
        asyncio.run(
            _ensure_article_with_embeddings(
                title=args.title,
                content=args.content,
                category=args.category,
                url=args.url,
            )
        )
        return

    parser.print_help()


if __name__ == "__main__":
    main()

