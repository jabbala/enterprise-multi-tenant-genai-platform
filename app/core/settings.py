"""
Application configuration and settings for Enterprise Multi-Tenant GenAI Platform.
Uses environment variables with sensible development defaults.
"""

import os
from typing import Optional, List
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings and configuration."""
    
    # ======================================================================
    # API Configuration
    # ======================================================================
    API_VERSION: str = "v1"
    APP_NAME: str = "Enterprise Multi-Tenant GenAI Platform"
    APP_ENV: str = os.getenv("APP_ENV", "development")
    
    # ======================================================================
    # Server Configuration
    # ======================================================================
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    WORKERS: int = int(os.getenv("WORKERS", "4"))
    
    # ======================================================================
    # Database Configuration
    # ======================================================================
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/genai")
    DATABASE_POOL_SIZE: int = int(os.getenv("DATABASE_POOL_SIZE", "20"))
    DATABASE_POOL_RECYCLE: int = int(os.getenv("DATABASE_POOL_RECYCLE", "3600"))
    
    # ======================================================================
    # Redis Configuration
    # ======================================================================
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_CLUSTER_ENABLED: bool = os.getenv("REDIS_CLUSTER_ENABLED", "false").lower() == "true"
    REDIS_KEY_PREFIX: str = "genai:"
    
    # ======================================================================
    # OpenSearch Configuration
    # ======================================================================
    OPENSEARCH_HOSTS: List[str] = os.getenv("OPENSEARCH_HOSTS", "localhost:9200").split(",")
    OPENSEARCH_USER: str = os.getenv("OPENSEARCH_USER", "admin")
    OPENSEARCH_PASSWORD: str = os.getenv("OPENSEARCH_PASSWORD", "")
    OPENSEARCH_VERIFY_CERTS: bool = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
    OPENSEARCH_CA_CERT_PATH: Optional[str] = os.getenv("OPENSEARCH_CA_CERT_PATH")
    
    # ======================================================================
    # FAISS Vector Store Configuration
    # ======================================================================
    FAISS_INDEX_PATH: str = os.getenv("FAISS_INDEX_PATH", "/tmp/faiss_indices")
    FAISS_DIMENSION: int = 1536  # OpenAI embedding dimension
    FAISS_INDEX_TYPE: str = "IVF64,Flat"  # IVF with flat quantization
    
    # ======================================================================
    # LLM Configuration
    # ======================================================================
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    OPENAI_MODEL_PRIMARY: str = os.getenv("OPENAI_MODEL_PRIMARY", "gpt-4-turbo")
    OPENAI_MODEL_SECONDARY: str = os.getenv("OPENAI_MODEL_SECONDARY", "gpt-4")
    OPENAI_MODEL_FALLBACK: str = os.getenv("OPENAI_MODEL_FALLBACK", "gpt-3.5-turbo")
    LLM_REQUEST_TIMEOUT: int = int(os.getenv("LLM_REQUEST_TIMEOUT", "30"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "2"))
    
    # ======================================================================
    # Embedding Configuration
    # ======================================================================
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIMENSION: int = 1536
    EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "100"))
    
    # ======================================================================
    # Security & Authentication
    # ======================================================================
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-me-in-production-SECRET-KEY-MIN-32-CHARS")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
    JWT_ISSUER: str = "genai-platform"
    
    # CORS
    ALLOWED_ORIGINS: List[str] = ["*"]
    
    # ======================================================================
    # Rate Limiting & Backpressure
    # ======================================================================
    DEFAULT_QPS_LIMIT: int = 5
    DEFAULT_BURST_QPS: int = 10
    DEFAULT_BURST_DURATION_SEC: int = 5
    DEFAULT_DAILY_QUOTA: int = 100000
    
    # Queue configuration
    MAX_QUEUE_DEPTH: int = int(os.getenv("MAX_QUEUE_DEPTH", "100"))
    QUEUE_TIMEOUT_SEC: int = int(os.getenv("QUEUE_TIMEOUT_SEC", "30"))
    MAX_INFLIGHT_PER_POD: int = int(os.getenv("MAX_INFLIGHT_PER_POD", "50"))
    WORKER_POOL_SIZE: int = int(os.getenv("WORKER_POOL_SIZE", "10"))
    QUEUE_CHECK_INTERVAL_MS: int = 100
    
    # ======================================================================
    # Fair Sharing & Tenant Tiers
    # ======================================================================
    FAIR_SHARE_ENTERPRISE: float = 0.50
    FAIR_SHARE_PROFESSIONAL: float = 0.30
    FAIR_SHARE_STARTER: float = 0.15
    FAIR_SHARE_FREE: float = 0.05
    NOISY_NEIGHBOR_THRESHOLD: float = 0.20  # 20% cap
    NOISY_NEIGHBOR_ALERT_THRESHOLD: float = 0.30  # Alert at 30%
    
    # ======================================================================
    # Encryption & Key Management
    # ======================================================================
    ENCRYPTION_ENABLED: bool = os.getenv("ENCRYPTION_ENABLED", "true").lower() == "true"
    ENCRYPTION_ALGORITHM: str = "AES-256-GCM"
    KMS_PROVIDER: str = os.getenv("KMS_PROVIDER", "k8s-secret")  # aws-kms, gcp-kms, k8s-secret
    KMS_KEY_ID: Optional[str] = os.getenv("KMS_KEY_ID")
    AWS_KMS_REGION: Optional[str] = os.getenv("AWS_KMS_REGION", "us-east-1")
    
    # ======================================================================
    # Data Governance
    # ======================================================================
    DEFAULT_RETENTION_DAYS: int = int(os.getenv("DEFAULT_RETENTION_DAYS", "90"))
    DEFAULT_DATA_RESIDENCY: str = os.getenv("DEFAULT_DATA_RESIDENCY", "us")
    PII_REDACTION_ENABLED: bool = os.getenv("PII_REDACTION_ENABLED", "true").lower() == "true"
    
    # ======================================================================
    # Model Evaluation & Governance
    # ======================================================================
    EVALUATION_DATASET_PATH: str = os.getenv("EVALUATION_DATASET_PATH", "/opt/genai/evaluation_datasets")
    MODEL_REGRESSION_THRESHOLD_PCT: float = 5.0  # Block if > 5% quality drop
    MODEL_A_B_TEST_STAGES: List[float] = [0.01, 0.10, 0.50, 1.0]  # 1% -> 10% -> 50% -> 100%
    MODEL_AB_TEST_MIN_SAMPLES: int = 100
    
    # ======================================================================
    # Observability & Monitoring
    # ======================================================================
    PROMETHEUS_ENABLED: bool = os.getenv("PROMETHEUS_ENABLED", "true").lower() == "true"
    PROMETHEUS_PORT: int = int(os.getenv("PROMETHEUS_PORT", "8001"))
    
    OTEL_ENABLED: bool = os.getenv("OTEL_ENABLED", "false").lower() == "true"
    OTEL_JAEGER_ENABLED: bool = os.getenv("OTEL_JAEGER_ENABLED", "false").lower() == "true"
    OTEL_JAEGER_HOST: str = os.getenv("OTEL_JAEGER_HOST", "localhost")
    OTEL_JAEGER_PORT: int = int(os.getenv("OTEL_JAEGER_PORT", "6831"))
    OTEL_TRACE_SAMPLE_RATE: float = float(os.getenv("OTEL_TRACE_SAMPLE_RATE", "0.1"))
    
    LOGGING_LEVEL: str = os.getenv("LOGGING_LEVEL", "INFO")
    STRUCTURED_LOGGING_ENABLED: bool = True
    
    # ======================================================================
    # Cost Tracking & Billing
    # ======================================================================
    COST_TRACKING_ENABLED: bool = True
    LLM_COST_PER_1K_TOKENS: float = 0.03
    RETRIEVAL_COST_PER_QUERY: float = 0.001
    COMPUTE_COST_PER_SECOND: float = 0.001
    
    # ======================================================================
    # Health Check
    # ======================================================================
    HEALTH_CHECK_INTERVAL_SEC: int = 30
    LIVENESS_PROBE_ENABLED: bool = True
    READINESS_PROBE_ENABLED: bool = True
    
    # ======================================================================
    # Insider Threat Detection
    # ======================================================================
    THREAT_DETECTION_ENABLED: bool = os.getenv("THREAT_DETECTION_ENABLED", "true").lower() == "true"
    BEHAVIOR_BASELINE_WINDOW_DAYS: int = 30
    ANOMALY_SCORE_THRESHOLD: float = 70.0  # Alert if score > 70
    MASS_EXPORT_THRESHOLD: int = 1000  # documents per day
    QUERY_SCRAPING_WINDOW: int = 10  # Check last 10 queries
    QUERY_SCRAPING_SIMILARITY_THRESHOLD: float = 0.90
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


# Export singleton
settings = get_settings()
