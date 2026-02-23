"""Circuit breaker and retry logic for resilience"""
from pybreaker import CircuitBreaker
from tenacity import (
    Retrying,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_log,
    after_log,
)
from functools import wraps
from typing import Callable, Type, Optional
import asyncio
import structlog

logger = structlog.get_logger(__name__)


class TenantAwareCircuitBreaker(CircuitBreaker):
    """Circuit breaker with per-tenant state tracking"""
    
    def __init__(self, name: str, fail_max: int = 5, reset_timeout: int = 60, **kwargs):
        super().__init__(
            name=name,
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            listeners=[],
            **kwargs
        )
        self.tenant_states = {}
    
    def get_tenant_breaker(self, tenant_id: str) -> 'CircuitBreaker':
        """Get or create circuit breaker for tenant"""
        if tenant_id not in self.tenant_states:
            self.tenant_states[tenant_id] = CircuitBreaker(
                name=f"{self.name}_{tenant_id}",
                fail_max=self.fail_max,
                reset_timeout=self.reset_timeout,
            )
        return self.tenant_states[tenant_id]
    
    def call(self, func, *args, **kwargs):
        """Call function with circuit breaker protection"""
        return super().call(func, *args, **kwargs)


# Global circuit breakers for different services
llm_circuit_breaker = TenantAwareCircuitBreaker(
    "llm_service",
    fail_max=5,
    reset_timeout=60
)

opensearch_circuit_breaker = TenantAwareCircuitBreaker(
    "opensearch_service",
    fail_max=5,
    reset_timeout=60
)

vector_store_circuit_breaker = TenantAwareCircuitBreaker(
    "vector_store_service",
    fail_max=5,
    reset_timeout=60
)

redis_circuit_breaker = TenantAwareCircuitBreaker(
    "redis_service",
    fail_max=5,
    reset_timeout=60
)


def with_circuit_breaker(breaker: TenantAwareCircuitBreaker, tenant_id: str = None):
    """Decorator to apply circuit breaker pattern"""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, tenant_id_arg=None, **kwargs):
            tenant = tenant_id or tenant_id_arg or args[0]
            cb = breaker.get_tenant_breaker(str(tenant))
            
            try:
                return await cb.call(lambda: func(*args, **kwargs))
            except Exception as e:
                logger.error(
                    "circuit_breaker_error",
                    service=breaker.name,
                    tenant_id=tenant,
                    error=str(e)
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, tenant_id_arg=None, **kwargs):
            tenant = tenant_id or tenant_id_arg or args[0]
            cb = breaker.get_tenant_breaker(str(tenant))
            
            try:
                return cb.call(func, *args, **kwargs)
            except Exception as e:
                logger.error(
                    "circuit_breaker_error",
                    service=breaker.name,
                    tenant_id=tenant,
                    error=str(e)
                )
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def with_retry(
    max_attempts: int = 3,
    wait_multiplier: int = 1,
    max_wait: int = 10,
    exceptions: tuple = (Exception,)
):
    """Decorator to apply retry logic with exponential backoff"""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger_instance = structlog.get_logger(__name__)
            for attempt in Retrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=wait_multiplier, max=max_wait),
                retry=retry_if_exception_type(exceptions),
                before=before_log(logger_instance, logging_level="debug"),
                after=after_log(logger_instance, logging_level="debug"),
            ):
                with attempt:
                    return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            logger_instance = structlog.get_logger(__name__)
            for attempt in Retrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=wait_multiplier, max=max_wait),
                retry=retry_if_exception_type(exceptions),
                before=before_log(logger_instance, logging_level="debug"),
                after=after_log(logger_instance, logging_level="debug"),
            ):
                with attempt:
                    return func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


class ResilientClient:
    """Base class for clients with resilience patterns"""
    
    def __init__(self, name: str, circuit_breaker: TenantAwareCircuitBreaker):
        self.name = name
        self.circuit_breaker = circuit_breaker
        self.logger = structlog.get_logger(name)
    
    async def execute_with_resilience(
        self,
        func: Callable,
        tenant_id: str,
        *args,
        max_retries: int = 3,
        **kwargs
    ):
        """Execute function with circuit breaker and retry logic"""
        cb = self.circuit_breaker.get_tenant_breaker(str(tenant_id))
        
        for attempt in range(max_retries):
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await cb.call(lambda: func(*args, **kwargs))
                else:
                    result = cb.call(func, *args, **kwargs)
                
                self.logger.debug(
                    "resilient_call_success",
                    tenant_id=tenant_id,
                    attempt=attempt + 1
                )
                return result
            
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(
                        "resilient_call_failed",
                        tenant_id=tenant_id,
                        attempts=max_retries,
                        error=str(e)
                    )
                    raise
                
                wait_time = (2 ** attempt)
                self.logger.warning(
                    "resilient_call_retry",
                    tenant_id=tenant_id,
                    attempt=attempt + 1,
                    wait_seconds=wait_time,
                    error=str(e)
                )
                await asyncio.sleep(wait_time)
