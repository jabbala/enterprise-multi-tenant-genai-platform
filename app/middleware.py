"""Middleware for observability, cost tracking, and security"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import time
import structlog
from app.core.metrics import (
    active_requests,
    query_count,
    cost_total,
)
from app.core.logging_config import audit_logger
from app.core.config import settings

logger = structlog.get_logger(__name__)


class CostTrackingMiddleware(BaseHTTPMiddleware):
    """Track costs per tenant for usage and billing"""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        tenant_id = request.headers.get("X-Tenant-ID", "unknown")
        
        start_time = time.time()
        
        try:
            response = await call_next(request)
            duration = time.time() - start_time
            
            # Calculate cost (basic model: cost per second of compute)
            cost = duration * 0.001  # $0.001 per second
            cost_total.labels(tenant_id=tenant_id, cost_type="compute").inc(cost)
            
            # Log cost event
            if settings.cost_tracking_enabled:
                audit_logger.log_cost_event(
                    tenant_id,
                    "api_request",
                    cost,
                    {
                        "endpoint": request.url.path,
                        "method": request.method,
                        "duration_seconds": duration,
                        "status_code": response.status_code,
                    }
                )
            
            # Add cost header
            response.headers["X-Cost-Dollars"] = f"{cost:.6f}"
            response.headers["X-Tenant-ID"] = tenant_id
            
            return response
        except Exception as e:
            duration = time.time() - start_time
            logger.error("middleware_error", endpoint=request.url.path, error=str(e))
            raise


class MetricsMiddleware(BaseHTTPMiddleware):
    """Track request metrics"""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        tenant_id = request.headers.get("X-Tenant-ID", "unknown")
        endpoint = request.url.path
        
        active_requests.labels(tenant_id=tenant_id, endpoint=endpoint).inc()
        
        try:
            response = await call_next(request)
            
            # Track status
            status = "success" if response.status_code < 400 else "error"
            query_count.labels(tenant_id=tenant_id, status=status).inc()
            
            return response
        finally:
            active_requests.labels(tenant_id=tenant_id, endpoint=endpoint).dec()


class SecurityMiddleware(BaseHTTPMiddleware):
    """Add security headers and validate requests"""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Validate tenant ID
        tenant_id = request.headers.get("X-Tenant-ID")
        user_id = request.headers.get("X-User-ID", "unknown")
        
        if not tenant_id and request.url.path not in ["/health", "/metrics"]:
            logger.warning("missing_tenant_id", endpoint=request.url.path)
            return JSONResponse(
                status_code=400,
                content={"detail": "X-Tenant-ID header required"}
            )
        
        # Audit authentication
        if request.url.path == "/login" or request.url.path == "/auth":
            audit_logger.log_authentication(
                tenant_id or "unknown",
                user_id,
                "attempted",
                request.client.host if request.client else "unknown"
            )
        
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return response


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Log all API access for audit trails"""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        tenant_id = request.headers.get("X-Tenant-ID", "unknown")
        user_id = request.headers.get("X-User-ID", "unknown")
        
        start_time = time.time()
        
        try:
            response = await call_next(request)
            duration = time.time() - start_time
            
            # Log API access
            audit_logger.log_data_access(
                tenant_id,
                user_id,
                request.url.path,
                request.method
            )
            
            logger.info(
                "api_call",
                tenant_id=tenant_id,
                user_id=user_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration=duration,
            )
            
            return response
        except Exception as e:
            logger.error(
                "api_error",
                tenant_id=tenant_id,
                method=request.method,
                path=request.url.path,
                error=str(e)
            )
            raise


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple rate limiting per tenant"""
    
    def __init__(self, app, requests_per_minute: int = 100):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.request_counts = {}  # tenant_id -> [timestamps]
    
    async def dispatch(self, request: Request, call_next) -> Response:
        tenant_id = request.headers.get("X-Tenant-ID", "unknown")
        current_time = time.time()
        
        # Clean old requests (older than 1 minute)
        if tenant_id not in self.request_counts:
            self.request_counts[tenant_id] = []
        
        self.request_counts[tenant_id] = [
            t for t in self.request_counts[tenant_id]
            if current_time - t < 60
        ]
        
        # Check rate limit
        if len(self.request_counts[tenant_id]) >= self.requests_per_minute:
            logger.warning("rate_limit_exceeded", tenant_id=tenant_id)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"}
            )
        
        self.request_counts[tenant_id].append(current_time)
        
        return await call_next(request)
