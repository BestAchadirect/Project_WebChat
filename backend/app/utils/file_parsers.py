from typing import Optional
import io
from pathlib import Path

class FileParser:
    """Utility for parsing different file formats to text."""
    
    @staticmethod
    async def parse_file(file_path: str, file_type: str) -> str:
        """
        Parse a file and extract text content.
        
        Args:
            file_path: Path to the file
            file_type: File extension (pdf, doc, docx, txt, csv)
        
        Returns:
            Extracted text content
        """
        file_type = file_type.lower().replace(".", "")
        
        if file_type == "txt":
            return await FileParser._parse_txt(file_path)
        elif file_type == "pdf":
            return await FileParser._parse_pdf(file_path)
        elif file_type in ["doc", "docx"]:
            return await FileParser._parse_docx(file_path)
        elif file_type == "csv":
            return await FileParser._parse_csv(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
    
    @staticmethod
    async def _parse_txt(file_path: str) -> str:
        """Parse plain text file."""
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    
    @staticmethod
    async def _parse_pdf(file_path: str) -> str:
        """
        Parse PDF file.
        Requires: pip install pypdf2 or pdfplumber
        """
        try:
            import pdfplumber
            
            text_parts = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
            
            return "\n\n".join(text_parts)
        except ImportError:
            # Fallback to PyPDF2
            try:
                from PyPDF2 import PdfReader
                
                reader = PdfReader(file_path)
                text_parts = []
                
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                
                return "\n\n".join(text_parts)
            except ImportError:
                raise ImportError("Please install pdfplumber or PyPDF2 to parse PDF files")
    
    @staticmethod
    async def _parse_docx(file_path: str) -> str:
        """
        Parse DOCX file.
        Requires: pip install python-docx
        """
        try:
            from docx import Document
            
            doc = Document(file_path)
            text_parts = [paragraph.text for paragraph in doc.paragraphs if paragraph.text]
            
            return "\n\n".join(text_parts)
        except ImportError:
            raise ImportError("Please install python-docx to parse DOCX files")
    
    @staticmethod
    async def _parse_csv(file_path: str) -> str:
        """Parse CSV file."""
        import csv
        
        text_parts = []
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            
            if headers:
                text_parts.append(" | ".join(headers))
            
            for row in reader:
                text_parts.append(" | ".join(row))
        
        return "\n".join(text_parts)

async def parse_uploaded_file(file_content: bytes, filename: str) -> str:
    """
    Parse uploaded file content.
    
    Args:
        file_content: File content as bytes
        filename: Original filename
    
    Returns:
        Extracted text
    """
    # Save temporarily and parse
    import tempfile
    
    file_ext = Path(filename).suffix
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
        tmp_file.write(file_content)
        tmp_path = tmp_file.name
    
    try:
        text = await FileParser.parse_file(tmp_path, file_ext)
        return text
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)
