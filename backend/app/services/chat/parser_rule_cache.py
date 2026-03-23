from __future__ import annotations

import asyncio
import logging
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat_parser_rule import ChatParserRule
from app.models.product_attribute import AttributeDefinition
from app.services.chat.parser_rule_types import ParserRuleSet, build_rule_set, empty_rule_set

logger = logging.getLogger(__name__)


_parser_rules: ParserRuleSet | None = None
_cache_lock = asyncio.Lock()
_PARSER_RULE_TIMEOUT_SECONDS = float(
    getattr(settings, "PARSER_RULES_REFRESH_TIMEOUT_SECONDS", 5.0)
)


def _normalize_text(value: object) -> str:
    return str(value or "").strip().lower()


def _add_pattern(bucket: Dict[str, List[str]], key: str, pattern: str) -> None:
    if not key or not pattern:
        return
    values = bucket.setdefault(key, [])
    if pattern not in values:
        values.append(pattern)


async def refresh_parser_rule_cache(db: AsyncSession) -> ParserRuleSet:
    global _parser_rules
    async with _cache_lock:
        rules_stmt = (
            select(ChatParserRule)
            .where(ChatParserRule.is_active.is_(True))
            .order_by(ChatParserRule.priority.asc(), ChatParserRule.id.asc())
        )
        attrs_stmt = (
            select(AttributeDefinition.name)
            .where(AttributeDefinition.is_enabled.is_(True))
            .order_by(AttributeDefinition.display_order.asc(), AttributeDefinition.name.asc())
        )
        try:
            rule_result = await asyncio.wait_for(
                db.execute(rules_stmt),
                timeout=_PARSER_RULE_TIMEOUT_SECONDS,
            )
            attr_result = await asyncio.wait_for(
                db.execute(attrs_stmt),
                timeout=_PARSER_RULE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "parser_rule_cache.refresh timed out after %.2fs",
                _PARSER_RULE_TIMEOUT_SECONDS,
            )
            if _parser_rules is not None:
                return _parser_rules
            return empty_rule_set()
        except SQLAlchemyError:
            logger.exception("parser_rule_cache.refresh failed; returning cached-or-empty rules")
            if _parser_rules is not None:
                return _parser_rules
            return empty_rule_set()

        requested_field_patterns: Dict[str, List[str]] = {}
        value_extract_patterns: Dict[str, List[str]] = {}
        detection_attribute_order: List[str] = []
        allowed_attribute_filters: set[str] = set()

        for row in list(rule_result.scalars().all() or []):
            group = _normalize_text(row.rule_group)
            target_key = _normalize_text(row.target_key)
            pattern = str(row.pattern or "").strip()
            if group == "requested_field":
                _add_pattern(requested_field_patterns, target_key, pattern)
            elif group == "value_extract":
                _add_pattern(value_extract_patterns, target_key, pattern)
                if target_key:
                    allowed_attribute_filters.add(target_key)
            elif group == "detection_order":
                if target_key and target_key not in detection_attribute_order:
                    detection_attribute_order.append(target_key)
                    allowed_attribute_filters.add(target_key)
            elif group == "allowed_attribute":
                if target_key:
                    allowed_attribute_filters.add(target_key)

        for raw_name in list(attr_result.scalars().all() or []):
            name = _normalize_text(raw_name)
            if name:
                allowed_attribute_filters.add(name)

        for attr in value_extract_patterns.keys():
            if attr:
                allowed_attribute_filters.add(attr)

        _parser_rules = build_rule_set(
            requested_field_patterns=requested_field_patterns,
            value_extract_patterns=value_extract_patterns,
            detection_attribute_order=detection_attribute_order,
            allowed_attribute_filters=allowed_attribute_filters,
        )
        return _parser_rules


async def get_parser_rules(db: AsyncSession) -> ParserRuleSet:
    if _parser_rules is not None:
        return _parser_rules
    try:
        return await refresh_parser_rule_cache(db)
    except Exception:
        logger.exception("parser_rule_cache.get failed; returning empty rules")
        return empty_rule_set()


def get_cached_parser_rules() -> ParserRuleSet:
    return _parser_rules or empty_rule_set()
