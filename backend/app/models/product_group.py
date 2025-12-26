from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.db.base import Base


class ProductGroup(Base):
    __tablename__ = "product_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    master_code = Column(String, unique=True, index=True, nullable=False)
    display_title = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    products = relationship("Product", back_populates="group")
