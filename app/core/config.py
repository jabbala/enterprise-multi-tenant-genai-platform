from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    """Production settings for Enterprise Multi-Tenant GenAI Platform"""
    
    # Application
    app_name: str = "Enterprise Multi-Tenant GenAI Platform"
    debug: bool = False
    environment: str = os.getenv("ENVIRONMENT", "development")
    
    # Security
    jwt_secret: str = os.getenv("JWT_SECRET", "super-secret-key-change-in-prod")
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    
    # LLM Provider
    llm_provider_url: str = os.getenv("LLM_PROVIDER_URL", "http://localhost:8001")
    llm_api_key: Optional[str] = os.getenv("LLM_API_KEY")
    llm_model: str = "gpt-4-turbo"
    llm_timeout: int = 30
    
    # Redis Configuration
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = 0
    redis_ttl_seconds: int = 3600  # 1 hour cache
    redis_max_connections: int = 50
    
    # OpenSearch Configuration
    opensearch_host: str = os.getenv("OPENSEARCH_HOST", "localhost")
    opensearch_port: int = int(os.getenv("OPENSEARCH_PORT", "9200"))
    opensearch_username: Optional[str] = os.getenv("OPENSEARCH_USERNAME")
    opensearch_password: Optional[str] = os.getenv("OPENSEARCH_PASSWORD")
    opensearch_index_prefix: str = "genai"
    opensearch_number_of_shards: int = 3
    opensearch_number_of_replicas: int = 1
    
    # FAISS Vector Store
    faiss_index_path: str = os.getenv("FAISS_INDEX_PATH", "./data/faiss_indexes")
    faiss_dimension: int = 1536  # OpenAI embedding dimension
    
    # Retrieval
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.3
    bm25_weight: float = 0.4
    vector_weight: float = 0.6
    
    # Cost Tracking
    cost_tracking_enabled: bool = True
    llm_cost_per_1k_tokens: float = 0.03  # Adjust based on LLM provider
    retrieval_cost_per_query: float = 0.001
    
    # Observability
    prometheus_enabled: bool = True
    prometheus_port: int = 9090
    opentelemetry_enabled: bool = True
    jaeger_host: str = os.getenv("JAEGER_HOST", "localhost")
    jaeger_port: int = 6831
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_format: str = "json"
    structured_logging_enabled: bool = True
    
    # Circuit Breaker
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: int = 60
    circuit_breaker_expected_exception: Exception = Exception
    
    # Retry Logic
    max_retries: int = 3
    initial_retry_delay: float = 0.5
    max_retry_delay: float = 10.0
    
    # Load Testing & Scaling
    target_latency_p95_ms: int = 2500
    target_uptime_percentage: float = 99.9
    target_precision_at_5: float = 0.9
    
    # Audit & Compliance
    audit_logging_enabled: bool = True
    pii_redaction_enabled: bool = True
    cross_tenant_leakage_check_enabled: bool = True
    
    # Database
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("DB_NAME", "genai_platform")
    db_user: str = os.getenv("DB_USER", "postgres")
    db_password: str = os.getenv("DB_PASSWORD", "password")
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
