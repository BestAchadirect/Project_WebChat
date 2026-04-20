from __future__ import annotations

from enum import Enum


class ComponentType(str, Enum):
    QUERY_SUMMARY = "query_summary"
    PRODUCT_CARDS = "product_cards"
    PRODUCT_DETAIL = "product_detail"
    CLARIFY = "clarify"
    KNOWLEDGE_ANSWER = "knowledge_answer"
    ERROR = "error"


class ComponentSource(str, Enum):
    SQL = "sql"
    VECTOR = "vector"
    TOOL = "tool"
    KNOWLEDGE = "knowledge"
    ERROR = "error"
