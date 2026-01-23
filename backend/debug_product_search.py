import asyncio
import logging
from sqlalchemy import select, or_
from app.db.session import AsyncSessionLocal
from app.models.product import Product

# Suppress logs
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

async def check_product():
    async with AsyncSessionLocal() as db:
        query = "ACCO"
        output = []
        output.append(f"Checking for product: {query}")
        
        # Check SKU
        stmt = select(Product).where(Product.sku.ilike(f"%{query}%"))
        result = await db.execute(stmt)
        skus = result.scalars().all()
        output.append(f"SKUs matching '%{query}%': {[p.sku for p in skus]}")
        
        # Check Master Code
        stmt = select(Product).where(Product.master_code.ilike(f"%{query}%"))
        result = await db.execute(stmt)
        masters = result.scalars().all()
        output.append(f"Master Codes matching '%{query}%': {[p.master_code for p in masters]}")
        
        with open("debug_output.txt", "w") as f:
            f.write("\n".join(output))

if __name__ == "__main__":
    asyncio.run(check_product())
