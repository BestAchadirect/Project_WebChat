from pathlib import Path
from typing import Optional

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
    PRODUCT_SEARCH_TOPK: int = 10
    PRODUCT_SEARCH_DISTANCE_THRESHOLD: float = 0.35
    PRODUCT_EMBEDDING_MODEL: str = "text-embedding-3-small"
    PRODUCT_DISTANCE_STRICT: float = 0.35
    PRODUCT_DISTANCE_LOOSE: float = 0.45
    PRICE_DISPLAY_CURRENCY: str = "USD"
    THB_TO_USD_RATE: float = 1.0
    BASE_CURRENCY: str = "USD"
    CURRENCY_RATES_JSON: str = "{}"

    # Routing UX (smalltalk / low-signal)
    SMALLTALK_ENABLED: bool = True
    SMALLTALK_MODE: str = "static"  # static | llm
    SMALLTALK_MODEL: str = "gpt-4o-mini"
    GENERAL_CHAT_MODEL: str = "gpt-4o-mini"
    GENERAL_CHAT_MAX_TOKENS: int = 250
    CONTEXTUAL_REPLY_ENABLED: bool = True
    CONTEXTUAL_REPLY_MODEL: str = "gpt-4o-mini"
    CONTEXTUAL_REPLY_MAX_TOKENS: int = 120
    CONTEXTUAL_REPLY_TEMPERATURE: float = 0.3
    CHAT_LANGUAGE_MODE: str = "auto"  # auto | locale | fixed
    DEFAULT_LOCALE: str = "en-US"
    FIXED_REPLY_LANGUAGE: str = "en-US"
    LANGUAGE_DETECT_MODEL: str = "gpt-4o-mini"
    LANGUAGE_DETECT_MAX_TOKENS: int = 40
    PRODUCT_WEAK_DISTANCE: float = 0.55
    KNOWLEDGE_WEAK_DISTANCE: float = 0.60

    # Answer polishing (rewrite-only, optional)
    ANSWER_POLISHER_ENABLED: bool = False
    ANSWER_POLISHER_MODEL: str = "gpt-4o-mini"
    ANSWER_POLISHER_MAX_TOKENS: int = 200

    # RAG pipeline (routing should not depend on distance thresholds)
    RAG_RETRIEVE_TOPK_KNOWLEDGE: int = 30
    RAG_RETRIEVE_TOPK_PRODUCT: int = 20
    RAG_RERANK_TOPN: int = 5
    RAG_COHERE_RERANK_MODEL: str = "rerank-english-v3.0"
    COHERE_API_KEY: Optional[str] = None
    RAG_RERANK_MIN_SCORE: float = 0.05
    RAG_RERANK_MIN_SCORE_COUNT: int = 2
    RAG_MAX_DOC_CHARS_FOR_RERANK: int = 700
    RERANK_MIN_CANDIDATES: int = 12
    RERANK_GAP_THRESHOLD: float = 0.06
    RERANK_WEAK_D1_THRESHOLD: float = 0.45
    RAG_MAX_CHUNK_CHARS_FOR_CONTEXT: int = 1200
    RAG_VERIFY_MODEL: str = "gpt-4o-mini"
    RAG_DECOMPOSE_MODEL: str = "gpt-4o-mini"
    RAG_DECOMPOSE_MAX_SUBQUESTIONS: int = 8
    RAG_DECOMPOSE_WEAK_DISTANCE: float = 0.55
    RAG_DECOMPOSE_GAP_THRESHOLD: float = 0.06
    RAG_MAX_SUB_QUESTIONS: int = 4
    RAG_PER_QUERY_KEEP: int = 1
    RAG_VERIFY_MAX_KNOWLEDGE_CHUNKS: int = 12

    # Retrieval planner (LLM, almost-always)
    PLANNER_ENABLED: bool = True
    PLANNER_MODEL: str = "gpt-4o-mini"
    PLANNER_MAX_TOKENS: int = 200
    PLANNER_MIN_CONFIDENCE: float = 0.6

    # Logging
    LOG_DIR: str = "logs"
    DEBUG_LOG_FILE: str = "debug.log"

    # Supabase Storage
    SUPABASE_URL: str
    SUPABASE_KEY: str  # Anon key
    SUPABASE_SERVICE_KEY: str  # Service role key for admin operations
    SUPABASE_BUCKET: str = "documents"
    
    # File Storage
    UPLOAD_DIR: str = "uploads"  # Directory for storing uploaded files
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB max file size
    ALLOWED_EXTENSIONS: str = "pdf,doc,docx,txt,csv"

    # Load backend-local .env regardless of current working directory.
    # Ignore unrelated env vars (e.g. VITE_*) so frontend settings don't crash the backend.
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        case_sensitive=True,
        extra="ignore",
    )

settings = Settings()
