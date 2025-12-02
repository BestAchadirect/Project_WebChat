import pdfplumber
from fastapi import UploadFile
from typing import List

class IngestionService:
    @staticmethod
    async def extract_text(file: UploadFile) -> str:
        if file.content_type == "application/pdf":
            return await IngestionService._extract_from_pdf(file)
        elif file.content_type in ["text/plain", "text/csv"]:
            content = await file.read()
            return content.decode("utf-8")
        else:
            raise ValueError(f"Unsupported file type: {file.content_type}")

    @staticmethod
    async def _extract_from_pdf(file: UploadFile) -> str:
        # Save temporarily or read directly if possible
        # pdfplumber needs a file-like object or path
        # UploadFile.file is a SpooledTemporaryFile which works
        text = ""
        with pdfplumber.open(file.file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text

    @staticmethod
    def create_chunks(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start += chunk_size - overlap
        
        return chunks
