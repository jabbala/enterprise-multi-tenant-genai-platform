"""
Data models and schemas for the Enterprise Multi-Tenant GenAI Platform.
Includes tenant schemas, query/response models, cost tracking, and security models.
"""

from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from enum import Enum
import re

# ============================================================================
# Enums
# ============================================================================

class TenantTier(str, Enum):
    """Tenant subscription tiers for resource allocation and fair queuing."""
    ENTERPRISE = "enterprise"      # 50% fair share, 100 QPS, P95 < 2s
    PROFESSIONAL = "professional" # 30% fair share, 20 QPS, P95 < 3s
    STARTER = "starter"           # 15% fair share, 5 QPS, P95 < 5s
    FREE = "free"                 # 5% fair share, 1 QPS, best effort


class ClassificationTier(str, Enum):
    """Data sensitivity classification tiers."""
    PUBLIC = "public"             # Tier 0: Free LLM processing
    INTERNAL = "internal"         # Tier 1: Normal LLM processing
    CONFIDENTIAL = "confidential" # Tier 2: Requires approval, LLM summarizes
    RESTRICTED = "restricted"     # Tier 3: No LLM processing


class UserRole(str, Enum):
    """User roles for RBAC."""
    ADMIN = "admin"       # Full access
    ANALYST = "analyst"   # Query + document access
    VIEWER = "viewer"     # Read-only


class HTTPMethod(str, Enum):
    """HTTP methods for audit logging."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class IncidentSeverity(str, Enum):
    """Severity levels for security incidents."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ============================================================================
# Tenant Configuration
# ============================================================================

class TenantConfig(BaseModel):
    """Configuration for a tenant."""
    tenant_id: str = Field(..., min_length=3, max_length=64)
    tenant_name: str
    tier: TenantTier = TenantTier.STARTER
    qps_limit: int = Field(default=5, ge=1, le=1000)
    daily_quota: int = Field(default=100000, ge=1)
    burst_qps: int = Field(default=10, ge=1)
    burst_duration_seconds: int = Field(default=5, ge=1)
    data_residency: Literal["eu", "us", "apac"] = "us"
    retention_days: int = Field(default=90, ge=7, le=365)
    encryption_enabled: bool = True
    vector_search_enabled: bool = True
    llm_enabled: bool = True
    fallback_to_search_enabled: bool = True
    monthly_cost_limit_usd: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# User & Authentication
# ============================================================================

class User(BaseModel):
    """User information from JWT token."""
    user_id: str = Field(..., min_length=3, max_length=256)
    tenant_id: str
    roles: List[UserRole]
    email: Optional[str] = None
    
    def has_role(self, role: UserRole) -> bool:
        return role in self.roles
    
    def is_admin(self) -> bool:
        return self.has_role(UserRole.ADMIN)


class JWTPayload(BaseModel):
    """JWT token payload structure."""
    user_id: str
    tenant_id: str
    roles: List[str]
    email: Optional[str] = None
    exp: int
    iat: int
    iss: str = "genai-platform"


# ============================================================================
# Query & Response Models
# ============================================================================

class DocumentSource(BaseModel):
    """A document source in the response."""
    doc_id: str
    content: str
    score: float = Field(ge=0.0, le=1.0)
    source: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SourceDocument(BaseModel):
    """Legacy source document for backward compatibility."""
    content: str
    score: float


class QueryRequest(BaseModel):
    """User query request."""
    query: str = Field(..., min_length=1, max_length=2000)
    filters: Optional[Dict[str, Any]] = None
    top_k: int = Field(default=5, ge=1, le=20)
    bm25_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    use_llm: bool = True
    model_name: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    max_tokens: int = Field(default=1024, ge=256, le=4096)
    
    @field_validator('query')
    @classmethod
    def validate_no_injection(cls, v: str) -> str:
        """Validate query for prompt injection patterns."""
        injection_keywords = [
            r'ignore', r'disregard', r'override', r'bypass', 
            r'forget', r'clear context', r'new instructions',
            r'you are now', r'respond as', r'act as'
        ]
        query_lower = v.lower()
        for keyword in injection_keywords:
            if re.search(keyword, query_lower):
                raise ValueError(f"Potential prompt injection detected: {keyword}")
        return v


class QueryResponse(BaseModel):
    """Response to a user query."""
    request_id: str
    tenant_id: str
    answer: str
    sources: List[DocumentSource]
    generated_by: str = "llm"
    confidence_level: float = Field(ge=0.0, le=1.0)
    cost_dollars: float = Field(default=0.0, ge=0.0)
    tokens_used: int = Field(default=0, ge=0)
    latency_ms: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    model_name: Optional[str] = None
    model_version: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response."""
    request_id: str
    error: str
    error_code: str
    http_status: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Optional[Dict[str, Any]] = None


# ============================================================================
# Document Models
# ============================================================================

class DocumentMetadata(BaseModel):
    """Document metadata."""
    tenant_id: str
    source: str = Field(default="unknown")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    author: Optional[str] = None
    tags: Optional[List[str]] = None
    external_id: Optional[str] = None


class Document(BaseModel):
    """A searchable document."""
    doc_id: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1)
    metadata: DocumentMetadata
    classification: ClassificationTier = ClassificationTier.INTERNAL
    vector: Optional[List[float]] = None
    vector_model: str = "text-embedding-3-small"


class DocumentIngestRequest(BaseModel):
    """Request to ingest documents."""
    documents: List[Document]
    batch_id: Optional[str] = None


# ============================================================================
# Cost & Billing Models
# ============================================================================

class TokenEstimate(BaseModel):
    """Token usage estimate."""
    prompt_tokens: int
    estimated_completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


class CostEvent(BaseModel):
    """A cost event for billing."""
    request_id: str
    tenant_id: str
    user_id: str
    operation: str
    estimated_tokens: int
    actual_tokens: Optional[int] = None
    estimated_cost_usd: float
    actual_cost_usd: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BillingRecord(BaseModel):
    """Billing record for a tenant."""
    billing_period: str
    tenant_id: str
    llm_cost_usd: float = 0.0
    retrieval_cost_usd: float = 0.0
    compute_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    query_count: int = 0
    document_count: int = 0


# ============================================================================
# Audit & Logging Models
# ============================================================================

class AuditLog(BaseModel):
    """Immutable audit log entry."""
    log_id: str
    tenant_id: str
    user_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    http_method: HTTPMethod
    endpoint: str
    request_body: Optional[Dict[str, Any]] = None
    http_status: int
    response_body: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    jwt_claims: Optional[Dict[str, Any]] = None
    success: bool
    error_message: Optional[str] = None


class SecurityEvent(BaseModel):
    """Security-related event for threat detection."""
    event_id: str
    tenant_id: str
    user_id: str
    event_type: str
    severity: IncidentSeverity
    description: str
    evidence: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    is_false_positive: bool = False
    investigation_notes: Optional[str] = None


# ============================================================================
# Queue & Scheduling Models
# ============================================================================

class QueuedRequest(BaseModel):
    """A request in the processing queue."""
    request_id: str
    tenant_id: str
    user_id: str
    priority: int
    submitted_at: datetime
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    query_data: Dict[str, Any]
    status: Literal["queued", "executing", "completed", "failed", "rejected"] = "queued"


class ConcurrencyToken(BaseModel):
    """Token from token bucket for rate limiting."""
    tenant_id: str
    tokens_available: int
    last_refill: datetime
    refill_rate: int


# ============================================================================
# Encryption Models
# ============================================================================

class EncryptionKeySpec(BaseModel):
    """Specification for encryption key."""
    key_id: str
    algorithm: Literal["AES-256-GCM", "AES-128-GCM"] = "AES-256-GCM"
    kms_provider: Literal["aws-kms", "gcp-kms", "azure-kms", "k8s-secret"] = "aws-kms"
    rotation_period_days: int = 365
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EncryptedDocument(BaseModel):
    """Document with encrypted content."""
    doc_id: str
    encrypted_content: str
    encryption_key_id: str
    nonce: str
    metadata: DocumentMetadata


# ============================================================================
# Model Evaluation Models
# ============================================================================

class EvaluationDatasetVersion(BaseModel):
    """Version of the evaluation dataset."""
    dataset_id: str
    version: str
    created_at: datetime
    created_by: str
    description: str
    query_count: int


class EvaluationQuery(BaseModel):
    """A query in the evaluation dataset."""
    query_id: str
    query_text: str
    expected_answer: str
    quality_criteria: Dict[str, float]
    query_type: str


class ModelBaseline(BaseModel):
    """Baseline metrics for a model version."""
    model_version: str
    dataset_version: str
    bleu_score: float
    rouge_score: float
    human_rating: float
    answer_relevance: float
    created_at: datetime


class ModelEvaluationResult(BaseModel):
    """Results from evaluating a model."""
    model_version: str
    dataset_version: str
    baseline: ModelBaseline
    bleu_score: float
    rouge_score: float
    human_rating: float
    answer_relevance: float
    quality_drop_pct: float
    regression_detected: bool
    p_value: Optional[float] = None


# ============================================================================
# Insider Threat Detection Models
# ============================================================================

class UserBehaviorBaseline(BaseModel):
    """Baseline behavior for a user."""
    user_id: str
    tenant_id: str
    avg_queries_per_day: float
    avg_queries_per_hour: float
    queries_by_hour: Dict[int, int]
    unique_query_types: int
    typical_locations: List[str]
    typical_devices: List[str]
    typical_ips: List[str]


class UserAnomalyScore(BaseModel):
    """Anomaly score for a user (0-100)."""
    user_id: str
    tenant_id: str
    score: float = Field(ge=0.0, le=100.0)
    factors: Dict[str, float]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    triggered_alerts: List[str]


class InsiderThreatIncident(BaseModel):
    """Detected insider threat incident."""
    incident_id: str
    user_id: str
    tenant_id: str
    threat_type: str
    severity: IncidentSeverity
    description: str
    evidence: Dict[str, Any]
    detected_at: datetime
    requires_escalation: bool = False
    escalated_to: Optional[str] = None