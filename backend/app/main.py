from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.routes import health, chat, data_import, tasks, documents


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# Mount static assets (chat widget script, etc.)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# CORS configuration
allowed_origins = ["http://localhost:5173", "http://localhost:8080", "http://localhost:3000"]
if settings.ALLOWED_ORIGINS and settings.ALLOWED_ORIGINS != "*":
    allowed_origins = [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",")] + allowed_origins
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

# Include routers
app.include_router(health, tags=["Health"])
app.include_router(chat, prefix=f"{settings.API_V1_STR}/chat", tags=["Chat"])
app.include_router(data_import, prefix=f"{settings.API_V1_STR}/import", tags=["Import"])
app.include_router(tasks, prefix=f"{settings.API_V1_STR}/tasks", tags=["Tasks"])
app.include_router(documents, prefix=f"{settings.API_V1_STR}/documents", tags=["Documents"])


@app.on_event("startup")
async def startup_event():
    """Startup event handler."""
    print(f"{settings.PROJECT_NAME} is starting up...")
    print("API docs available at: http://localhost:8000/docs")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler."""
    print(f"{settings.PROJECT_NAME} is shutting down...")
