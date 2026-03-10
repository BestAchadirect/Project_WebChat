from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class AttributeDefinition(Base):
    __tablename__ = "attribute_definitions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=False)
    data_type = Column(String(50), nullable=False)
    is_enabled = Column(Boolean, nullable=False, server_default=text("true"))
    tier = Column(String(20), nullable=False, server_default=text("'secondary'"))
    display_order = Column(Integer, nullable=False, server_default=text("100"))
    is_multivalue = Column(Boolean, nullable=False, server_default=text("false"))
    option_cap = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    values = relationship("ProductAttributeValue", back_populates="attribute", cascade="all, delete-orphan")
    aliases = relationship("FacetValueAlias", back_populates="attribute", cascade="all, delete-orphan")


class ProductAttributeValue(Base):
    __tablename__ = "product_attribute_values"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    attribute_id = Column(BigInteger, ForeignKey("attribute_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(Text, nullable=True)
    value_norm = Column(Text, nullable=True)

    attribute = relationship("AttributeDefinition", back_populates="values")


class FacetValueAlias(Base):
    __tablename__ = "facet_value_aliases"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    attribute_id = Column(BigInteger, ForeignKey("attribute_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_value = Column(Text, nullable=False)
    raw_value_norm = Column(Text, nullable=False)
    canonical_value = Column(Text, nullable=False)
    canonical_value_norm = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    attribute = relationship("AttributeDefinition", back_populates="aliases")
