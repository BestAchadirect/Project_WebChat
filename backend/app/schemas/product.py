from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

# Product Schemas
class Product(BaseModel):
    """Product information from Magento."""
    id: str
    object_id: Optional[str] = None
    sku: str
    legacy_sku: List[str] = []
    name: str
    price: float
    image_url: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    in_stock: bool = True

class ProductCarouselItem(BaseModel):
    """Product item for carousel display."""
    product_id: str
    name: str
    price: float
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    short_description: Optional[str] = None
