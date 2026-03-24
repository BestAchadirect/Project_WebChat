from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_attribute import AttributeDefinition, FacetValueAlias
from app.core.config import settings

_alias_map: Dict[str, Dict[str, str]] = {}
_alias_list: List[FacetValueAlias] = []
_cache_lock = asyncio.Lock()
_ALIAS_REFRESH_TIMEOUT_SECONDS = float(getattr(settings, "ALIASES_REFRESH_TIMEOUT_SECONDS", 5.0))
logger = logging.getLogger(__name__)


def _normalize_value(value: Optional[str]) -> str:
    return (str(value or "").strip() or "").lower()


async def refresh_alias_cache(db: AsyncSession) -> Dict[str, Dict[str, str]]:
    global _alias_map, _alias_list
    async with _cache_lock:
        if not hasattr(db, "execute"):
            logger.debug("alias_cache.refresh_alias_cache received db without execute(); returning empty cache")
            _alias_map = {}
            _alias_list = []
            return {}
        stmt = (
            select(FacetValueAlias, AttributeDefinition)
            .join(AttributeDefinition, FacetValueAlias.attribute_id == AttributeDefinition.id)
            .where(FacetValueAlias.is_active.is_(True))
        )
        try:
            result = await asyncio.wait_for(db.execute(stmt), timeout=_ALIAS_REFRESH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("alias_cache.refresh_alias_cache timed out after %.2fs", _ALIAS_REFRESH_TIMEOUT_SECONDS)
            raise
        alias_rows = []
        alias_map: Dict[str, Dict[str, str]] = {}
        if not hasattr(result, "all"):
            logger.debug("alias_cache.refresh_alias_cache received non-iterable result; returning empty cache")
            _alias_map = alias_map
            _alias_list = alias_rows
            return dict(_alias_map)
        try:
            rows = list(result.all() or [])
        except Exception:
            logger.exception("alias_cache.refresh_alias_cache could not materialize rows; returning empty cache")
            _alias_map = alias_map
            _alias_list = alias_rows
            return dict(_alias_map)
        for alias, attribute in rows:
            attr_name = str(getattr(attribute, "name", "") or "").strip().lower()
            raw_norm = _normalize_value(alias.raw_value_norm or alias.raw_value)
            canonical_norm = _normalize_value(alias.canonical_value_norm or alias.canonical_value)
            if not attr_name or not raw_norm or not canonical_norm:
                continue
            alias_map.setdefault(attr_name, {})[raw_norm] = canonical_norm
            alias.attribute = attribute
            alias_rows.append(alias)
        _alias_map = alias_map
        _alias_list = alias_rows
        return dict(_alias_map)


async def get_alias_map(db: AsyncSession) -> Dict[str, Dict[str, str]]:
    if _alias_map:
        return _alias_map
    return await refresh_alias_cache(db)


def alias_lookup(alias_map: Dict[str, Dict[str, str]], *, attribute: str, value: str) -> Optional[str]:
    return alias_map.get(attribute, {}).get((value or "").strip().lower())


async def list_aliases(db: AsyncSession) -> List[FacetValueAlias]:
    if _alias_list:
        return list(_alias_list)
    await refresh_alias_cache(db)
    return list(_alias_list)


async def create_alias(
    *,
    db: AsyncSession,
    attribute_name: str,
    raw_value: str,
    canonical_value: str,
) -> FacetValueAlias:
    stmt = select(AttributeDefinition).where(AttributeDefinition.name == attribute_name)
    result = await db.execute(stmt)
    attribute = result.scalar_one_or_none()
    if attribute is None:
        raise ValueError(f"Unknown attribute {attribute_name}")
    normalized_raw = (raw_value or "").strip()
    normalized_canonical = (canonical_value or "").strip()
    alias = FacetValueAlias(
        attribute_id=attribute.id,
        raw_value=normalized_raw,
        raw_value_norm=normalized_raw.lower(),
        canonical_value=normalized_canonical,
        canonical_value_norm=normalized_canonical.lower(),
        is_active=True,
    )
    db.add(alias)
    await db.commit()
    await db.refresh(alias)
    # Ensure attribute mapping is set
    alias.attribute = attribute
    await refresh_alias_cache(db)
    return alias


async def update_alias(
    *,
    db: AsyncSession,
    alias_id: int,
    raw_value: Optional[str] = None,
    canonical_value: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> FacetValueAlias:
    stmt = (
        select(FacetValueAlias)
        .join(AttributeDefinition, FacetValueAlias.attribute_id == AttributeDefinition.id)
        .where(FacetValueAlias.id == alias_id)
    )
    result = await db.execute(stmt)
    alias = result.scalar_one_or_none()
    if not alias:
        raise ValueError(f"Alias with id {alias_id} not found")

    if raw_value is not None:
        normalized_raw = str(raw_value).strip()
        alias.raw_value = normalized_raw
        alias.raw_value_norm = normalized_raw.lower()
    if canonical_value is not None:
        normalized_canonical = str(canonical_value).strip()
        alias.canonical_value = normalized_canonical
        alias.canonical_value_norm = normalized_canonical.lower()
    if is_active is not None:
        alias.is_active = is_active

    await db.commit()
    await db.refresh(alias)
    
    # Reload attribute for schema
    stmt_attr = select(AttributeDefinition).where(AttributeDefinition.id == alias.attribute_id)
    attr_result = await db.execute(stmt_attr)
    alias.attribute = attr_result.scalar_one()

    await refresh_alias_cache(db)
    return alias


async def delete_alias(
    *,
    db: AsyncSession,
    alias_id: int,
) -> bool:
    stmt = select(FacetValueAlias).where(FacetValueAlias.id == alias_id)
    result = await db.execute(stmt)
    alias = result.scalar_one_or_none()
    if not alias:
        return False
        
    await db.delete(alias)
    await db.commit()
    await refresh_alias_cache(db)
    return True
