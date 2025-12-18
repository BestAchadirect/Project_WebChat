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
