from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc, or_, func, and_, false

from app.api.deps import get_db
from app.models.product import Product, StockStatus
from app.models.product_group import ProductGroup
from app.models.product_attribute import ProductAttributeValue
from app.schemas.product import Product as ProductSchema, ProductUpdate, ProductListResponse, ProductBulkUpdateRequest
from app.services.eav_service import eav_service

router = APIRouter()

ATTRIBUTE_FIELDS = {
    "material",
    "jewelry_type",
    "color",
    "gauge",
    "threading",
    "length",
    "size",
    "cz_color",
    "opal_color",
    "outer_diameter",
    "design",
    "crystal_color",
    "pearl_color",
    "rack",
    "height",
    "packing_option",
    "pincher_size",
    "ring_size",
    "size_in_pack",
    "quantity_in_bulk",
}
ALLOWED_BULK_UPDATE_FIELDS = set(ATTRIBUTE_FIELDS)

FILTER_FACETS = [
    "material",
    "jewelry_type",
    "color",
    "gauge",
    "threading",
    "length",
    "size",
    "cz_color",
    "opal_color",
    "outer_diameter",
    "design",
    "crystal_color",
    "pearl_color",
    "rack",
    "height",
    "packing_option",
    "pincher_size",
    "ring_size",
    "size_in_pack",
    "quantity_in_bulk",
    "category",
]


def _normalize_filter_values(values: Optional[List[str]]) -> List[str]:
    if not values:
        return []
    items: List[str] = []
    for entry in values:
        if entry is None:
            continue
        for part in str(entry).split(","):
            item = part.strip()
            if item:
                items.append(item)
    # Preserve order while de-duping
    seen = set()
    deduped: List[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _collect_attr_filters(**kwargs: Optional[List[str]]) -> Dict[str, List[str]]:
    filters: Dict[str, List[str]] = {}
    for name, raw in kwargs.items():
        values = _normalize_filter_values(raw)
        if values:
            filters[name] = values
    return filters


def _apply_base_filters(
    query,
    *,
    search: Optional[str],
    visibility: Optional[bool],
    is_featured: Optional[bool],
    master_code: Optional[str],
    min_price: Optional[float],
    max_price: Optional[float],
):
    if search:
        query = query.where(
            or_(
                Product.name.ilike(f"%{search}%"),
                Product.sku.ilike(f"%{search}%"),
                Product.master_code.ilike(f"%{search}%"),
            )
        )

    if visibility is not None:
        query = query.where(Product.visibility == visibility)

    if is_featured is not None:
        query = query.where(Product.is_featured == is_featured)

    if master_code:
        query = query.where(Product.master_code == master_code)

    if min_price is not None:
        query = query.where(Product.price >= min_price)

    if max_price is not None:
        query = query.where(Product.price <= max_price)

    return query

def _build_product_schema(product: Product, attrs: dict) -> ProductSchema:
    return ProductSchema(
        id=str(product.id),
        object_id=product.object_id,
        sku=product.sku,
        legacy_sku=product.legacy_sku,
        name=product.name,
        price=product.price,
        image_url=product.image_url,
        url=product.product_url,
        description=product.description,
        in_stock=product.stock_status == StockStatus.in_stock,
        stock_status=product.stock_status,
        visibility=product.visibility,
        is_featured=product.is_featured,
        priority=product.priority,
        master_code=product.master_code,
        jewelry_type=attrs.get("jewelry_type"),
        material=attrs.get("material"),
        length=attrs.get("length"),
        size=attrs.get("size"),
        cz_color=attrs.get("cz_color"),
        design=attrs.get("design"),
        crystal_color=attrs.get("crystal_color"),
        color=attrs.get("color"),
        gauge=attrs.get("gauge"),
        size_in_pack=attrs.get("size_in_pack"),
        rack=attrs.get("rack"),
        height=attrs.get("height"),
        packing_option=attrs.get("packing_option"),
        pincher_size=attrs.get("pincher_size"),
        ring_size=attrs.get("ring_size"),
        quantity_in_bulk=attrs.get("quantity_in_bulk"),
        opal_color=attrs.get("opal_color"),
        threading=attrs.get("threading"),
        outer_diameter=attrs.get("outer_diameter"),
        pearl_color=attrs.get("pearl_color"),
    )


async def _apply_attribute_filters(db, query, count_query, filters: Dict[str, List[str]]):
    if not filters:
        return query, count_query
    definitions = await eav_service.get_definitions_by_name(db, list(filters.keys()))
    if len(definitions) != len(filters):
        return query.where(false()), count_query.where(false())
    conditions = []
    for name, values in filters.items():
        definition = definitions.get(name)
        if not definition:
            return query.where(false()), count_query.where(false())
        for value in values:
            conditions.append(
                and_(
                    ProductAttributeValue.attribute_id == definition.id,
                    ProductAttributeValue.value == str(value),
                )
            )
    subq = (
        select(ProductAttributeValue.product_id)
        .where(or_(*conditions))
        .group_by(ProductAttributeValue.product_id)
        .having(func.count(func.distinct(ProductAttributeValue.attribute_id)) == len(filters))
    ).subquery()
    query = query.where(Product.id.in_(select(subq.c.product_id)))
    count_query = count_query.where(Product.id.in_(select(subq.c.product_id)))
    return query, count_query

@router.get("/", response_model=ProductListResponse)
async def list_products(
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    category: Optional[List[str]] = Query(None),
    visibility: Optional[bool] = None,
    is_featured: Optional[bool] = None,
    material: Optional[List[str]] = Query(None),
    jewelry_type: Optional[List[str]] = Query(None),
    color: Optional[List[str]] = Query(None),
    gauge: Optional[List[str]] = Query(None),
    threading: Optional[List[str]] = Query(None),
    length: Optional[List[str]] = Query(None),
    size: Optional[List[str]] = Query(None),
    cz_color: Optional[List[str]] = Query(None),
    opal_color: Optional[List[str]] = Query(None),
    outer_diameter: Optional[List[str]] = Query(None),
    design: Optional[List[str]] = Query(None),
    crystal_color: Optional[List[str]] = Query(None),
    pearl_color: Optional[List[str]] = Query(None),
    rack: Optional[List[str]] = Query(None),
    height: Optional[List[str]] = Query(None),
    packing_option: Optional[List[str]] = Query(None),
    pincher_size: Optional[List[str]] = Query(None),
    ring_size: Optional[List[str]] = Query(None),
    size_in_pack: Optional[List[str]] = Query(None),
    quantity_in_bulk: Optional[List[str]] = Query(None),
    master_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    db: AsyncSession = Depends(get_db)
):
    # Base query for products
    query = select(Product).order_by(desc(Product.created_at))
    
    # Base query for count
    count_query = select(func.count()).select_from(Product)
    
    query = _apply_base_filters(
        query,
        search=search,
        visibility=visibility,
        is_featured=is_featured,
        master_code=master_code,
        min_price=min_price,
        max_price=max_price,
    )
    count_query = _apply_base_filters(
        count_query,
        search=search,
        visibility=visibility,
        is_featured=is_featured,
        master_code=master_code,
        min_price=min_price,
        max_price=max_price,
    )

    attr_filters = _collect_attr_filters(
        material=material,
        jewelry_type=jewelry_type,
        color=color,
        gauge=gauge,
        threading=threading,
        length=length,
        size=size,
        cz_color=cz_color,
        opal_color=opal_color,
        outer_diameter=outer_diameter,
        design=design,
        crystal_color=crystal_color,
        pearl_color=pearl_color,
        rack=rack,
        height=height,
        packing_option=packing_option,
        pincher_size=pincher_size,
        ring_size=ring_size,
        size_in_pack=size_in_pack,
        quantity_in_bulk=quantity_in_bulk,
        category=category,
    )
        
    if attr_filters:
        query, count_query = await _apply_attribute_filters(db, query, count_query, attr_filters)
    
    # Execute count
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    # Apply pagination and execute product list
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    products = result.scalars().all()
    
    attr_map = await eav_service.get_product_attributes(db, [p.id for p in products])

    # Map to schema
    item_schemas = []
    for p in products:
        attrs = attr_map.get(p.id, {})
        item_schemas.append(_build_product_schema(p, attrs))
    
    return ProductListResponse(
        items=item_schemas,
        total=total,
        offset=offset,
        limit=limit
    )


@router.get("/filters")
async def list_product_filters(
    search: Optional[str] = None,
    category: Optional[List[str]] = Query(None),
    visibility: Optional[bool] = None,
    is_featured: Optional[bool] = None,
    material: Optional[List[str]] = Query(None),
    jewelry_type: Optional[List[str]] = Query(None),
    color: Optional[List[str]] = Query(None),
    gauge: Optional[List[str]] = Query(None),
    threading: Optional[List[str]] = Query(None),
    length: Optional[List[str]] = Query(None),
    size: Optional[List[str]] = Query(None),
    cz_color: Optional[List[str]] = Query(None),
    opal_color: Optional[List[str]] = Query(None),
    outer_diameter: Optional[List[str]] = Query(None),
    design: Optional[List[str]] = Query(None),
    crystal_color: Optional[List[str]] = Query(None),
    pearl_color: Optional[List[str]] = Query(None),
    rack: Optional[List[str]] = Query(None),
    height: Optional[List[str]] = Query(None),
    packing_option: Optional[List[str]] = Query(None),
    pincher_size: Optional[List[str]] = Query(None),
    ring_size: Optional[List[str]] = Query(None),
    size_in_pack: Optional[List[str]] = Query(None),
    quantity_in_bulk: Optional[List[str]] = Query(None),
    master_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    db: AsyncSession = Depends(get_db),
):
    base_query = select(Product.id)
    base_query = _apply_base_filters(
        base_query,
        search=search,
        visibility=visibility,
        is_featured=is_featured,
        master_code=master_code,
        min_price=min_price,
        max_price=max_price,
    )

    attr_filters = _collect_attr_filters(
        material=material,
        jewelry_type=jewelry_type,
        color=color,
        gauge=gauge,
        threading=threading,
        length=length,
        size=size,
        cz_color=cz_color,
        opal_color=opal_color,
        outer_diameter=outer_diameter,
        design=design,
        crystal_color=crystal_color,
        pearl_color=pearl_color,
        rack=rack,
        height=height,
        packing_option=packing_option,
        pincher_size=pincher_size,
        ring_size=ring_size,
        size_in_pack=size_in_pack,
        quantity_in_bulk=quantity_in_bulk,
        category=category,
    )

    if attr_filters:
        base_query, _ = await _apply_attribute_filters(db, base_query, base_query, attr_filters)

    base_subq = base_query.subquery()
    total_result = await db.execute(select(func.count()).select_from(base_subq))
    total = total_result.scalar() or 0

    definitions = await eav_service.get_definitions_by_name(db, FILTER_FACETS)
    if not definitions:
        return {"total": total, "filters": {}}

    attr_id_to_name = {definition.id: name for name, definition in definitions.items()}
    stmt = (
        select(
            ProductAttributeValue.attribute_id,
            ProductAttributeValue.value,
            func.count(func.distinct(ProductAttributeValue.product_id)).label("count"),
        )
        .join(base_subq, ProductAttributeValue.product_id == base_subq.c.id)
        .where(ProductAttributeValue.attribute_id.in_(attr_id_to_name.keys()))
        .group_by(ProductAttributeValue.attribute_id, ProductAttributeValue.value)
        .order_by(ProductAttributeValue.attribute_id, func.count(func.distinct(ProductAttributeValue.product_id)).desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    filters_payload: Dict[str, List[Dict[str, Any]]] = {name: [] for name in FILTER_FACETS}
    for attribute_id, value, count in rows:
        name = attr_id_to_name.get(attribute_id)
        if not name or value is None:
            continue
        filters_payload.setdefault(name, []).append({"value": value, "count": int(count)})

    return {"total": total, "filters": filters_payload}

@router.put("/{product_id}", response_model=ProductSchema)
async def update_product(
    product_id: UUID,
    product_in: ProductUpdate,
    db: AsyncSession = Depends(get_db)
):
    product = await db.get(Product, product_id)
    if not product:
        # Try to find by string ID if UUID fails? Database uses UUID for ID.
        # But if the input is a string that looks like UUID it should work.
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = product_in.model_dump(exclude_unset=True, exclude_none=True)
    attr_updates = {k: v for k, v in update_data.items() if k in ATTRIBUTE_FIELDS}
    base_updates = {k: v for k, v in update_data.items() if k not in ATTRIBUTE_FIELDS}
    for field, value in base_updates.items():
        setattr(product, field, value)

    if "master_code" in update_data:
        master_code = update_data.get("master_code")
        if master_code:
            stmt = select(ProductGroup).where(ProductGroup.master_code == master_code)
            result = await db.execute(stmt)
            group = result.scalar_one_or_none()
            if not group:
                group = ProductGroup(master_code=master_code)
                db.add(group)
                await db.flush()
            product.group_id = group.id

    if attr_updates:
        if not base_updates:
            product.updated_at = datetime.utcnow()
        await eav_service.upsert_product_attributes(
            db,
            product_id=product.id,
            attributes=attr_updates,
        )
        
    await db.commit()
    await db.refresh(product)
    attr_map = await eav_service.get_product_attributes(db, [product.id])
    return _build_product_schema(product, attr_map.get(product.id, {}))

@router.post("/bulk/hide")
async def bulk_hide_products(
    product_ids: List[UUID],
    db: AsyncSession = Depends(get_db)
):
    await db.execute(
        update(Product)
        .where(Product.id.in_(product_ids))
        .values(visibility=False)
    )
    await db.commit()
    return {"status": "success", "count": len(product_ids)}

@router.post("/bulk/show")
async def bulk_show_products(
    product_ids: List[UUID],
    db: AsyncSession = Depends(get_db)
):
    await db.execute(
        update(Product)
        .where(Product.id.in_(product_ids))
        .values(visibility=True)
    )
    await db.commit()
    return {"status": "success", "count": len(product_ids)}

@router.post("/bulk/update")
async def bulk_update_products(
    payload: ProductBulkUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    if not payload.product_ids:
        raise HTTPException(status_code=400, detail="product_ids cannot be empty")

    update_data = payload.updates.model_dump(exclude_unset=True)
    attr_updates = {k: v for k, v in update_data.items() if k in ALLOWED_BULK_UPDATE_FIELDS}
    base_updates = {k: v for k, v in update_data.items() if k not in ALLOWED_BULK_UPDATE_FIELDS}

    if not base_updates and not attr_updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    base_updates["updated_at"] = datetime.utcnow()

    result = None
    if base_updates:
        result = await db.execute(
            update(Product)
            .where(Product.id.in_(payload.product_ids))
            .values(**base_updates)
        )
    if attr_updates:
        await eav_service.bulk_upsert_product_attributes(
            db,
            product_ids=payload.product_ids,
            attributes=attr_updates,
        )
    await db.commit()
    updated_count = result.rowcount if result is not None else 0
    return {"status": "success", "updated": updated_count, "attribute_updates": len(attr_updates)}
