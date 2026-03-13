import asyncio
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.dependencies import get_db
from app.schemas.chat_alias import SynonymEntry, SynonymCreateRequest, SynonymUpdateRequest, SynonymAttribute
from app.services.chat import alias_cache
from app.models.product_attribute import AttributeDefinition

router = APIRouter()


@router.get("", response_model=List[SynonymEntry])
async def list_aliases(db: AsyncSession = Depends(get_db)) -> List[SynonymEntry]:
    try:
        aliases = await alias_cache.list_aliases(db)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Database timeout while loading aliases") from exc
    output: List[SynonymEntry] = []
    for alias in aliases:
        attribute_name = getattr(getattr(alias, "attribute", None), "name", "") or ""
        output.append(
            SynonymEntry(
                id=alias.id,
                attribute=attribute_name,
                raw_value=str(alias.raw_value or ""),
                canonical_value=str(alias.canonical_value or ""),
                is_active=bool(alias.is_active),
            )
        )
    return output


@router.post("", response_model=SynonymEntry)
async def create_alias(
    request: SynonymCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> SynonymEntry:
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
        .where(AttributeDefinition.is_enabled.is_(True))
        .order_by(AttributeDefinition.display_order, AttributeDefinition.name)
    )
    result = await db.execute(stmt)
    attributes = result.scalars().all()
    return [
        SynonymAttribute(name=attr.name, display_name=attr.display_name)
        for attr in attributes
    ]
