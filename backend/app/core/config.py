from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "GenAI SaaS Backend"
    API_V1_STR: str = "/api/v1"
    
    DATABASE_URL: str
    
    # Security
    JWT_SECRET: str = Field(validation_alias=AliasChoices("JWT_SECRET", "SECRET_KEY"))
    JWT_ALGORITHM: str = Field(default="HS256", validation_alias=AliasChoices("JWT_ALGORITHM", "ALGORITHM"))
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # CORS
    ALLOWED_ORIGINS: str = "*"
    ENVIRONMENT: str = "development"
    
    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4-turbo-preview"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    
    # Vector DB
    VECTOR_DIMENSIONS: int = 1536  # for text-embedding-3-small
    KNOWLEDGE_DISTANCE_THRESHOLD: float = 0.40
    PRODUCT_DISTANCE_THRESHOLD: float = 0.35

    # RAG pipeline (routing should not depend on distance thresholds)
    RAG_RETRIEVE_TOPK_KNOWLEDGE: int = 30
    RAG_RETRIEVE_TOPK_PRODUCT: int = 20
    RAG_RERANK_TOPN: int = 5
    RAG_COHERE_RERANK_MODEL: str = "rerank-english-v3.0"
    COHERE_API_KEY: Optional[str] = None
    RAG_RERANK_MIN_SCORE: float = 0.05
    RAG_RERANK_MIN_SCORE_COUNT: int = 2
    RAG_MAX_DOC_CHARS_FOR_RERANK: int = 700
    RAG_MAX_CHUNK_CHARS_FOR_CONTEXT: int = 1200
    RAG_VERIFY_MODEL: str = "gpt-4o-mini"
    RAG_DECOMPOSE_MODEL: str = "gpt-4o-mini"
    RAG_DECOMPOSE_MAX_SUBQUESTIONS: int = 8

    # Supabase Storage
    SUPABASE_URL: str
    SUPABASE_KEY: str  # Anon key
    SUPABASE_SERVICE_KEY: str  # Service role key for admin operations
    SUPABASE_BUCKET: str = "documents"
    
    # File Storage
    UPLOAD_DIR: str = "uploads"  # Directory for storing uploaded files
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB max file size
    ALLOWED_EXTENSIONS: str = "pdf,doc,docx,txt,csv"

    class Config:
        # Load backend-local .env regardless of current working directory
        env_file = str(Path(__file__).resolve().parents[2] / ".env")
        case_sensitive = True

settings = Settings()
