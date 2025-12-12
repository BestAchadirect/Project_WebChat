import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

# Mock Environment Variables
os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost/db"
os.environ["JWT_SECRET"] = "secret"
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["SUPABASE_URL"] = "https://example.supabase.co"
os.environ["SUPABASE_KEY"] = "anon-key"
os.environ["SUPABASE_SERVICE_KEY"] = "service-key"

from fastapi import UploadFile
from app.services.data_import_service import DataImportService
from app.models.product import Product
from app.models.knowledge import KnowledgeArticle

async def test_import_logic():
    print("🧪 Starting Data Import Verification...")
    
    # Mock DB
    mock_db = AsyncMock()
    service = DataImportService()
    
    # Mock LLM Service (monkeypatch)
    from app.services.llm_service import llm_service
    llm_service.generate_embedding = AsyncMock(return_value=[0.1] * 1536)
    
    # --- TEST 1: Product Import ---
    print("\n--- Testing Product Import ---")
    csv_content = b"sku,name,price,description\nSKU-1,Test Product,100,Desc\nSKU-2,Another Product,200,Desc 2"
    
    # Mock UploadFile
    mock_file = AsyncMock() # UploadFile is hard to mock directly, just mocking read behavior
    mock_file.read.return_value = csv_content
    mock_file.filename = "products.csv"
    
    # Mock DB Query (No existing products)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result
    
    stats = await service.import_products(mock_db, mock_file)
    
    print(f"Stats: {stats}")
    assert stats["created"] == 2
    assert stats["updated"] == 0
    print("✅ Product Import Passed")
    
    # --- TEST 2: Knowledge Import ---
    print("\n--- Testing Knowledge Import ---")
    kb_content = b"title,content,category\nFAQ 1,Answer 1,General\nFAQ 2,Answer 2,Shipping"
    
    mock_kb_file = AsyncMock()
    mock_kb_file.read.return_value = kb_content
    mock_kb_file.filename = "kb.csv"
    
    stats_kb = await service.import_knowledge(mock_db, mock_kb_file)
    
    print(f"Stats: {stats_kb}")
    assert stats_kb["created"] == 2
    print("✅ Knowledge Import Passed")

    # --- TEST 3: Template Generation ---
    prod_template = service.get_product_template()
    kb_template = service.get_knowledge_template()
    assert "sku,name" in prod_template
    assert "title,content" in kb_template
    print(f"Templates: {prod_template[:20]}...")
    print("✅ Template Generation Passed")

if __name__ == "__main__":
    asyncio.run(test_import_logic())
