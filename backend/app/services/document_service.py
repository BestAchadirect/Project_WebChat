from pathlib import Path
from typing import List, Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentStatus


class DocumentService:
    """Service layer for managing uploaded documents."""

    def __init__(self) -> None:
        self.root_dir = Path(settings.UPLOAD_DIR) / "documents"

    async def upload_document(self, db: AsyncSession, file: UploadFile) -> Document:
        """Store uploaded file and persist metadata."""
        self.root_dir.mkdir(parents=True, exist_ok=True)

        doc_id = uuid4()
        safe_name = Path(file.filename or "upload").name
        dest_dir = self.root_dir / str(doc_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / safe_name

        content = await file.read()
        dest_path.write_bytes(content)

        doc = Document(
            id=doc_id,
            filename=safe_name,
            content_type=file.content_type,
            file_size=len(content),
            file_path=str(dest_path),
            status=DocumentStatus.COMPLETED,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    async def list_documents(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Document], int]:
        """Return paginated documents."""
        total_stmt = select(func.count()).select_from(Document)
        total = (await db.execute(total_stmt)).scalar_one()

        stmt = (
            select(Document)
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        items = (await db.execute(stmt)).scalars().all()
        return items, total

    async def delete_document(self, db: AsyncSession, document_id: UUID) -> None:
        """Delete a document record plus its stored file."""
        stmt = select(Document).where(Document.id == document_id)
        result = await db.execute(stmt)
        doc = result.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        file_path = Path(doc.file_path)
        resolved = self._ensure_within_root(file_path)
        resolved.unlink(missing_ok=True)
        # cleanup doc-specific directory if empty
        doc_dir = resolved.parent
        if doc_dir.exists():
            try:
                doc_dir.rmdir()
            except OSError:
                pass

        await db.delete(doc)
        await db.commit()

    def _ensure_within_root(self, path: Path) -> Path:
        """Validate the stored path stays under uploads root."""
        root_resolved = self.root_dir.resolve()
        target = path.resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid file path")
        return target


document_service = DocumentService()
