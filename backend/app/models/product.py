from sqlalchemy import Column, String, Float, Boolean, Integer, ForeignKey, DateTime, Enum
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import relationship, synonym
from pgvector.sqlalchemy import Vector
from datetime import datetime
import uuid
import enum

from app.db.base import Base
from app.core.config import settings

class StockStatus(str, enum.Enum):
    in_stock = "in_stock"
    out_of_stock = "out_of_stock"

class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    object_id = Column(String, unique=True, index=True, nullable=True)  # Internal/Magento ID
    sku = Column(String, unique=True, index=True, nullable=False)
    legacy_sku = Column(ARRAY(String), default=list)  # Multiple SKUs
    description = Column(String, nullable=True)
    price = Column(Float, nullable=False)
    currency = Column(String, default=lambda: (getattr(settings, "BASE_CURRENCY", "USD") or "USD").upper(), nullable=False)
    stock_status = Column(Enum(StockStatus), default=StockStatus.in_stock)
    image_url = Column(String, nullable=True)
    product_url = Column(String, nullable=True)
    attributes = Column(JSONB, default=dict)  # Key-value pairs for filters
    is_active = Column(Boolean, default=True)
    product_upload_id = Column(UUID(as_uuid=True), ForeignKey("product_uploads.id"), nullable=True)
    
    
    # Control fields
    visibility = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False)
    priority = Column(Integer, default=0)
    master_code = Column(String, index=True, nullable=False)

    # Backward-compatible alias: many parts of the codebase still reference `product.name`.
    # We store the value in master_code and expose it via this synonym.
    name = synonym("master_code")
    group_id = Column(UUID(as_uuid=True), ForeignKey("product_groups.id"), nullable=False, index=True)

    # New fields
    search_text = Column(String, nullable=True)
    search_hash = Column(String, nullable=True)
    search_keywords = Column(ARRAY(String), default=list, nullable=False)

    # Common product attribute columns (optional; also mirrored in attributes JSONB)
    jewelry_type = Column(String, nullable=True, index=True)
    material = Column(String, nullable=True, index=True)
    length = Column(String, nullable=True)
    size = Column(String, nullable=True)
    cz_color = Column(String, nullable=True)
    design = Column(String, nullable=True)
    crystal_color = Column(String, nullable=True)
    color = Column(String, nullable=True)
    gauge = Column(String, nullable=True)
    size_in_pack = Column(Integer, nullable=True)
    rack = Column(String, nullable=True)
    height = Column(String, nullable=True)
    packing_option = Column(String, nullable=True)
    pincher_size = Column(String, nullable=True)
    ring_size = Column(String, nullable=True)
    quantity_in_bulk = Column(Integer, nullable=True)
    opal_color = Column(String, nullable=True)
    threading = Column(String, nullable=True)
    outer_diameter = Column(String, nullable=True)
    pearl_color = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    embeddings = relationship("ProductEmbedding", back_populates="product", cascade="all, delete-orphan")
    upload = relationship("ProductUpload", back_populates="products")
    group = relationship("ProductGroup", back_populates="products")

class ProductEmbedding(Base):
    __tablename__ = "product_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    
    # Metadata cache for faster filtering without joining
    category_id = Column(String, nullable=True, index=True) 
    price_cache = Column(Float, nullable=False)
    
    # Vector embedding
    embedding = Column(Vector(settings.VECTOR_DIMENSIONS), nullable=False)
    model = Column(String, nullable=True)
    source_hash = Column(String, nullable=True, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    product = relationship("Product", back_populates="embeddings")
