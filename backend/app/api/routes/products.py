from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, desc, or_, func, and_, false, text

from app.api.deps import get_db
from app.models.product import Product, ProductEmbedding, StockStatus
from app.models.product_group import ProductGroup
from app.models.product_change import ProductChange
from app.models.product_attribute import ProductAttributeValue
from app.schemas.product import Product as ProductSchema, ProductUpdate, ProductListResponse, ProductBulkUpdateRequest
from app.services.catalog.attributes_service import eav_service
from app.services.imports.service import data_import_service
from app.services.catalog.attribute_sync_service import product_attribute_sync_service
from app.utils.pagination import normalize_pagination

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


def _normalize_id_list(ids: List[UUID]) -> List[UUID]:
    deduped: List[UUID] = []
    seen: set[UUID] = set()
    for item in ids:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _normalize_sku_list(skus: List[str]) -> List[str]:
    deduped: List[str] = []
    seen: set[str] = set()
    for sku in skus:
        item = (sku or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped

@router.get("/", response_model=ProductListResponse)
async def list_products(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=9999),
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
    if "limit" in request.query_params or "offset" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="limit/offset pagination is no longer supported. Use page and pageSize.",
        )

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
    
    safe_page, total_pages, offset = normalize_pagination(
        total_items=total,
        page=page,
        page_size=page_size,
    )

    # Apply pagination and execute product list
    query = query.offset(offset).limit(page_size)
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
        totalItems=total,
        page=safe_page,
        pageSize=page_size,
        totalPages=total_pages,
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
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    product = await db.get(Product, product_id)
    if not product:
        # Try to find by string ID if UUID fails? Database uses UUID for ID.
        # But if the input is a string that looks like UUID it should work.
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = product_in.model_dump(exclude_unset=True, exclude_none=False)
    attr_updates = {k: v for k, v in update_data.items() if k in ATTRIBUTE_FIELDS}
    base_updates = {k: v for k, v in update_data.items() if k not in ATTRIBUTE_FIELDS}
    stock_status_updated = False
    for field, value in base_updates.items():
        if field == "master_code":
            continue
        if value is None and field != "description":
            continue
        setattr(product, field, value)
        if field == "stock_status" and value is not None:
            stock_status_updated = True

    if "master_code" in base_updates and base_updates.get("master_code"):
        master_code = str(base_updates.get("master_code"))
        stmt = select(ProductGroup).where(ProductGroup.master_code == master_code)
        result = await db.execute(stmt)
        group = result.scalar_one_or_none()
        if not group:
            group = ProductGroup(master_code=master_code)
            db.add(group)
            await db.flush()
        product.master_code = master_code
        product.group_id = group.id

    if stock_status_updated:
        product.last_stock_sync_at = datetime.utcnow()

    if attr_updates:
        await product_attribute_sync_service.apply_dual_canonical(
            db=db,
            product=product,
            attribute_updates=attr_updates,
            drop_empty=True,
        )

    search_changed = False
    if base_updates or attr_updates:
        search_changed = product_attribute_sync_service.recompute_product_search_fields(product=product)
    product.updated_at = datetime.utcnow()
        
    await db.commit()
    if search_changed and background_tasks:
        background_tasks.add_task(
            data_import_service._generate_product_embeddings_background,
            [product.id],
        )
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
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    product_ids = _normalize_id_list(payload.product_ids)
    if not product_ids:
        raise HTTPException(status_code=400, detail="product_ids cannot be empty")

    update_data = payload.updates.model_dump(exclude_unset=True, exclude_none=False)
    attr_updates = {k: v for k, v in update_data.items() if k in ALLOWED_BULK_UPDATE_FIELDS}
    base_updates = {k: v for k, v in update_data.items() if k not in ALLOWED_BULK_UPDATE_FIELDS}

    if not base_updates and not attr_updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    result = await db.execute(select(Product).where(Product.id.in_(product_ids)))
    products = list(result.scalars().all())
    if not products:
        return {"status": "success", "updated": 0, "attribute_updates": len(attr_updates)}

    master_code = base_updates.get("master_code")
    target_group_id = None
    if master_code:
        stmt = select(ProductGroup).where(ProductGroup.master_code == str(master_code))
        group_result = await db.execute(stmt)
        group = group_result.scalar_one_or_none()
        if not group:
            group = ProductGroup(master_code=str(master_code))
            db.add(group)
            await db.flush()
        target_group_id = group.id

    now_utc = datetime.utcnow()
    embed_ids: List[UUID] = []
    for product in products:
        stock_status_updated = False
        for field, value in base_updates.items():
            if field == "master_code":
                if value:
                    product.master_code = str(value)
                    if target_group_id:
                        product.group_id = target_group_id
                continue
            if value is None and field != "description":
                continue
            setattr(product, field, value)
            if field == "stock_status" and value is not None:
                stock_status_updated = True

        if stock_status_updated:
            product.last_stock_sync_at = now_utc

        if attr_updates:
            await product_attribute_sync_service.apply_dual_canonical(
                db=db,
                product=product,
                attribute_updates=attr_updates,
                drop_empty=True,
            )
        if base_updates or attr_updates:
            if product_attribute_sync_service.recompute_product_search_fields(product=product):
                embed_ids.append(product.id)
        product.updated_at = now_utc

    await db.commit()
    if embed_ids and background_tasks:
        background_tasks.add_task(
            data_import_service._generate_product_embeddings_background,
            _normalize_id_list(embed_ids),
        )
    return {"status": "success", "updated": len(products), "attribute_updates": len(attr_updates)}


@router.post("/bulk/delete-sku")
async def hard_delete_products_by_sku(
    skus: List[str],
    db: AsyncSession = Depends(get_db),
):
    normalized_skus = _normalize_sku_list(skus)
    if not normalized_skus:
        raise HTTPException(status_code=400, detail="skus cannot be empty")

    result = await db.execute(
        select(Product.id, Product.sku).where(Product.sku.in_(normalized_skus))
    )
    rows = result.all()
    if not rows:
        return {
            "status": "success",
            "requested": len(normalized_skus),
            "deleted": 0,
            "deleted_skus": [],
            "not_found_skus": normalized_skus,
        }

    product_ids = [row.id for row in rows]
    deleted_skus = [row.sku for row in rows]
    deleted_lookup = set(deleted_skus)
    not_found_skus = [sku for sku in normalized_skus if sku not in deleted_lookup]

    await db.execute(delete(ProductEmbedding).where(ProductEmbedding.product_id.in_(product_ids)))
    await db.execute(delete(ProductAttributeValue).where(ProductAttributeValue.product_id.in_(product_ids)))
    await db.execute(delete(ProductChange).where(ProductChange.product_id.in_(product_ids)))
    await db.execute(delete(Product).where(Product.id.in_(product_ids)))
    await db.commit()

    return {
        "status": "success",
        "requested": len(normalized_skus),
        "deleted": len(deleted_skus),
        "deleted_skus": deleted_skus,
        "not_found_skus": not_found_skus,
    }


@router.delete("/sku/{sku}")
async def hard_delete_product_by_sku(
    sku: str,
    db: AsyncSession = Depends(get_db),
):
    normalized_list = _normalize_sku_list([sku])
    normalized_sku = normalized_list[0] if normalized_list else ""
    if not normalized_sku:
        raise HTTPException(status_code=400, detail="SKU cannot be empty")

    result = await db.execute(select(Product).where(Product.sku == normalized_sku))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product_id = product.id

    await db.execute(delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id))
    await db.execute(delete(ProductAttributeValue).where(ProductAttributeValue.product_id == product_id))
    await db.execute(delete(ProductChange).where(ProductChange.product_id == product_id))
    await db.execute(delete(Product).where(Product.id == product_id))
    await db.commit()

    return {"status": "success", "sku": normalized_sku, "deleted": True}


@router.get("/health/attribute-drift")
async def product_attribute_drift_health(
    sample_limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    count_sql = text(
        """
        WITH eav AS (
            SELECT pav.product_id, ad.name, NULLIF(BTRIM(pav.value), '') AS value
            FROM product_attribute_values pav
            JOIN attribute_definitions ad ON ad.id = pav.attribute_id
        ),
        json_pairs AS (
            SELECT p.id AS product_id, kv.key AS name, NULLIF(BTRIM(kv.value), '') AS value
            FROM products p
            LEFT JOIN LATERAL jsonb_each_text(COALESCE(p.attributes, '{}'::jsonb)) kv ON TRUE
        ),
        paired AS (
            SELECT
                COALESCE(e.product_id, j.product_id) AS product_id,
                COALESCE(e.name, j.name) AS name,
                e.value AS eav_value,
                j.value AS json_value
            FROM eav e
            FULL OUTER JOIN json_pairs j
              ON e.product_id = j.product_id
             AND e.name = j.name
        )
        SELECT COUNT(*)
        FROM paired
        WHERE COALESCE(eav_value, '') <> COALESCE(json_value, '')
        """
    )
    sample_sql = text(
        """
        WITH eav AS (
            SELECT pav.product_id, ad.name, NULLIF(BTRIM(pav.value), '') AS value
            FROM product_attribute_values pav
            JOIN attribute_definitions ad ON ad.id = pav.attribute_id
        ),
        json_pairs AS (
            SELECT p.id AS product_id, kv.key AS name, NULLIF(BTRIM(kv.value), '') AS value
            FROM products p
            LEFT JOIN LATERAL jsonb_each_text(COALESCE(p.attributes, '{}'::jsonb)) kv ON TRUE
        ),
        paired AS (
            SELECT
                COALESCE(e.product_id, j.product_id) AS product_id,
                COALESCE(e.name, j.name) AS name,
                e.value AS eav_value,
                j.value AS json_value
            FROM eav e
            FULL OUTER JOIN json_pairs j
              ON e.product_id = j.product_id
             AND e.name = j.name
        )
        SELECT p.sku, paired.name, paired.eav_value, paired.json_value
        FROM paired
        JOIN products p ON p.id = paired.product_id
        WHERE COALESCE(paired.eav_value, '') <> COALESCE(paired.json_value, '')
        ORDER BY p.sku, paired.name
        LIMIT :sample_limit
        """
    )
    mismatch_count = int((await db.execute(count_sql)).scalar() or 0)
    sample_rows = (await db.execute(sample_sql, {"sample_limit": sample_limit})).all()
    samples = [
        {
            "sku": row.sku,
            "attribute": row.name,
            "eav_value": row.eav_value,
            "json_value": row.json_value,
        }
        for row in sample_rows
    ]
    return {
        "mismatch_count": mismatch_count,
        "sample_limit": sample_limit,
        "samples": samples,
    }
