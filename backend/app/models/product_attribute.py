from sqlalchemy import BigInteger, Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class AttributeDefinition(Base):
    __tablename__ = "attribute_definitions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=False)
    data_type = Column(String(50), nullable=False)

    values = relationship("ProductAttributeValue", back_populates="attribute", cascade="all, delete-orphan")


class ProductAttributeValue(Base):
    __tablename__ = "product_attribute_values"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    attribute_id = Column(BigInteger, ForeignKey("attribute_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(Text, nullable=True)

    attribute = relationship("AttributeDefinition", back_populates="values")
