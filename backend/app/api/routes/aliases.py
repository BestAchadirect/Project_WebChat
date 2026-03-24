import asyncio
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from typing import Dict, List

from app.dependencies import get_db
from app.schemas.chat_alias import (
    SynonymAlias,
    SynonymAttribute,
    SynonymCreateRequest,
    SynonymEntry,
    SynonymGroup,
    SynonymUpdateRequest,
)
from app.services.chat.runtime import alias_cache
from app.models.product_attribute import AttributeDefinition

router = APIRouter()
_INTERNAL_ATTRIBUTE_NAMES = frozenset({"source_id", "source_raw_sku"})


def _is_internal_attribute(name: str) -> bool:
    return str(name or "").strip().lower() in _INTERNAL_ATTRIBUTE_NAMES


@router.get("", response_model=List[SynonymGroup])
async def list_aliases(db: AsyncSession = Depends(get_db)) -> List[SynonymGroup]:
    try:
        aliases = await alias_cache.list_aliases(db)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Database timeout while loading aliases") from exc

    grouped: Dict[tuple[str, str], dict] = {}
    for alias in aliases:
        attribute = getattr(alias, "attribute", None)
        attribute_name = str(getattr(attribute, "name", "") or "").strip()
        if _is_internal_attribute(attribute_name):
            continue
        attribute_display = str(getattr(attribute, "display_name", attribute_name) or "").strip()
        canonical_value = str(alias.canonical_value or "").strip()
        raw_value = str(alias.raw_value or "").strip()
        if not attribute_name or not canonical_value:
            continue
        key = (attribute_name, canonical_value)
        group = grouped.setdefault(
            key,
            {
                "attribute": attribute_name,
                "attribute_display_name": attribute_display or attribute_name,
                "canonical_value": canonical_value,
                "synonyms": [],
            },
        )
        group["synonyms"].append(
            {
                "id": alias.id,
                "raw_value": raw_value,
                "is_active": bool(alias.is_active),
            }
        )

    groups = sorted(
        grouped.values(),
        key=lambda entry: (entry["attribute"].lower(), entry["canonical_value"].lower()),
    )
    return [
        SynonymGroup(
            attribute=entry["attribute"],
            attribute_display_name=entry["attribute_display_name"],
            canonical_value=entry["canonical_value"],
            synonyms=[
                SynonymAlias(**synonym) for synonym in entry["synonyms"]
            ],
        )
        for entry in groups
    ]


@router.post("", response_model=SynonymEntry)
async def create_alias(
    request: SynonymCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> SynonymEntry:
    if _is_internal_attribute(request.attribute):
        raise HTTPException(status_code=400, detail="Internal attributes are not editable in Synonym Rules")
    try:
        alias = await alias_cache.create_alias(
            db=db,
            attribute_name=request.attribute,
            raw_value=request.raw_value,
            canonical_value=request.canonical_value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    attribute_name = getattr(getattr(alias, "attribute", None), "name", "") or ""
    return SynonymEntry(
        id=alias.id,
        attribute=attribute_name,
        raw_value=str(alias.raw_value or ""),
        canonical_value=str(alias.canonical_value or ""),
        is_active=bool(alias.is_active),
    )


@router.put("/{alias_id}", response_model=SynonymEntry)
async def update_alias(
    alias_id: int = Path(...),
    request: SynonymUpdateRequest = None,
    db: AsyncSession = Depends(get_db),
) -> SynonymEntry:
    try:
        alias = await alias_cache.update_alias(
            db=db,
            alias_id=alias_id,
            raw_value=request.raw_value,
            canonical_value=request.canonical_value,
            is_active=request.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    attribute_name = getattr(getattr(alias, "attribute", None), "name", "") or ""
    return SynonymEntry(
        id=alias.id,
        attribute=attribute_name,
        raw_value=str(alias.raw_value or ""),
        canonical_value=str(alias.canonical_value or ""),
        is_active=bool(alias.is_active),
    )


@router.delete("/{alias_id}")
async def delete_alias(
    alias_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
):
    success = await alias_cache.delete_alias(db=db, alias_id=alias_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alias not found")
    return {"status": "success"}


@router.get("/attributes", response_model=List[SynonymAttribute])
async def list_attributes(db: AsyncSession = Depends(get_db)) -> List[SynonymAttribute]:
    stmt = (
        select(AttributeDefinition)
        .where(
            AttributeDefinition.is_enabled.is_(True),
            func.lower(AttributeDefinition.name).notin_(tuple(_INTERNAL_ATTRIBUTE_NAMES)),
        )
        .order_by(AttributeDefinition.display_order, AttributeDefinition.name)
    )
    result = await db.execute(stmt)
    attributes = result.scalars().all()
    return [
        SynonymAttribute(name=attr.name, display_name=attr.display_name)
        for attr in attributes
    ]
