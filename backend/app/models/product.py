from sqlalchemy import Column, String, Float, Boolean, Integer, JSON, ForeignKey, DateTime
from sqlalchemy import Column, String, Float, Boolean, Integer, JSON, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from datetime import datetime
import uuid

from app.db.base import Base
from app.core.config import settings

class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    object_id = Column(String, unique=True, index=True, nullable=True)  # Internal/Magento ID
    sku = Column(String, unique=True, index=True, nullable=False)
    legacy_sku = Column(ARRAY(String), default=list)  # Multiple SKUs
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    price = Column(Float, nullable=False)
    currency = Column(String, default="THB", nullable=False)
    stock_status = Column(String, default="in_stock")  # in_stock, out_of_stock
    image_url = Column(String, nullable=True)
    product_url = Column(String, nullable=True)
    attributes = Column(JSON, default={})  # Key-value pairs for filters
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    embeddings = relationship("ProductEmbedding", back_populates="product", cascade="all, delete-orphan")

class ProductEmbedding(Base):
    __tablename__ = "product_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    
    # Metadata cache for faster filtering without joining
    category_id = Column(String, nullable=True, index=True) 
    price_cache = Column(Float, nullable=False)
    
    # Vector embedding
    embedding = Column(Vector(settings.VECTOR_DIMENSIONS), nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    product = relationship("Product", back_populates="embeddings")
