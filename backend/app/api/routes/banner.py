from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.models.banner import Banner
from app.schemas.banner import BannerCreateUpdate, BannerRead, BannerUploadResponse

router = APIRouter()

ALLOWED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
}


def _resolve_uploads_dir() -> Path:
    return Path(settings.UPLOAD_DIR).resolve()


def _absolute_image_url(request: Request, image_url: str) -> str:
    if not image_url:
        return image_url
    lower = image_url.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return image_url
    if image_url.startswith("/"):
        base_url = str(request.base_url).rstrip("/")
        return f"{base_url}{image_url}"
    return image_url


def _normalize_image_url(image_url: str) -> str:
    if not image_url:
        return image_url
    if image_url.startswith("/uploads/"):
        return image_url
    if "://" in image_url:
        parsed = urlparse(image_url)
        if parsed.path.startswith("/uploads/"):
            return parsed.path
    return image_url


def _banner_response(request: Request, banner: Banner) -> BannerRead:
    data = {
        "id": banner.id,
        "image_url": _absolute_image_url(request, banner.image_url),
        "link_url": banner.link_url,
        "alt_text": banner.alt_text,
        "is_active": banner.is_active,
        "sort_order": banner.sort_order,
        "created_at": banner.created_at,
        "updated_at": banner.updated_at,
    }
    return BannerRead(**data)


@router.get("/", response_model=List[BannerRead])
async def list_banners(
    request: Request,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
) -> List[BannerRead]:
    query = select(Banner).order_by(Banner.sort_order.asc(), desc(Banner.created_at))
    if not include_inactive:
        query = query.where(Banner.is_active.is_(True))

    result = await db.execute(query)
    banners = result.scalars().all()
    return [_banner_response(request, banner) for banner in banners]


@router.post("/upload", response_model=BannerUploadResponse)
async def upload_banner_image(
    file: UploadFile = File(...),
) -> BannerUploadResponse:
    if not file.content_type or file.content_type.lower() not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid image type")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        raise HTTPException(status_code=400, detail="Unsupported file extension")

    uploads_root = _resolve_uploads_dir()
    banner_dir = uploads_root / "banners"
    banner_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{suffix}"
    dest = banner_dir / filename

    contents = await file.read()
    dest.write_bytes(contents)

    image_url = f"/uploads/banners/{filename}"
    return BannerUploadResponse(image_url=image_url)


@router.post("/", response_model=BannerRead)
async def upsert_banner(
    request: Request,
    banner_in: BannerCreateUpdate,
    db: AsyncSession = Depends(get_db),
) -> BannerRead:
    banner: Optional[Banner] = None
    if banner_in.id:
        banner = await db.get(Banner, banner_in.id)
        if not banner:
            raise HTTPException(status_code=404, detail="Banner not found")

    if banner is None:
        banner = Banner()
        db.add(banner)

    update_data = banner_in.model_dump(exclude_unset=True, exclude={"id"})
    if "image_url" in update_data and update_data["image_url"]:
        update_data["image_url"] = _normalize_image_url(update_data["image_url"])
    for field, value in update_data.items():
        setattr(banner, field, value)

    await db.commit()
    await db.refresh(banner)
    return _banner_response(request, banner)


@router.delete("/{banner_id}", status_code=204)
async def delete_banner(
    banner_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    banner = await db.get(Banner, banner_id)
    if not banner:
        raise HTTPException(status_code=404, detail="Banner not found")

    image_url = banner.image_url or ""
    if image_url.startswith("/uploads/"):
        rel_path = image_url[len("/uploads/") :]
        file_path = _resolve_uploads_dir() / rel_path
        if file_path.exists() and file_path.is_file():
            try:
                file_path.unlink()
            except OSError:
                pass

    await db.delete(banner)
    await db.commit()
