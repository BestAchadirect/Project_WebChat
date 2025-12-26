import enum
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

# Product Schemas
class StockStatus(str, enum.Enum):
    in_stock = "in_stock"
    out_of_stock = "out_of_stock"

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
    stock_status: StockStatus = StockStatus.in_stock
    
    # Control fields
    visibility: bool = True
    is_featured: bool = False
    priority: int = 0
    master_code: Optional[str] = None

    # Extended attributes
    jewelry_type: Optional[str] = None
    material: Optional[str] = None
    length: Optional[str] = None
    size: Optional[str] = None
    cz_color: Optional[str] = None
    design: Optional[str] = None
    crystal_color: Optional[str] = None
    color: Optional[str] = None
    gauge: Optional[str] = None
    size_in_pack: Optional[int] = None
    rack: Optional[str] = None
    height: Optional[str] = None
    packing_option: Optional[str] = None
    pincher_size: Optional[str] = None
    ring_size: Optional[str] = None
    quantity_in_bulk: Optional[int] = None
    opal_color: Optional[str] = None
    threading: Optional[str] = None
    outer_diameter: Optional[str] = None
    pearl_color: Optional[str] = None

class ProductUpdate(BaseModel):
    visibility: Optional[bool] = None
    is_featured: Optional[bool] = None
    priority: Optional[int] = None
    master_code: Optional[str] = None
    stock_status: Optional[StockStatus] = None

class ProductCarouselItem(BaseModel):
    """Product item for carousel display."""
    product_id: str
    name: str
    price: float
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    short_description: Optional[str] = None

class ProductListResponse(BaseModel):
    items: List[Product]
    total: int
    offset: int
    limit: int
