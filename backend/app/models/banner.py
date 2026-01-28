from sqlalchemy import Column, String, Boolean, Integer, BigInteger, DateTime
from sqlalchemy.sql import func

from app.db.base import Base


class Banner(Base):
    __tablename__ = "banner"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    image_url = Column(String(512), nullable=False)
    link_url = Column(String(1024), nullable=True)
    alt_text = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
