from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api.routes import documents, health, chat, data_import

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(documents.router, prefix=f"{settings.API_V1_STR}/documents", tags=["Documents"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(data_import.router, prefix=f"{settings.API_V1_STR}/import", tags=["Data Import"])

@app.on_event("startup")
async def startup_event():
    """Startup event handler."""
    print(f"🚀 {settings.PROJECT_NAME} is starting up...")
    print(f"📚 API docs available at: http://localhost:8000/docs")

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler."""
    print(f"👋 {settings.PROJECT_NAME} is shutting down...")
