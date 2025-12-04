import asyncio
import sys
sys.path.append('backend')

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.document import Document

async def check_documents():
    """Check the latest documents in the database."""
    async with AsyncSessionLocal() as db:
        # Get latest 3 documents
        stmt = select(Document).order_by(Document.created_at.desc()).limit(3)
        result = await db.execute(stmt)
        documents = result.scalars().all()
        
        print("📊 Latest Documents in Database:\n")
        for doc in documents:
            print(f"ID: {doc.id}")
            print(f"  Filename: {doc.filename}")
            print(f"  File Path: {doc.file_path}")
            print(f"  Content Hash: {doc.content_hash}")
            print(f"  File Size: {doc.file_size} bytes")
            print(f"  Content Type: {doc.content_type}")
            print(f"  Status: {doc.status}")
            print(f"  Created: {doc.created_at}")
            print()

if __name__ == "__main__":
    asyncio.run(check_documents())
