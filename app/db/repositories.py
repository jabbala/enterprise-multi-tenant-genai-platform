"""Repository pattern for database access"""

from typing import List, Optional, Any, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.db.models import (
    TenantModel, UserModel, DocumentModel, AuditLogModel,
    CostEventModel, SecurityEventModel, QueuedRequestModel
)


class BaseRepository:
    """Base repository with common CRUD operations"""

    def __init__(self, db: Session, model):
        self.db = db
        self.model = model

    def create(self, obj_in: Dict) -> Any:
        """Create and return new object"""
        db_obj = self.model(**obj_in)
        self.db.add(db_obj)
        self.db.commit()
        self.db.refresh(db_obj)
        return db_obj

    def get(self, id: str) -> Optional[Any]:
        """Get object by ID"""
        return self.db.query(self.model).filter(self.model.id == id).first()

    def get_all(self, skip: int = 0, limit: int = 100) -> List[Any]:
        """Get all objects with pagination"""
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def update(self, id: str, obj_in: Dict) -> Optional[Any]:
        """Update object"""
        db_obj = self.get(id)
        if db_obj:
            for key, value in obj_in.items():
                setattr(db_obj, key, value)
            self.db.commit()
            self.db.refresh(db_obj)
        return db_obj

    def delete(self, id: str) -> bool:
        """Delete object"""
        db_obj = self.get(id)
        if db_obj:
            self.db.delete(db_obj)
            self.db.commit()
            return True
        return False

    def count(self) -> int:
        """Count all objects"""
        return self.db.query(self.model).count()


class TenantRepository(BaseRepository):
    """Tenant data access"""

    def __init__(self, db: Session):
        super().__init__(db, TenantModel)

    def get_by_name(self, name: str) -> Optional[TenantModel]:
        """Get tenant by name"""
        return self.db.query(TenantModel).filter(TenantModel.name == name).first()

    def get_active_tenants(self) -> List[TenantModel]:
        """Get all active tenants"""
        return self.db.query(TenantModel).filter(TenantModel.status == "active").all()

    def get_by_tier(self, tier: str) -> List[TenantModel]:
        """Get tenants by tier"""
        return self.db.query(TenantModel).filter(TenantModel.tier == tier).all()


class UserRepository(BaseRepository):
    """User data access"""

    def __init__(self, db: Session):
        super().__init__(db, UserModel)

    def get_by_email(self, email: str) -> Optional[UserModel]:
        """Get user by email"""
        return self.db.query(UserModel).filter(UserModel.email == email).first()

    def get_by_tenant(self, tenant_id: str) -> List[UserModel]:
        """Get all users in tenant"""
        return self.db.query(UserModel).filter(UserModel.tenant_id == tenant_id).all()

    def get_active_users(self, tenant_id: str) -> List[UserModel]:
        """Get active users in tenant"""
        return self.db.query(UserModel).filter(
            and_(UserModel.tenant_id == tenant_id, UserModel.is_active == True)
        ).all()

    def get_by_role(self, tenant_id: str, role: str) -> List[UserModel]:
        """Get users with specific role"""
        return self.db.query(UserModel).filter(
            and_(UserModel.tenant_id == tenant_id, UserModel.role == role)
        ).all()


class DocumentRepository(BaseRepository):
    """Document data access"""

    def __init__(self, db: Session):
        super().__init__(db, DocumentModel)

    def get_by_tenant(self, tenant_id: str, skip: int = 0, limit: int = 100) -> List[DocumentModel]:
        """Get documents in tenant"""
        return self.db.query(DocumentModel).filter(
            DocumentModel.tenant_id == tenant_id
        ).offset(skip).limit(limit).all()

    def get_by_classification(self, tenant_id: str, classification: str) -> List[DocumentModel]:
        """Get documents by classification"""
        return self.db.query(DocumentModel).filter(
            and_(
                DocumentModel.tenant_id == tenant_id,
                DocumentModel.classification == classification
            )
        ).all()

    def search_by_title(self, tenant_id: str, search_text: str) -> List[DocumentModel]:
        """Search documents by title"""
        return self.db.query(DocumentModel).filter(
            and_(
                DocumentModel.tenant_id == tenant_id,
                DocumentModel.title.ilike(f"%{search_text}%")
            )
        ).all()

    def get_by_vector_id(self, vector_id: str) -> Optional[DocumentModel]:
        """Get document by vector ID"""
        return self.db.query(DocumentModel).filter(DocumentModel.vector_id == vector_id).first()

    def count_by_tenant(self, tenant_id: str) -> int:
        """Count documents in tenant"""
        return self.db.query(DocumentModel).filter(DocumentModel.tenant_id == tenant_id).count()


class AuditLogRepository(BaseRepository):
    """Audit log data access"""

    def __init__(self, db: Session):
        super().__init__(db, AuditLogModel)

    def get_by_tenant(self, tenant_id: str, skip: int = 0, limit: int = 100) -> List[AuditLogModel]:
        """Get audit logs for tenant"""
        return self.db.query(AuditLogModel).filter(
            AuditLogModel.tenant_id == tenant_id
        ).order_by(AuditLogModel.timestamp.desc()).offset(skip).limit(limit).all()

    def get_by_user(self, user_id: str, skip: int = 0, limit: int = 100) -> List[AuditLogModel]:
        """Get audit logs for user"""
        return self.db.query(AuditLogModel).filter(
            AuditLogModel.user_id == user_id
        ).order_by(AuditLogModel.timestamp.desc()).offset(skip).limit(limit).all()

    def get_by_action(self, tenant_id: str, action: str) -> List[AuditLogModel]:
        """Get audit logs by action type"""
        return self.db.query(AuditLogModel).filter(
            and_(AuditLogModel.tenant_id == tenant_id, AuditLogModel.action == action)
        ).all()

    def get_failed_actions(self, tenant_id: str) -> List[AuditLogModel]:
        """Get failed audit logs"""
        return self.db.query(AuditLogModel).filter(
            and_(AuditLogModel.tenant_id == tenant_id, AuditLogModel.status == "failed")
        ).all()


class CostEventRepository(BaseRepository):
    """Cost event data access"""

    def __init__(self, db: Session):
        super().__init__(db, CostEventModel)

    def get_by_tenant(self, tenant_id: str, skip: int = 0, limit: int = 100) -> List[CostEventModel]:
        """Get cost events for tenant"""
        return self.db.query(CostEventModel).filter(
            CostEventModel.tenant_id == tenant_id
        ).order_by(CostEventModel.timestamp.desc()).offset(skip).limit(limit).all()

    def get_total_cost(self, tenant_id: str) -> float:
        """Calculate total cost for tenant"""
        result = self.db.query(CostEventModel).filter(
            CostEventModel.tenant_id == tenant_id
        ).with_entities(
            __import__('sqlalchemy').func.sum(CostEventModel.cost_usd)
        ).scalar()
        return result or 0.0

    def get_cost_by_type(self, tenant_id: str) -> Dict[str, float]:
        """Get cost breakdown by event type"""
        results = self.db.query(
            CostEventModel.event_type,
            __import__('sqlalchemy').func.sum(CostEventModel.cost_usd).label('total')
        ).filter(CostEventModel.tenant_id == tenant_id).group_by(CostEventModel.event_type).all()
        return {event_type: total for event_type, total in results}


class SecurityEventRepository(BaseRepository):
    """Security event data access"""

    def __init__(self, db: Session):
        super().__init__(db, SecurityEventModel)

    def get_unresolved(self, tenant_id: Optional[str] = None) -> List[SecurityEventModel]:
        """Get unresolved security events"""
        query = self.db.query(SecurityEventModel).filter(SecurityEventModel.resolved == False)
        if tenant_id:
            query = query.filter(SecurityEventModel.tenant_id == tenant_id)
        return query.all()

    def get_by_severity(self, severity: str, tenant_id: Optional[str] = None) -> List[SecurityEventModel]:
        """Get events by severity"""
        query = self.db.query(SecurityEventModel).filter(SecurityEventModel.severity == severity)
        if tenant_id:
            query = query.filter(SecurityEventModel.tenant_id == tenant_id)
        return query.all()

    def mark_resolved(self, event_id: str) -> Optional[SecurityEventModel]:
        """Mark event as resolved"""
        return self.update(event_id, {"resolved": True})


class QueuedRequestRepository(BaseRepository):
    """Queued request data access"""

    def __init__(self, db: Session):
        super().__init__(db, QueuedRequestModel)

    def get_queued(self, limit: int = 50) -> List[QueuedRequestModel]:
        """Get queued requests"""
        return self.db.query(QueuedRequestModel).filter(
            QueuedRequestModel.status == "queued"
        ).order_by(QueuedRequestModel.priority.desc(), QueuedRequestModel.created_at).limit(limit).all()

    def get_by_tenant(self, tenant_id: str) -> List[QueuedRequestModel]:
        """Get requests for tenant"""
        return self.db.query(QueuedRequestModel).filter(
            QueuedRequestModel.tenant_id == tenant_id
        ).all()

    def get_failed_requests(self) -> List[QueuedRequestModel]:
        """Get failed requests"""
        return self.db.query(QueuedRequestModel).filter(
            QueuedRequestModel.status == "failed"
        ).all()

    def get_by_status(self, status: str, skip: int = 0, limit: int = 100) -> List[QueuedRequestModel]:
        """Get requests by status"""
        return self.db.query(QueuedRequestModel).filter(
            QueuedRequestModel.status == status
        ).offset(skip).limit(limit).all()


# Repository factory
class RepositoryFactory:
    """Factory for creating repositories"""

    def __init__(self, db: Session):
        self.db = db

    @property
    def tenants(self) -> TenantRepository:
        return TenantRepository(self.db)

    @property
    def users(self) -> UserRepository:
        return UserRepository(self.db)

    @property
    def documents(self) -> DocumentRepository:
        return DocumentRepository(self.db)

    @property
    def audit_logs(self) -> AuditLogRepository:
        return AuditLogRepository(self.db)

    @property
    def cost_events(self) -> CostEventRepository:
        return CostEventRepository(self.db)

    @property
    def security_events(self) -> SecurityEventRepository:
        return SecurityEventRepository(self.db)

    @property
    def queued_requests(self) -> QueuedRequestRepository:
        return QueuedRequestRepository(self.db)
