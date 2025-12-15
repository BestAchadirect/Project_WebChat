from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db.session import engine
from app.db.base import Base
from sqlalchemy import text
import app.models # Ensure models are registered
from app.api.routes.health import router as health_router
from app.api.routes.chat import router as chat_router
from app.api.routes.data_import import router as data_import_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.documents import router as documents_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables
    async with engine.begin() as conn:
        # Enable vector extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Create tables
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown

from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("backend.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="GenAI SaaS API", lifespan=lifespan)

# Set all CORS enabled origins
allowed_origins = ["http://localhost:5173", "http://localhost:8080", "http://localhost:3000"]
if settings.ALLOWED_ORIGINS and settings.ALLOWED_ORIGINS != "*":
    allowed_origins = [str(origin).strip() for origin in settings.ALLOWED_ORIGINS.split(",")] + allowed_origins
elif settings.ALLOWED_ORIGINS == "*":
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include routers with proper prefixes
app.include_router(health_router, tags=["Health"])
app.include_router(chat_router, prefix=f"{settings.API_V1_STR}/chat", tags=["Chat"])
app.include_router(data_import_router, prefix=f"{settings.API_V1_STR}/import", tags=["Import"])
app.include_router(tasks_router, prefix=f"{settings.API_V1_STR}/tasks", tags=["Tasks"])
app.include_router(documents_router, prefix=f"{settings.API_V1_STR}/documents", tags=["Documents"])

@app.get("/health")
async def health_check():
    return {"status": "ok"}
