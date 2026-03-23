from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, text

from app.db.base import Base


class ChatParserRule(Base):
    __tablename__ = "chat_parser_rules"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    rule_group = Column(String(32), nullable=False, index=True)
    target_key = Column(String(100), nullable=False, index=True)
    pattern = Column(Text, nullable=False)
    canonical_value = Column(Text, nullable=True)
    priority = Column(Integer, nullable=False, server_default=text("100"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
