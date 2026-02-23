"""Structured logging configuration for enterprise observability"""
import structlog
import logging
from pythonjsonlogger import jsonlogger
from app.core.config import settings
import sys


def configure_logging():
    """Configure structured logging with JSON output"""
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecimalRenderer(),
            structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    if settings.debug:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    else:
        formatter = jsonlogger.JsonFormatter(
            '%(asctime)s %(name)s %(levelname)s %(message)s'
        )
    
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Suppress noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("opensearchpy").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)


def get_logger(name: str):
    """Get a configured logger instance"""
    return structlog.get_logger(name)


class AuditLogger:
    """Centralized audit logging for compliance"""
    
    def __init__(self):
        self.logger = structlog.get_logger("audit")
    
    def log_query(self, tenant_id: str, user_id: str, query: str, status: str):
        """Log query execution"""
        self.logger.info(
            "query_executed",
            tenant_id=tenant_id,
            user_id=user_id,
            query=query[:100],  # Truncate for logging
            status=status,
        )
    
    def log_authentication(self, tenant_id: str, user_id: str, status: str, ip: str):
        """Log authentication events"""
        self.logger.info(
            "authentication",
            tenant_id=tenant_id,
            user_id=user_id,
            status=status,
            ip=ip,
        )
    
    def log_data_access(self, tenant_id: str, user_id: str, resource: str, action: str):
        """Log data access events"""
        self.logger.info(
            "data_access",
            tenant_id=tenant_id,
            user_id=user_id,
            resource=resource,
            action=action,
        )
    
    def log_security_event(self, event_type: str, tenant_id: str, details: dict):
        """Log security-related events"""
        self.logger.warning(
            "security_event",
            event_type=event_type,
            tenant_id=tenant_id,
            **details
        )
    
    def log_cost_event(self, tenant_id: str, cost_type: str, amount: float, details: dict):
        """Log cost tracking events"""
        self.logger.info(
            "cost_event",
            tenant_id=tenant_id,
            cost_type=cost_type,
            amount=amount,
            **details
        )
    
    def log_compliance_check(self, tenant_id: str, check_type: str, passed: bool, details: dict):
        """Log compliance check events"""
        level = "info" if passed else "warning"
        log_func = getattr(self.logger, level)
        log_func(
            "compliance_check",
            tenant_id=tenant_id,
            check_type=check_type,
            passed=passed,
            **details
        )


# Global audit logger instance
audit_logger = AuditLogger()


class ContextFilter(logging.Filter):
    """Add context information to log records"""
    
    def filter(self, record):
        # Add any additional context here
        return True
