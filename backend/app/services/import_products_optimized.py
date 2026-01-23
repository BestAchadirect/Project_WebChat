"""
Optimized batch processing implementation for import_products.

This is a replacement for the existing import_products method in data_import_service.py
It implements:
- Batch processing (1000 products per commit)
- Pre-loading caches to eliminate N+1 queries
- Progress tracking
- Better error handling with detailed logging
"""

async def import_products_optimized(
    self,
    db: AsyncSession,
    file: UploadFile,
    background_tasks: BackgroundTasks = None,
    uploaded_by: str | None = None
) -> Dict[str, Any]:
    """
    Optimized product import for handling 200k+ SKUs efficiently.
    """
    BATCH_SIZE = 1000  # Process 1000 products per commit
    
    content = await file.read()
    upload_record = await self._create_product_upload(
        db=db,
        content=content,
        filename=file.filename,
        content_type=file.content_type,
        uploaded_by=uploaded_by,
    )

    # Decode CSV and count total rows first
    text_content = content.decode("utf-8-sig")
    csv_reader_count = csv.DictReader(io.StringIO(text_content))
    total_rows = sum(1 for _ in csv_reader_count if _.get("sku"))
    
    # Reset for actual processing
    csv_reader = csv.DictReader(io.StringIO(text_content))

    stats = {"created": 0, "updated": 0, "errors": 0, "skipped": 0}
    error_details = []  # Collect error details for error_log
    
    try:
        # Update upload record with total rows
        upload_record.total_rows = total_rows
        upload_record.status = ProductUploadStatus.PROCESSING
        await db.commit()
        
        # PRE-LOAD CACHES - This eliminates N+1 queries
        logger.info(f"Pre-loading caches for {total_rows} products...")
        
        # Cache 1: Load all existing product SKUs
        stmt = select(Product.sku, Product.id).select_from(Product)
        result = await db.execute(stmt)
        existing_products_cache: Dict[str, UUID] = {row.sku: row.id for row in result}
        logger.info(f"Loaded {len(existing_products_cache)} existing products into cache")
        
        # Cache 2: Load all product groups
        stmt = select(ProductGroup.master_code, ProductGroup.id).select_from(ProductGroup)
        result = await db.execute(stmt)
        group_cache: Dict[str, UUID] = {row.master_code: row.id for row in result}
        logger.info(f"Loaded {len(group_cache)} product groups into cache")
        
        # Batch processing variables
        current_batch = []
        rows_processed = 0
        products_to_embed_ids = []
        
        for row_num, row in enumerate(csv_reader, start=1):
            try:
                # Basic validation
                if not row.get("sku"):
                    stats["skipped"] += 1
                    continue

                sku = row["sku"].strip()
                row_desc = row.get("description", "")
                
                # Process master_code and group
                master_code_raw = row.get("master_code")
                master_code = (master_code_raw.strip() if isinstance(master_code_raw, str) else master_code_raw) or None
                row_name = row.get("name")
                row_name = (row_name.strip() if isinstance(row_name, str) else row_name) or None
                display_name = master_code or row_name or sku
                
                # Get or create group (using cache)
                group_id: UUID | None = None
                if display_name:
                    if display_name in group_cache:
                        group_id = group_cache[display_name]
                    else:
                        # Create new group and add to cache
                        new_group = ProductGroup(master_code=display_name)
                        db.add(new_group)
                        await db.flush()
                        group_id = new_group.id
                        group_cache[display_name] = group_id
                
                # Parse all fields (same as before)
                object_id_raw = row.get("object_id")
                object_id = (object_id_raw.strip() if isinstance(object_id_raw, str) else object_id_raw) or None
                
                legacy_raw = row.get("legacy_sku")
                legacy_skus: List[str] = []
                if isinstance(legacy_raw, str) and legacy_raw.strip():
                    legacy_skus = [s.strip() for s in re.split(r"[|,]", legacy_raw) if s.strip()]

                stock_status = self._parse_stock_status(row.get("stock_status"))
                visibility = self._parse_bool(row.get("visibility"))
                is_featured = self._parse_bool(row.get("is_featured"))
                priority = self._parse_int(row.get("priority"))
                
                image_url = row.get("image_url")
                if isinstance(image_url, str):
                    image_url = image_url.strip() or None
                    
                product_url = row.get("product_url")
                if isinstance(product_url, str):
                    product_url = product_url.strip() or None
                
                # Parse attributes
                attributes: Dict[str, Any] = {}
                attributes_json_raw = row.get("attributes_json")
                if isinstance(attributes_json_raw, str) and attributes_json_raw.strip():
                    try:
                        parsed = json.loads(attributes_json_raw)
                        if isinstance(parsed, dict):
                            attributes.update(parsed)
                    except Exception:
                        pass
                
                for key in ATTRIBUTE_COLUMNS:
                    val = row.get(key)
                    if val is None:
                        continue
                    if isinstance(val, str):
                        val = val.strip()
                        if not val:
                            continue
                    if key in {"size_in_pack", "quantity_in_bulk"}:
                        parsed_int = self._parse_int(val)
                        if parsed_int is not None:
                            attributes[key] = parsed_int
                    else:
                        normalized = self._normalize_attribute_value(key, val)
                        if normalized is not None:
                            attributes[key] = normalized
                
                category_raw = row.get("category")
                category = category_raw.strip() if isinstance(category_raw, str) else category_raw
                if isinstance(category, str) and category.strip():
                    attributes["category"] = category.strip()
                
                # Check if product exists using cache
                is_update = sku in existing_products_cache
                
                if stock_status is None:
                    stock_status = "in_stock"
                
                # Build search text
                manual_keywords: List[str] = []
                search_keywords_raw = row.get("search_keywords")
                if isinstance(search_keywords_raw, str) and search_keywords_raw.strip():
                    for token in search_keywords_raw.split(","):
                        normalized = self._normalize_keyword(token)
                        if normalized:
                            manual_keywords.append(normalized)
                
                synonyms = self._build_search_synonyms(attributes)
                if manual_keywords:
                    synonyms = [*synonyms, *manual_keywords]
                    
                search_text = self._build_search_text(
                    display_name=display_name,
                    sku=sku,
                    object_id=object_id,
                    description=row_desc,
                    legacy_skus=legacy_skus,
                    synonyms=synonyms,
                    attributes=attributes,
                    attribute_columns=ATTRIBUTE_COLUMNS,
                )
                
                search_keywords = self._build_search_keywords(
                    display_name=display_name,
                    sku=sku,
                    legacy_skus=legacy_skus,
                    attributes=attributes,
                    keyword_columns=SEARCH_KEYWORD_COLUMNS,
                )
                if manual_keywords:
                    seen_keywords = set(search_keywords)
                    for keyword in manual_keywords:
                        if keyword not in seen_keywords:
                            seen_keywords.add(keyword)
                            search_keywords.append(keyword)
                            
                search_hash = self._hash_text(search_text)
                
                if is_update:
                    # Update existing product
                    product_id = existing_products_cache[sku]
                    stmt = select(Product).where(Product.id == product_id)
                    result = await db.execute(stmt)
                    existing_product = result.scalar_one()
                    
                    # Preserve legacy SKUs if not provided
                    if existing_product.legacy_sku and not legacy_skus:
                        legacy_skus = list(existing_product.legacy_sku)
                    
                    update_fields = {
                        "master_code": display_name,
                        "group_id": group_id,
                        "price": self._parse_float(row.get("price", 0)),
                        "currency": (getattr(settings, "BASE_CURRENCY", "USD") or "USD").upper(),
                        "description": row_desc,
                        "search_text": search_text,
                        "search_hash": search_hash,
                        "search_keywords": search_keywords,
                        "attributes": attributes or {},
                        "object_id": object_id,
                        "stock_status": stock_status,
                        "legacy_sku": legacy_skus,
                    }
                    
                    for k in ATTRIBUTE_COLUMNS:
                        if k in {"size_in_pack", "quantity_in_bulk"}:
                            update_fields[k] = self._parse_int(attributes.get(k))
                        else:
                            update_fields[k] = attributes.get(k)
                    
                    if image_url is not None:
                        update_fields["image_url"] = image_url
                    if product_url is not None:
                        update_fields["product_url"] = product_url
                    if visibility is not None:
                        update_fields["visibility"] = visibility
                    if is_featured is not None:
                        update_fields["is_featured"] = is_featured
                    if priority is not None:
                        update_fields["priority"] = priority
                    
                    # Track changes
                    changed_fields, old_values, new_values = self._collect_product_changes(
                        product=existing_product,
                        updates=update_fields,
                    )
                    
                    for field, value in update_fields.items():
                        setattr(existing_product, field, value)
                    
                    if changed_fields:
                        db.add(ProductChange(
                            upload_id=upload_record.id,
                            product_id=existing_product.id,
                            changed_fields=changed_fields,
                            old_values=old_values,
                            new_values=new_values,
                        ))
                    
                    stats["updated"] += 1
                    products_to_embed_ids.append(existing_product.id)
                    
                else:
                    # Create new product
                    new_product = Product(
                        sku=sku,
                        master_code=display_name,
                        group_id=group_id,
                        price=self._parse_float(row.get("price", 0)),
                        currency=(getattr(settings, "BASE_CURRENCY", "USD") or "USD").upper(),
                        description=row_desc,
                        image_url=image_url,
                        product_url=product_url,
                        object_id=object_id,
                        product_upload_id=upload_record.id,
                        search_text=search_text,
                        search_hash=search_hash,
                        stock_status=stock_status,
                        search_keywords=search_keywords,
                        attributes=attributes or {},
                        legacy_sku=legacy_skus,
                    )
                    
                    if visibility is not None:
                        new_product.visibility = visibility
                    if is_featured is not None:
                        new_product.is_featured = is_featured
                    if priority is not None:
                        new_product.priority = priority
                        
                    for k in ATTRIBUTE_COLUMNS:
                        if k in {"size_in_pack", "quantity_in_bulk"}:
                            setattr(new_product, k, self._parse_int(attributes.get(k)))
                        else:
                            setattr(new_product, k, attributes.get(k))
                    
                    db.add(new_product)
                    await db.flush()  # Get ID for caching
                    
                    # Update cache
                    existing_products_cache[sku] = new_product.id
                    
                    stats["created"] += 1
                    products_to_embed_ids.append(new_product.id)
                
                current_batch.append(sku)
                rows_processed += 1
                
                # Commit batch
                if len(current_batch) >= BATCH_SIZE:
                    await db.commit()
                    
                    # Update progress
                    progress = int((rows_processed / total_rows) * 100)
                    upload_record.rows_processed = rows_processed
                    upload_record.progress_percentage = progress
                    await db.commit()
                    
                    logger.info(f"Processed batch: {rows_processed}/{total_rows} ({progress}%)")
                    current_batch = []
                    
            except Exception as row_error:
                error_msg = f"Row {row_num} (SKU: {row.get('sku', 'unknown')}): {str(row_error)}"
                logger.error(error_msg)
                stats["errors"] += 1
                error_details.append({
                    "row": row_num,
                    "sku": row.get("sku"),
                    "error": str(row_error)
                })
                
                # Continue processing other rows
                continue
        
        # Commit final batch
        if current_batch:
            await db.commit()
            upload_record.rows_processed = rows_processed
            upload_record.progress_percentage = 100
            await db.commit()
            logger.info(f"Final batch committed: {rows_processed}/{total_rows}")
        
        # Schedule background embedding generation in chunks
        if background_tasks and products_to_embed_ids:
            background_tasks.add_task(
                self._generate_product_embeddings_background_chunked,
                products_to_embed_ids,
                upload_record.id,
            )
        
        # Update final status
        upload_record.status = ProductUploadStatus.COMPLETED
        upload_record.imported_products = stats["created"] + stats["updated"]
        upload_record.error_log = error_details if error_details else None
        upload_record.completed_at = datetime.utcnow()
        await db.commit()
        
        logger.info(f"Import completed: {stats}")
        
        return {
            "message": "Product import completed. Embeddings will be generated in background.",
            "stats": stats,
            "upload_id": upload_record.id,
            "status": ProductUploadStatus.COMPLETED,
        }
        
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
            
        upload_record.status = ProductUploadStatus.FAILED
        upload_record.error_message = str(e)
        upload_record.error_log = error_details if error_details else None
        await db.commit()
        
        logger.error(f"Import failed: {e}")
        raise
