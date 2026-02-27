from __future__ import annotations

from enum import Enum


class ComponentType(str, Enum):
    QUERY_SUMMARY = "query_summary"
    RESULT_COUNT = "result_count"
    PRODUCT_CARDS = "product_cards"
    PRODUCT_TABLE = "product_table"
    PRODUCT_BULLETS = "product_bullets"
    PRODUCT_DETAIL = "product_detail"
    COMPARE = "compare"
    RECOMMENDATIONS = "recommendations"
    CLARIFY = "clarify"
    KNOWLEDGE_ANSWER = "knowledge_answer"
    ACTION_RESULT = "action_result"
    ERROR = "error"


class ComponentSource(str, Enum):
    SQL = "sql"
    VECTOR = "vector"
    TOOL = "tool"
    KNOWLEDGE = "knowledge"
    ERROR = "error"

