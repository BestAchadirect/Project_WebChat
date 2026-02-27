from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class ProductSearchProjection(Base):
    __tablename__ = "product_search_projection"

    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    sku_norm = Column(String(255), nullable=False, index=True)
    material_norm = Column(String(255), nullable=True, index=True)
    jewelry_type_norm = Column(String(255), nullable=True, index=True)
    gauge_norm = Column(String(64), nullable=True, index=True)
    threading_norm = Column(String(128), nullable=True, index=True)
    color_norm = Column(String(255), nullable=True, index=True)
    opal_color_norm = Column(String(255), nullable=True, index=True)
    search_text_norm = Column(Text, nullable=True)
    stock_status_norm = Column(String(64), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    product = relationship("Product")

    __table_args__ = (
        Index(
            "ix_product_search_projection_active_filters",
            "is_active",
            "material_norm",
            "jewelry_type_norm",
            "gauge_norm",
            "threading_norm",
            "color_norm",
        ),
        Index(
            "ix_product_search_projection_sku_active",
            "sku_norm",
            "is_active",
        ),
    )

