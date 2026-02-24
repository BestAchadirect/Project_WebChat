import sys
import os
import asyncio
from unittest.mock import MagicMock

# Mock Environment Variables for Pydantic Settings
os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost/db"
os.environ["JWT_SECRET"] = "secret"
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["SUPABASE_URL"] = "https://example.supabase.co"
os.environ["SUPABASE_KEY"] = "anon-key"
os.environ["SUPABASE_SERVICE_KEY"] = "service-key"

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

try:
    from app.models.product import Product
    from app.models.knowledge import KnowledgeArticle
    from app.models.chat import ChatSession
    from app.schemas.chat import ChatRequest
    from app.services.chat.service import ChatService
    from app.api.routes import chat

    print("✅ Imports successful")

    # Mock DB Session
    mock_db = MagicMock()
    
    # Instantiate Service
    service = ChatService(mock_db)
    print("✅ ChatService instantiated")

    # Test Schema
    req = ChatRequest(message="Hello", locale="en-US")
    print(f"✅ Schema validation passed: {req}")

except Exception as e:
    print(f"❌ Verification Failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
