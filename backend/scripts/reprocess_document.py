"""Run background processing for a given document id from the command line.

Usage:
  python scripts/reprocess_document.py 09862580-fda6-4910-b70b-7803cde2a68a

This script uses the same services as the app and runs the background
processing synchronously so you can recover documents stuck in PROCESSING.
"""
import asyncio
import sys
from uuid import UUID

from app.services.document_service import document_service


async def main(doc_id_str: str):
    doc_id = UUID(doc_id_str)
    await document_service.process_document_background(doc_id)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/reprocess_document.py <document_uuid>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
