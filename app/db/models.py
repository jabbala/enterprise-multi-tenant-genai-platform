"""SQLAlchemy ORM models for database tables"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON, Enum, Index
from sqlalchemy.orm import relationship
from app.db.database import Base
from app.models.schemas import TenantTier, ClassificationTier, UserRole, IncidentSeverity


class TenantModel(Base):
    """Tenant organization"""
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True)
    tier = Column(Enum(TenantTier), default=TenantTier.PROFESSIONAL)
    status = Column(String(50), default="active")
    max_users = Column(Integer, default=100)
    api_quota_per_day = Column(Integer, default=10000)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    metadata_json = Column(JSON, nullable=True)

    # Relationships
    users = relationship("UserModel", back_populates="tenant", cascade="all, delete-orphan")
    documents = relationship("DocumentModel", back_populates="tenant", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLogModel", back_populates="tenant", cascade="all, delete-orphan")
    cost_events = relationship("CostEventModel", back_populates="tenant", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_tenant_tier", "tier"),
        Index("idx_tenant_status", "status"),
    )


class UserModel(Base):
    """Tenant user"""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), index=True)
    email = Column(String(255), unique=True, index=True)
    full_name = Column(String(255))
    role = Column(Enum(UserRole), default=UserRole.VIEWER)
    is_active = Column(Boolean, default=True, index=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant = relationship("TenantModel", back_populates="users")

    __table_args__ = (
        Index("idx_user_tenant_role", "tenant_id", "role"),
        Index("idx_user_active", "is_active"),
    )


class DocumentModel(Base):
    """Ingested document"""
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), index=True)
    title = Column(String(500))
    content = Column(Text)
    classification = Column(Enum(ClassificationTier), default=ClassificationTier.PUBLIC)
    source_url = Column(String(2000), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    is_encrypted = Column(Boolean, default=False)
    vector_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    # Relationships
    tenant = relationship("TenantModel", back_populates="documents")

    __table_args__ = (
        Index("idx_document_tenant_class", "tenant_id", "classification"),
        Index("idx_document_expires", "expires_at"),
    )


class AuditLogModel(Base):
    """User action audit log"""
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    action = Column(String(100), index=True)
    resource_type = Column(String(100))
    resource_id = Column(String(100), nullable=True)
    details = Column(JSON)
    status = Column(String(50), default="success")
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    tenant = relationship("TenantModel", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_tenant_timestamp", "tenant_id", "timestamp"),
        Index("idx_audit_action", "action"),
    )


class CostEventModel(Base):
    """Cost tracking events"""
    __tablename__ = "cost_events"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), index=True)
    event_type = Column(String(50))  # "llm_tokens", "retrieval", "compute"
    cost_usd = Column(Float)
    tokens_used = Column(Integer, nullable=True)
    request_id = Column(String(100), index=True)
    details = Column(JSON)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    tenant = relationship("TenantModel", back_populates="cost_events")

    __table_args__ = (
        Index("idx_cost_tenant_timestamp", "tenant_id", "timestamp"),
        Index("idx_cost_type", "event_type"),
    )


class SecurityEventModel(Base):
    """Security incidents"""
    __tablename__ = "security_events"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), nullable=True, index=True)
    event_type = Column(String(100))  # "injection_attempt", "unauthorized_access", etc.
    severity = Column(Enum(IncidentSeverity), default=IncidentSeverity.LOW)
    description = Column(Text)
    source_ip = Column(String(45), nullable=True)
    user_id = Column(String(36), nullable=True)
    details = Column(JSON)
    resolved = Column(Boolean, default=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_security_tenant_severity", "tenant_id", "severity"),
        Index("idx_security_resolved", "resolved"),
    )


class QueuedRequestModel(Base):
    """Request queue for scheduler"""
    __tablename__ = "queued_requests"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True)
    user_id = Column(String(36))
    priority = Column(Integer, default=0)  # 0-3 for tiers
    request_data = Column(JSON)
    status = Column(String(50), default="queued")  # queued, processing, completed, failed
    result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_queued_tenant_status", "tenant_id", "status"),
        Index("idx_queued_priority", "priority"),
    )


class ModelEvaluationModel(Base):
    """Model evaluation results"""
    __tablename__ = "model_evaluations"

    id = Column(String(36), primary_key=True, index=True)
    model_name = Column(String(100), index=True)
    version = Column(String(50))
    metric_name = Column(String(100))
    value = Column(Float)
    dataset_size = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    metadata_json = Column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_eval_model_version", "model_name", "version"),
    )


class UserBehaviorBaselineModel(Base):
    """User behavior baseline for anomaly detection"""
    __tablename__ = "user_baselines"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), index=True)
    user_id = Column(String(36), ForeignKey("users.id"), index=True)
    metric_name = Column(String(100))  # "avg_queries_per_day", "avg_response_time", etc.
    baseline_value = Column(Float)
    std_deviation = Column(Float)
    data_points = Column(Integer)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant = relationship("TenantModel")
    user = relationship("UserModel")

    __table_args__ = (
        Index("idx_baseline_user", "user_id"),
    )
