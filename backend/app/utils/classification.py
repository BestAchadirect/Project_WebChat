from app.services.llm_service import llm_service
from app.core.logging import get_logger

logger = get_logger(__name__)

async def classify_user_intent(message: str) -> dict:
    """
    Classify user intent using LLM.
    
    Args:
        message: User message
    
    Returns:
        Classification result: {"intent": str, "confidence": float, "reasoning": str}
    """
    return await llm_service.classify_intent(message)

def extract_product_keywords(message: str) -> list[str]:
    """
    Extract potential product-related keywords from message.
    Simple keyword extraction - can be enhanced with NLP.
    
    Args:
        message: User message
    
    Returns:
        List of keywords
    """
    # Simple implementation - split and filter
    words = message.lower().split()
    
    # Filter out common stop words
    stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", 
                  "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
                  "i", "you", "he", "she", "it", "we", "they", "what", "which", "who",
                  "when", "where", "why", "how", "do", "does", "did", "can", "could",
                  "would", "should", "may", "might", "will", "shall"}
    
    keywords = [word for word in words if word not in stop_words and len(word) > 2]
    
    return keywords
