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
            file_type: File extension (txt, csv)
        
        Returns:
            Extracted text content
        """
        file_type = file_type.lower().replace(".", "")
        
        if file_type == "txt":
            return await FileParser._parse_txt(file_path)
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
