import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock

# Mock Environment Variables for Pydantic Settings
os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost/db"
os.environ["JWT_SECRET"] = "secret"
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["SUPABASE_URL"] = "https://example.supabase.co"
os.environ["SUPABASE_KEY"] = "anon-key"
os.environ["SUPABASE_SERVICE_KEY"] = "service-key"

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.services.product_service import ProductService
from app.models.product import Product

async def test_sku_logic():
    print("🧪 Starting SKU Update Verification...")
    
    # Mock DB
    mock_db = AsyncMock()
    service = ProductService(mock_db)
    
    # Mock Data: Existing Product
    mock_product = Product(
        object_id="123",
        sku="SKU-OLD",
        legacy_sku=[],
        name="Test Item"
    )
    
    # Mock Execute Result
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_product
    mock_db.execute.return_value = mock_result
    
    # CASE 1: SKU Change
    print("\n--- Testing Change: SKU-OLD -> SKU-NEW ---")
    await service.update_product_sku("123", "SKU-NEW")
    
    print(f"Current SKU: {mock_product.sku}")
    print(f"Legacy SKUs: {mock_product.legacy_sku}")
    
    assert mock_product.sku == "SKU-NEW"
    assert "SKU-OLD" in mock_product.legacy_sku
    print("✅ Case 1 Passed")
    
    # CASE 2: No Change
    print("\n--- Testing No Change: SKU-NEW -> SKU-NEW ---")
    await service.update_product_sku("123", "SKU-NEW")
    
    print(f"Current SKU: {mock_product.sku}")
    print(f"Legacy SKUs: {mock_product.legacy_sku}")
    
    assert mock_product.sku == "SKU-NEW"
    assert len(mock_product.legacy_sku) == 1 # Shouldn't duplicate
    print("✅ Case 2 Passed")

    # CASE 3: Another Change
    print("\n--- Testing Change: SKU-NEW -> SKU-FINAL ---")
    await service.update_product_sku("123", "SKU-FINAL")
    
    print(f"Current SKU: {mock_product.sku}")
    print(f"Legacy SKUs: {mock_product.legacy_sku}")
    
    assert mock_product.sku == "SKU-FINAL"
    assert "SKU-OLD" in mock_product.legacy_sku
    assert "SKU-NEW" in mock_product.legacy_sku
    print("✅ Case 3 Passed")

if __name__ == "__main__":
    asyncio.run(test_sku_logic())
