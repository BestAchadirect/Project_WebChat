from typing import List, Optional
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc, or_, func

from app.api.deps import get_db
from app.models.product import Product, StockStatus
from app.models.product_group import ProductGroup
from app.schemas.product import Product as ProductSchema, ProductUpdate, ProductListResponse, ProductBulkUpdateRequest

router = APIRouter()

ALLOWED_BULK_UPDATE_FIELDS = {
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

@router.get("/", response_model=ProductListResponse)
async def list_products(
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    category: Optional[str] = None,
    visibility: Optional[bool] = None,
    is_featured: Optional[bool] = None,
    material: Optional[str] = None,
    jewelry_type: Optional[str] = None,
    master_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    db: AsyncSession = Depends(get_db)
):
    # Base query for products
    query = select(Product).order_by(desc(Product.created_at))
    
    # Base query for count
    count_query = select(func.count()).select_from(Product)
    
    # Filter conditions
    filters = []
    
    if search:
        filters.append(
            or_(
                Product.name.ilike(f"%{search}%"),
                Product.sku.ilike(f"%{search}%"),
                Product.master_code.ilike(f"%{search}%")
            )
        )
    
    if visibility is not None:
        filters.append(Product.visibility == visibility)
        
    if is_featured is not None:
        filters.append(Product.is_featured == is_featured)

    if material:
        filters.append(Product.material == material)
        
    if jewelry_type:
        filters.append(Product.jewelry_type == jewelry_type)
        
    if master_code:
        filters.append(Product.master_code == master_code)
        
    if min_price is not None:
        filters.append(Product.price >= min_price)
        
    if max_price is not None:
        filters.append(Product.price <= max_price)

    # Apply filters to both queries
    for f in filters:
        query = query.where(f)
        count_query = count_query.where(f)
    
    # Execute count
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    # Apply pagination and execute product list
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    products = result.scalars().all()
    
    # Map to schema
    item_schemas = [
        ProductSchema(
            id=str(p.id),
            object_id=p.object_id,
            sku=p.sku,
            legacy_sku=p.legacy_sku,
            name=p.name,
            price=p.price,
            image_url=p.image_url,
            url=p.product_url,
            description=p.description,
            in_stock=p.stock_status == StockStatus.in_stock,
            stock_status=p.stock_status,
            visibility=p.visibility,
            is_featured=p.is_featured,
            priority=p.priority,
            master_code=p.master_code,
            jewelry_type=p.jewelry_type,
            material=p.material,
            length=p.length,
            size=p.size,
            cz_color=p.cz_color,
            design=p.design,
            crystal_color=p.crystal_color,
            color=p.color,
            gauge=p.gauge,
            size_in_pack=p.size_in_pack,
            rack=p.rack,
            height=p.height,
            packing_option=p.packing_option,
            pincher_size=p.pincher_size,
            ring_size=p.ring_size,
            quantity_in_bulk=p.quantity_in_bulk,
            opal_color=p.opal_color,
            threading=p.threading,
            outer_diameter=p.outer_diameter,
            pearl_color=p.pearl_color
        ) for p in products
    ]
    
    return ProductListResponse(
        items=item_schemas,
        total=total,
        offset=offset,
        limit=limit
    )

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
    for field, value in update_data.items():
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
        
    await db.commit()
    await db.refresh(product)
    
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
        jewelry_type=product.jewelry_type,
        material=product.material,
        length=product.length,
        size=product.size,
        cz_color=product.cz_color,
        design=product.design,
        crystal_color=product.crystal_color,
        color=product.color,
        gauge=product.gauge,
        size_in_pack=product.size_in_pack,
        rack=product.rack,
        height=product.height,
        packing_option=product.packing_option,
        pincher_size=product.pincher_size,
        ring_size=product.ring_size,
        quantity_in_bulk=product.quantity_in_bulk,
        opal_color=product.opal_color,
        threading=product.threading,
        outer_diameter=product.outer_diameter,
        pearl_color=product.pearl_color
    )

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
    update_data = {k: v for k, v in update_data.items() if k in ALLOWED_BULK_UPDATE_FIELDS}

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    update_data["updated_at"] = datetime.utcnow()

    result = await db.execute(
        update(Product)
        .where(Product.id.in_(payload.product_ids))
        .values(**update_data)
    )
    await db.commit()
    return {"status": "success", "updated": result.rowcount or 0}
