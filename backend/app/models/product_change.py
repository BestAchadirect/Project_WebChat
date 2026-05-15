import uuid

from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base
from app.utils.datetime import utc_now


class ProductChange(Base):
    __tablename__ = "product_changes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_id = Column(UUID(as_uuid=True), ForeignKey("product_uploads.id"), nullable=True, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    changed_fields = Column(JSONB, default=list)
    old_values = Column(JSONB, default=dict)
    new_values = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
