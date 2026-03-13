import asyncio
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.dependencies import get_db
from app.models.product_attribute import FacetValueAlias

router = APIRouter()

@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "GenAI SaaS Backend"}

@router.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)):
    """Database connectivity check."""
    timeout_seconds = float(getattr(settings, "ALIASES_REFRESH_TIMEOUT_SECONDS", 5.0))
    started = time.perf_counter()
    try:
        await asyncio.wait_for(db.execute(text("select 1")), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Database health check timed out") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database health check failed: {exc}") from exc
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {"status": "ok", "latency_ms": round(latency_ms, 2)}

@router.get("/health/db/aliases")
async def health_aliases(db: AsyncSession = Depends(get_db)):
    """Alias table count and latency check."""
    timeout_seconds = float(getattr(settings, "ALIASES_REFRESH_TIMEOUT_SECONDS", 5.0))
    started = time.perf_counter()
    try:
        stmt = select(func.count()).select_from(FacetValueAlias)
        result = await asyncio.wait_for(db.execute(stmt), timeout=timeout_seconds)
        count = int(result.scalar_one() or 0)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Alias count query timed out") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Alias count query failed: {exc}") from exc
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {"status": "ok", "latency_ms": round(latency_ms, 2), "aliases_count": count}

@router.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Welcome to GenAI SaaS API"}
