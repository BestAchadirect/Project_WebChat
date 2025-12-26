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
    async with engine.begin() as conn:
        print(f"Assigning master_code '{test_code}' to a random product...")
        await conn.execute(text(f"UPDATE products SET master_code = '{test_code}' WHERE id = (SELECT id FROM products LIMIT 1);"))
    
    print(f"Testing API search for '{test_code}'...")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://localhost:8000/api/v1/products/?search={test_code}")
        data = response.json()
        print(f"Found {data['total']} products.")
        if data['total'] > 0:
            print(f"Success! Found product with master_code '{data['items'][0]['master_code']}'")
        else:
            print("Failed to find product via unified search.")

if __name__ == "__main__":
    asyncio.run(verify())
