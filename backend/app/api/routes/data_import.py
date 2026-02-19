from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Response, BackgroundTasks, Header, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.dependencies import get_db
from app.services.data_import_service import data_import_service
from app.schemas import (
    KnowledgeUploadListResponse,
    KnowledgeImportResponse,
    ProductUploadListResponse,
)
from app.models.knowledge import KnowledgeUploadStatus
from app.utils.pagination import normalize_pagination

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
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    uploaded_by: str | None = Header(default=None, alias="X-Uploaded-By"),
    db: AsyncSession = Depends(get_db)
):
    """Import products from CSV."""
    if not file.filename.endswith(".csv"):
         raise HTTPException(status_code=400, detail="Only .csv files are allowed")
         
    result = await data_import_service.import_products(
        db,
        file,
        background_tasks,
        uploaded_by=uploaded_by,
    )
    return result

@router.get("/products/uploads", response_model=ProductUploadListResponse)
async def list_product_uploads(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=9999),
    db: AsyncSession = Depends(get_db),
):
    """List historical product uploads."""
    if "limit" in request.query_params or "offset" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="limit/offset pagination is no longer supported. Use page and pageSize.",
        )

    uploads, total = await data_import_service.list_product_uploads(db, page=page, page_size=page_size)
    safe_page, total_pages, _ = normalize_pagination(total_items=total, page=page, page_size=page_size)
    if safe_page != page:
        uploads, _ = await data_import_service.list_product_uploads(db, page=safe_page, page_size=page_size)
    return ProductUploadListResponse(
        items=uploads,
        totalItems=total,
        page=safe_page,
        pageSize=page_size,
        totalPages=total_pages,
    )

@router.get("/products/uploads/{upload_id}/download")
async def download_product_upload(upload_id: UUID, db: AsyncSession = Depends(get_db)):
    """Download the original product CSV upload."""
    file_path = await data_import_service.get_product_upload_file_path(db, upload_id)
    filename = file_path.name
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="text/csv"
    )

@router.delete("/products/uploads/{upload_id}", status_code=204)
async def delete_product_upload(upload_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a product upload and its stored file."""
    await data_import_service.delete_product_upload(db, upload_id)

@router.post("/knowledge")
async def import_knowledge(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    uploaded_by: str | None = Header(default=None, alias="X-Uploaded-By"),
    db: AsyncSession = Depends(get_db)
) -> KnowledgeImportResponse:
    """
    Import knowledge articles from CSV files.
    
    Supported formats:
    - CSV: Must have columns 'title', 'content', and optionally 'category', 'url'
    
    Files are processed in the background with embeddings generated asynchronously.
    """
    filename = file.filename.lower()
    
    # Validate file type
    allowed_extensions = ['.csv']
    if not any(filename.endswith(ext) for ext in allowed_extensions):
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    result = await data_import_service.import_knowledge(db, file, background_tasks, uploaded_by=uploaded_by)
    return KnowledgeImportResponse(
        message="Knowledge import initiated. Articles and embeddings will be generated in background.",
        upload_id=result["upload_id"],
        stats=result["stats"],
        status=result["status"]
    )

@router.get("/knowledge/uploads", response_model=KnowledgeUploadListResponse)
async def list_knowledge_uploads(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=9999),
    db: AsyncSession = Depends(get_db),
):
    """List knowledge upload sessions with status and counts."""
    if "limit" in request.query_params or "offset" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="limit/offset pagination is no longer supported. Use page and pageSize.",
        )

    uploads, total = await data_import_service.list_knowledge_uploads(db, page=page, page_size=page_size)
    safe_page, total_pages, _ = normalize_pagination(total_items=total, page=page, page_size=page_size)
    if safe_page != page:
        uploads, _ = await data_import_service.list_knowledge_uploads(db, page=safe_page, page_size=page_size)
    return KnowledgeUploadListResponse(
        items=uploads,
        totalItems=total,
        page=safe_page,
        pageSize=page_size,
        totalPages=total_pages,
    )

@router.get("/knowledge/uploads/{upload_id}/download")
async def download_knowledge_upload(upload_id: UUID, db: AsyncSession = Depends(get_db)):
    """Download the original uploaded file for a knowledge import."""
    file_path = await data_import_service.get_upload_file_path(db, upload_id)
    filename = file_path.name
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream"
    )

@router.delete("/knowledge/uploads/{upload_id}", status_code=204)
async def delete_knowledge_upload(upload_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a knowledge upload along with derived articles/embeddings."""
    await data_import_service.delete_knowledge_upload(db, upload_id)
