from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from app.models.product import Product
from app.schemas.product import Product as ProductSchema

class ProductService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_product_sku(self, object_id: str, new_sku: str):
        """
        Updates the SKU of a product if it has changed.
        Moves the old SKU to the 'legacy_sku' array.
        """
        # 1. Find the product by its immutable object_id (or ID)
        stmt = select(Product).where(Product.object_id == object_id)
        result = await self.db.execute(stmt)
        product = result.scalar_one_or_none()

        if not product:
            return None # Or raise NotFoundException

        # 2. Check if SKU has changed
        if product.sku != new_sku:
            print(f"SKU Change Detected for {product.name}: {product.sku} -> {new_sku}")
            
            # 3. Retrieve current legacy_skus (ensure it's a list)
            current_legacy = list(product.legacy_sku) if product.legacy_sku else []
            
            # 4. Add old SKU to legacy list if not already there
            if product.sku not in current_legacy:
                current_legacy.append(product.sku)
            
            # 5. Update fields
            product.legacy_sku = current_legacy
            product.sku = new_sku
            
            self.db.add(product)
            await self.db.commit()
            await self.db.refresh(product)
            
        return product

    async def create_or_update_product(self, product_data: ProductSchema):
        # Implementation for full sync...
        pass
