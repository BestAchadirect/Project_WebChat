from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import auth, tenants, documents, chat, health

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(tenants.router, prefix=f"{settings.API_V1_STR}/tenants", tags=["tenants"])
app.include_router(documents.router, prefix=f"{settings.API_V1_STR}/documents", tags=["documents"])
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat", tags=["chat"])

@app.on_event("startup")
async def startup_event():
    """Startup event handler."""
    print(f"🚀 {settings.PROJECT_NAME} is starting up...")
    print(f"📚 API docs available at: http://localhost:8000/docs")

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler."""
    print(f"👋 {settings.PROJECT_NAME} is shutting down...")

