from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "GenAI SaaS Backend"
    API_V1_STR: str = "/api/v1"
    
    DATABASE_URL: str
    DB_SQL_ECHO: bool = False
    
    # Security
    JWT_SECRET: str = Field(validation_alias=AliasChoices("JWT_SECRET", "SECRET_KEY"))
    JWT_ALGORITHM: str = Field(default="HS256", validation_alias=AliasChoices("JWT_ALGORITHM", "ALGORITHM"))
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # CORS
    ALLOWED_ORIGINS: str = "*"
    ENVIRONMENT: str = "development"
    
    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-5.4"
    OPENAI_TIMEOUT_SECONDS: float = 12.0
    OPENAI_MAX_RETRIES: int = 1
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_CACHE_MAX_ITEMS: int = 512
    EMBEDDING_CACHE_TTL_SECONDS: int = 3600
    
    # Vector DB
    VECTOR_DIMENSIONS: int = 1536  # for text-embedding-3-small
    KNOWLEDGE_DISTANCE_THRESHOLD: float = 0.40
    PRODUCT_DISTANCE_THRESHOLD: float = 0.35
    PRODUCT_EMBEDDING_MODEL: str = "text-embedding-3-small"
    PRODUCT_EMBEDDING_PAGE_SIZE: int = 1000
    PRODUCT_EMBEDDING_BATCH_SIZE: int = 128
    PRODUCT_EMBEDDING_MAX_CONCURRENCY: int = 4
    PRODUCT_EMBEDDING_MAX_RETRIES: int = 4
    PRODUCT_EMBEDDING_RETRY_BASE_MS: int = 500
    PRODUCT_EMBEDDING_PROGRESS_INTERVAL_SECONDS: int = 5
    CATALOG_EAV_PARTIAL_MATCH_KEYS: str = (
        "category,color,crystal_color,cz_color,design,finish,jewelry_type,"
        "material,opal_color,packing_option,pearl_color,rack,threading"
    )
    PRICE_DISPLAY_CURRENCY: str = "USD"
    THB_TO_USD_RATE: float = 1.0
    BASE_CURRENCY: str = "USD"
    CURRENCY_RATES_JSON: str = "{}"
    NLU_MODEL: str = "gpt-5-mini"
    NLU_MAX_TOKENS: int = 250
    NLU_FAST_PATH_ENABLED: bool = True

    UI_LOCALIZATION_ENABLED: bool = True
    UI_LOCALIZATION_MODEL: str = "gpt-5-mini"
    UI_LOCALIZATION_MAX_TOKENS: int = 220
    UI_LOCALIZATION_TEMPERATURE: float = 0.1
    UI_LOCALIZATION_CACHE_MAX_ITEMS: int = 256
    UI_LOCALIZATION_CACHE_TTL_SECONDS: int = 3600
    CHAT_LANGUAGE_MODE: str = "auto"  # auto | locale | fixed
    DEFAULT_LOCALE: str = "en-US"
    FIXED_REPLY_LANGUAGE: str = "en-US"
    PRODUCT_WEAK_DISTANCE: float = 0.55
    KNOWLEDGE_WEAK_DISTANCE: float = 0.60

    # Agentic function calling (phase 1 read-only)
    AGENTIC_FUNCTION_CALLING_ENABLED: bool = False
    AGENTIC_ALLOWED_CHANNELS: str = "widget,qa_console"
    AGENTIC_MODEL: str = ""
    AGENTIC_MAX_TOOL_ROUNDS: int = 4
    AGENTIC_MAX_TOOL_CALLS: int = 6
    AGENTIC_TOOL_TIMEOUT_MS: int = 3500
    AGENTIC_MAX_TOOL_RESULT_ITEMS: int = 10
    AGENTIC_ENABLE_FALLBACK: bool = True

    # Conversation lifecycle
    CONVERSATION_IDLE_TIMEOUT_MINUTES: int = 30
    CONVERSATION_HARD_CAP_HOURS: int = 24

    # Answer polishing (rewrite-only, optional)
    ANSWER_POLISHER_ENABLED: bool = False
    ANSWER_POLISHER_MODEL: str = "gpt-5-mini"
    ANSWER_POLISHER_MAX_TOKENS: int = 200

    # RAG pipeline (routing should not depend on distance thresholds)
    RAG_RETRIEVE_TOPK_KNOWLEDGE: int = 30
    RAG_MAX_CHUNK_CHARS_FOR_CONTEXT: int = 1200
    RAG_ANSWER_MODEL: str = "gpt-5-mini"
    RAG_DECOMPOSE_MODEL: str = "gpt-5-mini"
    RAG_DECOMPOSE_MAX_SUBQUESTIONS: int = 8
    RAG_DECOMPOSE_WEAK_DISTANCE: float = 0.55
    RAG_DECOMPOSE_GAP_THRESHOLD: float = 0.06
    RAG_PER_QUERY_KEEP: int = 1


    # Semantic cache (pgvector)
    SEMANTIC_CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_THRESHOLD: float = 0.96
    SEMANTIC_CACHE_TTL_DAYS: int = 7
    CHAT_FIELD_AWARE_DETAIL_ENABLED: bool = True
    CHAT_DETAIL_MAX_MATCHES: int = 3
    CHAT_DETAIL_MIN_CONFIDENCE: float = 0.55
    CHAT_DETAIL_ENABLE_SEMANTIC_CACHE: bool = False
    CHAT_FAIL_FAST_ON_EMBEDDING_ERROR: bool = True
    CHAT_SEMANTIC_FIRST_ENABLED: bool = True
    CHAT_SEMANTIC_MIN_ACCEPTANCE_SCORE: float = 0.35
    CHAT_SEMANTIC_SOFT_FILTER_RERANK_ENABLED: bool = True
    CHAT_ATTRIBUTE_INTERPRETATION_ENABLED: bool = True
    CHAT_ATTRIBUTE_INTERPRETATION_MODEL: str = ""
    CHAT_ATTRIBUTE_INTERPRETATION_MAX_TOKENS: int = 220
    CHAT_ATTRIBUTE_INTERPRETATION_MIN_CONFIDENCE: float = 0.55
    CHAT_SEMANTIC_HINTS_ENABLED: bool = True
    CHAT_CONTEXTUAL_COMPONENT_COPY_ENABLED: bool = False
    CHAT_CONTEXTUAL_COMPONENT_COPY_MODEL: str = ""
    CHAT_CONTEXTUAL_COMPONENT_COPY_MAX_TOKENS: int = 100
    CHAT_CONTEXTUAL_COMPONENT_COPY_TEMPERATURE: float = 0.2
    CHAT_PROJECTION_DUAL_WRITE_ENABLED: bool = True
    CHAT_STRUCTURED_CANDIDATE_CAP: int = 300
    CHAT_STRUCTURED_QUERY_CACHE_ENABLED: bool = True
    CHAT_STRUCTURED_QUERY_CACHE_MAX_ITEMS: int = 2000
    CHAT_STRUCTURED_QUERY_CACHE_TTL_SECONDS: int = 600
    CHAT_NLU_HEURISTIC_THRESHOLD: float = 0.85
    CHAT_EXTERNAL_CALL_BUDGET: int = 3
    CHAT_EXTERNAL_CALL_FAIL_FAST_SECONDS: float = 3.5
    CHAT_EXTERNAL_CALL_RETRY_MAX: int = 1
    CHAT_VECTOR_TOP_K: int = 12
    CHAT_CROSS_SELL_MODE: str = "off"  # off | inline
    CHAT_MAX_HISTORY_TOKENS: int = 1200
    CHAT_LLM_RENDER_ONLY_GUARD: bool = True
    CHAT_HARD_MAX_LLM_CALLS_PER_REQUEST: int = 0
    CHAT_HARD_MAX_EMBEDDINGS_PER_REQUEST: int = 5
    CHAT_EMBEDDING_RETRY_MAX: int = 1
    CHAT_STRICT_RETRIEVAL_SEPARATION_ENABLED: bool = False
    CHAT_CATALOG_VERSION: str = "v1"
    CHAT_PROMPT_VERSION: str = "v1"
    CHAT_LLM_ROUTING_ENABLED: bool = True
    CHAT_LLM_ROUTING_MODEL: str = ""
    CHAT_LLM_ROUTING_MAX_TOKENS: int = 180
    CHAT_LLM_ROUTING_TEMPERATURE: float = 0.0
    CHAT_LLM_ROUTING_TIMEOUT_MS: int = 5000
    CHAT_LLM_ROUTING_TIMEOUT_RETRY_ENABLED: bool = True
    CHAT_LLM_ROUTING_TIMEOUT_RETRY_MS: int = 2000
    CHAT_LLM_ROUTING_MIN_CONFIDENCE: float = 0.7
    CHAT_AGENTIC_MIN_CONFIDENCE: float = 0.8
    CHAT_MIXED_INTENT_ENABLED: bool = True
    CHAT_CLARIFY_GUARDRAILS_ENABLED: bool = True
    CHAT_KNOWLEDGE_MIN_RELEVANCE: float = 0.40
    CHAT_KNOWLEDGE_HIGH_RISK_GUARD_ENABLED: bool = True
    CHAT_KNOWLEDGE_ANSWER_MAX_CHARS: int = 420
    CHAT_CONVERSION_FOLLOW_UPS_ENABLED: bool = True
    CHAT_PRODUCT_CLICK_TRACKING_ENABLED: bool = True
    CHAT_CACHE_LOG_INTERVAL_SECONDS: int = 60
    CHAT_PUBLIC_DEBUG_ENABLED: bool = False
    CHAT_COMPONENT_BUCKETS_ENABLED: bool = False
    CHAT_COMPONENT_BUCKETS_SHADOW_MODE: bool = False
    CHAT_COMPONENT_BUCKETS_REQUIRE_COMPONENTS: bool = False
    CHAT_COMPONENT_BUCKETS_ENABLED_CHANNELS: str = "widget"
    CHAT_CONVERSATION_STATE_ENABLED: bool = True
    CHAT_TONE_HUMANIZER_ENABLED: bool = True
    CHAT_TONE_ANTI_REPEAT_WINDOW: int = 4
    CHAT_TONE_MAX_SENTENCES: int = 2
    CHAT_TONE_MAX_CHARS: int = 220
    CHAT_TONE_ENABLED_CHANNELS: str = "widget"
    FACETS_V2_DUAL_WRITE_ENABLED: bool = True
    FACETS_V2_READ_ENABLED: bool = True
    ALIASES_REFRESH_TIMEOUT_SECONDS: float = 5.0
    PARSER_RULES_REFRESH_TIMEOUT_SECONDS: float = 5.0

    # Klevu product sync
    KLEVU_API_ENDPOINT: str = "https://eucs30v2.ksearchnet.com/cs/v2/search"
    KLEVU_JS_API_KEY: str = ""
    KLEVU_SYNC_PAGE_SIZE_MAX: int = 100
    KLEVU_SYNC_REQUESTS_PER_MINUTE: int = 180
    KLEVU_SYNC_MAX_RETRIES: int = 5
    KLEVU_SYNC_BACKOFF_BASE_SECONDS: float = 0.5
    KLEVU_SYNC_PAYLOAD_MAX_BYTES: int = 2 * 1024 * 1024
    KLEVU_SYNC_TIMEOUT_SECONDS: float = 30.0
    KLEVU_SYNC_BULK_EAV_ENABLED: bool = True
    KLEVU_SYNC_DISABLE_GROUPING: bool = True
    KLEVU_SYNC_ROW_SAVEPOINT_ENABLED: bool = True
    KLEVU_SYNC_COMMIT_EVERY_PAGES: int = 1
    KLEVU_SYNC_CANCEL_CHECK_EVERY_PAGES: int = 1
    KLEVU_SYNC_DEFER_SEARCH_TEXT: bool = False
    KLEVU_SYNC_STALE_RUNNING_MINUTES: int = 10
    KLEVU_SYNC_USE_EXTERNAL_WORKER: bool = False
    KLEVU_SYNC_WORKER_POLL_SECONDS: float = 5.0

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
