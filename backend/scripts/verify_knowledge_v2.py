import asyncio
import os
import sys

# Assume running from 'backend' directory
sys.path.append(os.getcwd())

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.knowledge import KnowledgeArticle, KnowledgeArticleVersion, KnowledgeChunk, KnowledgeEmbedding
from app.services.data_import_service import data_import_service
from fastapi import UploadFile

class MockUploadFile:
    def __init__(self, filename, content):
        self.filename = filename
        self.content = content
        self.content_type = "text/csv"
    
    async def read(self):
        return self.content

async def verify():
    async with AsyncSessionLocal() as db:
        print("Starting Verification...")
        
        # 1. Create Mock File
        csv_content = b"title,content\nTest Doc v1,This is the content of test doc version 1. It has enough text to be chunked maybe."
        file = MockUploadFile("test_v1.csv", csv_content)
        
        # 2. Import
        print("Importing V1...")
        try:
            res = await data_import_service.import_knowledge(db, file)
            upload_id = res["upload_id"]
            print(f"Import V1 Result: {res}")
        except Exception as e:
            print(f"Import failed: {e}")
            raise

        # 3. Verify DB Structure
        # Check Article
        stmt = select(KnowledgeArticle).where(KnowledgeArticle.title == "Test Doc v1")
        article = (await db.execute(stmt)).scalar_one_or_none()
        assert article is not None, "Article not found"
        print(f"Article found: {article.id}")
        
        # Check Version
        stmt = select(KnowledgeArticleVersion).where(KnowledgeArticleVersion.article_id == article.id)
        versions = (await db.execute(stmt)).scalars().all()
        assert len(versions) >= 1, "Version not created"
        latest_version = versions[-1]
        print(f"Version found: {latest_version.version}")
        
        # Check Chunks
        stmt = select(KnowledgeChunk).where(KnowledgeChunk.article_id == article.id, KnowledgeChunk.version == latest_version.version)
        chunks = (await db.execute(stmt)).scalars().all()
        assert len(chunks) > 0, "Chunks not created"
        print(f"Chunks created: {len(chunks)}")
        
        # 4. Import Update (V2)
        print("Importing V2 (Modified content)...")
        csv_content_v2 = b"title,content\nTest Doc v1,This is the content of test doc version 2. It is slightly different."
        file_v2 = MockUploadFile("test_v2.csv", csv_content_v2)
        
        try:
            res_v2 = await data_import_service.import_knowledge(db, file_v2)
            print(f"Import V2 Result: {res_v2}")
        except Exception as e:
            print(f"Import V2 failed: {e}")
            raise
        
        # Check new version
        versions_v2 = (await db.execute(select(KnowledgeArticleVersion).where(KnowledgeArticleVersion.article_id == article.id))).scalars().all()
        print(f"Total versions: {len(versions_v2)}")
        assert len(versions_v2) == len(versions) + 1, "New version not created"
        
        print("Verification Successful!")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(verify())
