from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    EMBEDDING_CACHE_MAX_ITEMS: int = 512
    EMBEDDING_CACHE_TTL_SECONDS: int = 3600
    
    # Vector DB
    VECTOR_DIMENSIONS: int = 1536  # for text-embedding-3-small
    KNOWLEDGE_DISTANCE_THRESHOLD: float = 0.40
    PRODUCT_DISTANCE_THRESHOLD: float = 0.35
    PRODUCT_EMBEDDING_MODEL: str = "text-embedding-3-small"
    PRICE_DISPLAY_CURRENCY: str = "USD"
    THB_TO_USD_RATE: float = 1.0
    BASE_CURRENCY: str = "USD"
    CURRENCY_RATES_JSON: str = "{}"
    NLU_MODEL: str = "gpt-4o-mini"
    NLU_MAX_TOKENS: int = 250

    UI_LOCALIZATION_ENABLED: bool = True
    UI_LOCALIZATION_MODEL: str = "gpt-4o-mini"
    UI_LOCALIZATION_MAX_TOKENS: int = 220
    UI_LOCALIZATION_TEMPERATURE: float = 0.1
    UI_LOCALIZATION_CACHE_MAX_ITEMS: int = 256
    UI_LOCALIZATION_CACHE_TTL_SECONDS: int = 3600
    CHAT_LANGUAGE_MODE: str = "auto"  # auto | locale | fixed
    DEFAULT_LOCALE: str = "en-US"
    FIXED_REPLY_LANGUAGE: str = "en-US"
    PRODUCT_WEAK_DISTANCE: float = 0.55
    KNOWLEDGE_WEAK_DISTANCE: float = 0.60

    # Conversation lifecycle
    CONVERSATION_IDLE_TIMEOUT_MINUTES: int = 30
    CONVERSATION_HARD_CAP_HOURS: int = 24

    # Answer polishing (rewrite-only, optional)
    ANSWER_POLISHER_ENABLED: bool = False
    ANSWER_POLISHER_MODEL: str = "gpt-4o-mini"
    ANSWER_POLISHER_MAX_TOKENS: int = 200

    # RAG pipeline (routing should not depend on distance thresholds)
    RAG_RETRIEVE_TOPK_KNOWLEDGE: int = 30
    RAG_MAX_CHUNK_CHARS_FOR_CONTEXT: int = 1200
    RAG_ANSWER_MODEL: str = "gpt-4o-mini"
    RAG_DECOMPOSE_MODEL: str = "gpt-4o-mini"
    RAG_DECOMPOSE_MAX_SUBQUESTIONS: int = 8
    RAG_DECOMPOSE_WEAK_DISTANCE: float = 0.55
    RAG_DECOMPOSE_GAP_THRESHOLD: float = 0.06
    RAG_PER_QUERY_KEEP: int = 1


    # Semantic cache (pgvector)
    SEMANTIC_CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_THRESHOLD: float = 0.96
    SEMANTIC_CACHE_TTL_DAYS: int = 7

    # Logging
    LOG_DIR: str = "logs"
    DEBUG_LOG_FILE: str = "debug.log"

    # Supabase Storage
    SUPABASE_URL: str
    SUPABASE_KEY: str  # Anon key
    SUPABASE_SERVICE_KEY: str  # Service role key for admin operations
    # File Storage
    UPLOAD_DIR: str = "uploads"  # Directory for storing uploaded files
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB max file size

    # Load backend-local .env regardless of current working directory.
    # Ignore unrelated env vars (e.g. VITE_*) so frontend settings don't crash the backend.
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        case_sensitive=True,
        extra="ignore",
    )

settings = Settings()
