from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict

from app.dependencies import get_db
from app.services.data_import_service import data_import_service

router = APIRouter()

@router.get("/template/{type}")
async def download_template(type: str):
    """
    Download CSV template for data import.
    type: 'products' or 'knowledge'
    """
    if type == "products":
        content = data_import_service.get_product_template()
        filename = "product_import_template.csv"
    elif type == "knowledge":
        content = data_import_service.get_knowledge_template()
        filename = "knowledge_import_template.csv"
    else:
        raise HTTPException(status_code=400, detail="Invalid template type. Use 'products' or 'knowledge'.")
        
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.post("/products")
async def import_products(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """Import products from CSV."""
    if not file.filename.endswith(".csv"):
         raise HTTPException(status_code=400, detail="Only .csv files are allowed")
         
    stats = await data_import_service.import_products(db, file)
    return {"message": "Product import completed", "stats": stats}

@router.post("/knowledge")
async def import_knowledge(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """Import knowledge articles from CSV."""
    if not file.filename.endswith(".csv"):
         raise HTTPException(status_code=400, detail="Only .csv files are allowed")
         
    stats = await data_import_service.import_knowledge(db, file)
    return {"message": "Knowledge import completed", "stats": stats}
