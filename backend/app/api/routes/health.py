from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "GenAI SaaS Backend"}

@router.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Welcome to GenAI SaaS API"}
