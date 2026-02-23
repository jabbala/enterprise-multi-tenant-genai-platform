"""Governance service for compliance, security, and data protection"""
import re
from typing import List, Dict
from app.core.metrics import pii_redactions_performed, cross_tenant_leakage_attempts
from app.core.config import settings
from app.core.logging_config import audit_logger
import structlog

logger = structlog.get_logger(__name__)


# PII patterns
PII_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
}

# Prompt injection patterns
INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore the above instructions",
    "disregard",
    "forget the system prompt",
    "you are now in developer mode",
    "system override",
    "execute this command",
    "bypass",
]


def validate_prompt(query: str):
    """Validate query for prompt injection attempts"""
    query_lower = query.lower()
    
    for pattern in INJECTION_PATTERNS:
        if pattern in query_lower:
            logger.warning("prompt_injection_detected", pattern=pattern)
            audit_logger.log_security_event(
                "unknown_tenant",
                "prompt_injection",
                {"pattern": pattern, "query": query[:100]}
            )
            raise ValueError(f"Potential prompt injection detected: {pattern}")
    
    logger.debug("prompt_validation_passed")


def redact_pii(text: str) -> str:
    """Redact personally identifiable information from text"""
    if not settings.pii_redaction_enabled:
        return text
    
    redacted_text = text
    redactions_made = {}
    
    try:
        for pii_type, pattern in PII_PATTERNS.items():
            matches = re.findall(pattern, text)
            if matches:
                redacted_text = re.sub(pattern, f"[REDACTED_{pii_type.upper()}]", redacted_text)
                redactions_made[pii_type] = len(matches)
                pii_redactions_performed.labels(tenant_id="batch", pii_type=pii_type).inc(len(matches))
        
        if redactions_made:
            logger.info("pii_redaction_performed", redactions=redactions_made)
        
        return redacted_text
    except Exception as e:
        logger.error("pii_redaction_failed", error=str(e))
        return text


def check_cross_tenant_leakage(docs: List[Dict], requesting_tenant_id: str):
    """Verify that retrieved documents belong only to requesting tenant"""
    if not settings.cross_tenant_leakage_check_enabled:
        return
    
    try:
        for doc in docs:
            # Check if document has tenant metadata
            doc_tenant_id = doc.get("tenant_id") or doc.get("metadata", {}).get("tenant_id")
            
            if doc_tenant_id and doc_tenant_id != requesting_tenant_id:
                logger.error(
                    "cross_tenant_leakage_detected",
                    requesting_tenant=requesting_tenant_id,
                    doc_tenant=doc_tenant_id,
                    doc_id=doc.get("doc_id")
                )
                cross_tenant_leakage_attempts.labels(source="retrieval").inc()
                audit_logger.log_security_event(
                    requesting_tenant_id,
                    "cross_tenant_leakage_attempt",
                    {
                        "requesting_tenant": requesting_tenant_id,
                        "document_tenant": doc_tenant_id,
                        "doc_id": doc.get("doc_id")
                    }
                )
                raise ValueError("Security violation: Cross-tenant data access detected")
        
        logger.debug("cross_tenant_leakage_check_passed", tenant_id=requesting_tenant_id)
    except Exception as e:
        logger.error("cross_tenant_check_failed", tenant_id=requesting_tenant_id, error=str(e))
        raise


def validate_user_permissions(tenant_id: str, user_id: str, action: str) -> bool:
    """Validate user has permission to perform action in tenant"""
    logger.debug("validating_user_permissions", tenant_id=tenant_id, user_id=user_id, action=action)
    
    # In production, check against RBAC system
    # For now, return True
    return True


def mask_sensitive_data(data: dict, tenant_id: str) -> dict:
    """Mask or remove sensitive data from responses"""
    try:
        masked = data.copy()
        
        # Remove internal fields
        internal_fields = ["_id", "internal_id", "password_hash", "api_key"]
        for field in internal_fields:
            if field in masked:
                del masked[field]
        
        # Redact sensitive values
        if "email" in masked:
            masked["email"] = f"***@{masked['email'].split('@')[1]}"
        
        logger.debug("data_masked", tenant_id=tenant_id)
        return masked
    except Exception as e:
        logger.error("data_masking_failed", tenant_id=tenant_id, error=str(e))
        return data


def validate_data_classification(data: dict, tenant_id: str) -> bool:
    """Ensure data meets classification standards"""
    try:
        # Check for required metadata
        required_fields = ["classification_level", "owner", "created_at"]
        
        for field in required_fields:
            if field not in data:
                logger.warning("missing_classification_field", field=field, tenant_id=tenant_id)
                return False
        
        # Validate classification level
        valid_levels = ["public", "internal", "confidential", "restricted"]
        classification = data.get("classification_level", "").lower()
        
        if classification not in valid_levels:
            logger.warning("invalid_classification_level", level=classification, tenant_id=tenant_id)
            return False
        
        logger.debug("data_classification_valid", tenant_id=tenant_id)
        return True
    except Exception as e:
        logger.error("data_classification_check_failed", tenant_id=tenant_id, error=str(e))
        return False


def audit_data_access(tenant_id: str, user_id: str, resource: str, action: str, details: dict = None):
    """Log data access for audit trail"""
    try:
        audit_logger.log_data_access(tenant_id, user_id, resource, action)
        logger.debug("data_access_logged", tenant_id=tenant_id, user_id=user_id, resource=resource)
    except Exception as e:
        logger.error("audit_logging_failed", error=str(e))
