"""
Optimized background embedding generation with chunking and progress tracking.

This method should be added to DataImportService class.
"""

async def _generate_product_embeddings_background_chunked(
    self, 
    product_ids: List[UUID],
    upload_id: UUID
) -> None:
    """
    Background task to generate embeddings for products in chunks.
    Processes 100 products at a time with progress tracking.
    """
    from app.db.session import AsyncSessionLocal
    
    CHUNK_SIZE = 100  # Process 100 embeddings at a time
    total_products = len(product_ids)
    
    async with AsyncSessionLocal() as db:
        try:
            # Create task for tracking
            task = await task_service.create_task(
                db,
                TaskType.EMBEDDING_GENERATION,
                f"Generating embeddings for {total_products} products",
                {
                    "product_ids_count": total_products,
                    "upload_id": str(upload_id)
                }
            )
            
            await task_service.update_task_status(db, task.id, TaskStatus.RUNNING)
            
            processed = 0
            failed = 0
            
            # Process in chunks
            for chunk_start in range(0, total_products, CHUNK_SIZE):
                chunk_end = min(chunk_start + CHUNK_SIZE, total_products)
                chunk_ids = product_ids[chunk_start:chunk_end]
                
                # Load products for this chunk
                stmt = select(Product).where(Product.id.in_(chunk_ids))
                result = await db.execute(stmt)
                products = result.scalars().all()
                
                # Generate embeddings for each product in chunk
                for product in products:
                    try:
                        await self._update_product_embedding(db, product)
                        processed += 1
                    except Exception as e:
                        logger.error(f"Failed to embed product {product.sku}: {e}")
                        failed += 1
                
                # Update progress
                progress = int((chunk_end / total_products) * 100)
                await task_service.update_task_status(
                    db, 
                    task.id, 
                    TaskStatus.RUNNING, 
                    progress=progress
                )
                
                logger.info(f"Embedding progress: {chunk_end}/{total_products} ({progress}%)")
            
            # Update final status
            await task_service.update_task_status(
                db, 
                task.id, 
                TaskStatus.COMPLETED, 
                progress=100
            )
            
            logger.info(f"Embedding generation completed: {processed} succeeded, {failed} failed")
            
        except Exception as e:
            logger.error(f"Error in background embedding generation: {e}")
            try:
                await task_service.update_task_status(
                    db,
                    task.id,
                    TaskStatus.FAILED
                )
            except:
                pass
