import asyncio
import os
import sys
from sqlalchemy import text
import httpx

# Add parent directory to path so we can import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import engine

async def verify():
    test_code = 'SEARCH-V-CODE'
    original_master_code = None
    target_product_id = None

    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT id, master_code FROM products ORDER BY created_at DESC NULLS LAST LIMIT 1")
            )
        ).first()
        if not row:
            print("No products found. Skipping verification.")
            return

        target_product_id = row[0]
        original_master_code = row[1]

        print(f"Assigning master_code '{test_code}' to product id {target_product_id}...")
        await conn.execute(
            text("UPDATE products SET master_code = :code WHERE id = :product_id"),
            {"code": test_code, "product_id": target_product_id},
        )

    try:
        print(f"Testing API search for '{test_code}'...")
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://localhost:8000/api/v1/products/?search={test_code}")
            data = response.json()
            total = int(data.get("totalItems", data.get("total", 0)) or 0)
            items = data.get("items") or []

            print(f"Found {total} products.")
            if total > 0 and items:
                print(f"Success! Found product with master_code '{items[0].get('master_code')}'")
            else:
                print("Failed to find product via unified search.")
    finally:
        if target_product_id is not None and original_master_code is not None:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE products SET master_code = :master_code WHERE id = :product_id"),
                    {"master_code": original_master_code, "product_id": target_product_id},
                )
            print("Restored original master_code after verification.")

if __name__ == "__main__":
    asyncio.run(verify())
