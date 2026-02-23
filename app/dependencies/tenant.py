"""
Tenant dependency injection and multi-tenant context management.
Extracts tenant_id and user from JWT token and validates permissions.
"""

import logging
from typing import Optional
from fastapi import HTTPException, status, Request, Depends
from functools import lru_cache

from app.models.schemas import User, UserRole, TenantConfig
from app.core.security import JWTHandler

logger = logging.getLogger(__name__)


class TenantContext:
    """Context for a single request containing tenant and user information."""
    
    def __init__(
        self,
        user: User,
        tenant_config: Optional[TenantConfig] = None,
    ):
        self.user = user
        self.tenant_id = user.tenant_id
        self.user_id = user.user_id
        self.roles = user.roles
        self.tenant_config = tenant_config or TenantConfig(
            tenant_id=user.tenant_id,
            tenant_name=user.tenant_id,
        )
    
    def has_role(self, role: UserRole) -> bool:
        """Check if user has specific role."""
        return self.user.has_role(role)
    
    def is_admin(self) -> bool:
        """Check if user is admin."""
        return self.user.is_admin()
    
    def require_role(self, required_role: UserRole) -> None:
        """Require user to have specific role, raise exception if not."""
        if not self.has_role(required_role):
            raise PermissionDenied(
                f"User {self.user_id} requires {required_role.value} role"
            )
    
    def require_admin(self) -> None:
        """Require user to be admin."""
        self.require_role(UserRole.ADMIN)


class TenantAuthorization:
    """Validate tenant authorization and extract from JWT."""
    
    @staticmethod
    def extract_token_from_header(authorization: Optional[str]) -> Optional[str]:
        """Extract JWT token from Authorization header."""
        if not authorization:
            return None
        
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        
        return None
    
    @staticmethod
    async def validate_request(request: Request) -> TenantContext:
        """
        Validate request and extract tenant context.
        This is called as a FastAPI dependency.
        """
        # Extract token from Authorization header
        auth_header = request.headers.get("Authorization")
        token = TenantAuthorization.extract_token_from_header(auth_header)
        
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Decode and validate token
        user = JWTHandler.decode_token(token)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        logger.info(
            f"Authenticated user {user.user_id} for tenant {user.tenant_id} "
            f"with roles {[r.value for r in user.roles]}"
        )
        
        # Create tenant context
        return TenantContext(user=user)


# Dependency for FastAPI
async def get_current_user(request: Request) -> TenantContext:
    """FastAPI dependency to get current user and validate token."""
    return await TenantAuthorization.validate_request(request)


# ============================================================================
# Custom Exceptions
# ============================================================================

class PermissionDenied(HTTPException):
    """User doesn't have required permission."""
    
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class CrossTenantAccessAttempted(HTTPException):
    """Attempted cross-tenant data access."""
    
    def __init__(self, detail: str = "Cross-tenant access denied"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )
    
    @staticmethod
    def validate_tenant_ownership(
        context: TenantContext,
        resource_tenant_id: str,
    ) -> None:
        """Validate that resource belongs to user's tenant."""
        if context.tenant_id != resource_tenant_id:
            raise CrossTenantAccessAttempted(
                f"Resource belongs to tenant {resource_tenant_id}, "
                f"but user is from tenant {context.tenant_id}"
            )


# ============================================================================
# Token Bucket Rate Limiting
# ============================================================================

class TokenBucket:
    """Token bucket for rate limiting."""
    
    def __init__(
        self,
        capacity: int,
        refill_rate: float,  # Tokens per second
    ):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate
        self.last_refill_time = None
    
    def try_consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Return True if successful."""
        import time
        
        now = time.time()
        if self.last_refill_time is None:
            self.last_refill_time = now
        
        # Calculate tokens to add since last refill
        time_passed = now - self.last_refill_time
        tokens_to_add = time_passed * self.refill_rate
        
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill_time = now
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        
        return False
    
    def remaining_tokens(self) -> int:
        """Get remaining tokens."""
        return int(self.tokens)


# ============================================================================
# Rate Limit Headers
# ============================================================================

def create_rate_limit_headers(
    limit: int,
    remaining: int,
    reset_timestamp: int,
) -> dict:
    """Create rate limit headers for response."""
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Reset": str(reset_timestamp),
    }