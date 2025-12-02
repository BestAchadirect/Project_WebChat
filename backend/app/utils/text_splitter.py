from typing import List

class TextSplitter:
    """Utility for splitting text into chunks."""
    
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separator: str = "\n\n"
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separator = separator
    
    def split_text(self, text: str) -> List[str]:
        """
        Split text into overlapping chunks.
        
        Args:
            text: Input text to split
        
        Returns:
            List of text chunks
        """
        if not text:
            return []
        
        # Split by separator first
        splits = text.split(self.separator)
        
        chunks = []
        current_chunk = ""
        
        for split in splits:
            # If adding this split would exceed chunk_size, save current chunk
            if len(current_chunk) + len(split) > self.chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                # Start new chunk with overlap
                current_chunk = self._get_overlap(current_chunk) + split
            else:
                current_chunk += (self.separator if current_chunk else "") + split
        
        # Add the last chunk
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _get_overlap(self, text: str) -> str:
        """Get the last chunk_overlap characters from text."""
        if len(text) <= self.chunk_overlap:
            return text
        return text[-self.chunk_overlap:]

def split_text_by_tokens(
    text: str,
    max_tokens: int = 500,
    overlap_tokens: int = 50
) -> List[str]:
    """
    Split text by approximate token count.
    Note: This is a simple approximation (1 token ≈ 4 characters).
    For production, use tiktoken library.
    """
    chars_per_token = 4
    chunk_size = max_tokens * chars_per_token
    overlap_size = overlap_tokens * chars_per_token
    
    splitter = TextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap_size
    )
    
    return splitter.split_text(text)
