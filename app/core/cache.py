"""Redis-based caching utilities for multi-tenant isolation"""
import json
import redis
import hashlib
from typing import Any, Optional, Callable
from functools import wraps
import asyncio
import aioredis
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)


class RedisCache:
    """Thread-safe Redis cache wrapper with tenant isolation"""
    
    def __init__(self):
        self.redis_client = None
        self.async_client = None
    
    def connect(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                decode_responses=True,
                max_connections=settings.redis_max_connections,
            )
            self.redis_client.ping()
            logger.info("redis_connected", host=settings.redis_host, port=settings.redis_port)
        except Exception as e:
            logger.error("redis_connection_failed", error=str(e))
            raise
    
    async def connect_async(self):
        """Initialize async Redis connection"""
        try:
            self.async_client = await aioredis.create_redis_pool(
                f"redis://{settings.redis_host}:{settings.redis_port}",
                db=settings.redis_db,
                minsize=5,
                maxsize=settings.redis_max_connections,
            )
            logger.info("redis_async_connected")
        except Exception as e:
            logger.error("redis_async_connection_failed", error=str(e))
            raise
    
    async def close_async(self):
        """Close async Redis connection"""
        if self.async_client:
            self.async_client.close()
            await self.async_client.wait_closed()
    
    def disconnect(self):
        """Close Redis connection"""
        if self.redis_client:
            self.redis_client.close()
    
    def get_cache_key(self, tenant_id: str, *args) -> str:
        """Generate tenant-isolated cache key"""
        key_parts = [str(tenant_id)] + [str(arg) for arg in args]
        key_string = ":".join(key_parts)
        # Hash long keys
        if len(key_string) > 200:
            return f"{tenant_id}:{hashlib.md5(key_string.encode()).hexdigest()}"
        return key_string
    
    def set(self, tenant_id: str, key: str, value: Any, ttl: int = None) -> bool:
        """Set value in cache with tenant isolation"""
        try:
            cache_key = self.get_cache_key(tenant_id, key)
            ttl = ttl or settings.redis_ttl_seconds
            
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            
            self.redis_client.setex(cache_key, ttl, value)
            logger.debug("cache_set", tenant_id=tenant_id, key=key, ttl=ttl)
            return True
        except Exception as e:
            logger.error("cache_set_failed", tenant_id=tenant_id, key=key, error=str(e))
            return False
    
    def get(self, tenant_id: str, key: str) -> Optional[Any]:
        """Get value from cache with tenant isolation"""
        try:
            cache_key = self.get_cache_key(tenant_id, key)
            value = self.redis_client.get(cache_key)
            
            if value:
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            
            logger.debug("cache_miss", tenant_id=tenant_id, key=key)
            return None
        except Exception as e:
            logger.error("cache_get_failed", tenant_id=tenant_id, key=key, error=str(e))
            return None
    
    def delete(self, tenant_id: str, key: str) -> bool:
        """Delete value from cache"""
        try:
            cache_key = self.get_cache_key(tenant_id, key)
            self.redis_client.delete(cache_key)
            logger.debug("cache_deleted", tenant_id=tenant_id, key=key)
            return True
        except Exception as e:
            logger.error("cache_delete_failed", tenant_id=tenant_id, key=key, error=str(e))
            return False
    
    def clear_tenant_cache(self, tenant_id: str) -> int:
        """Clear all cache entries for a tenant"""
        try:
            pattern = f"{tenant_id}:*"
            cursor = 0
            count = 0
            
            while True:
                cursor, keys = self.redis_client.scan(cursor, match=pattern)
                if keys:
                    self.redis_client.delete(*keys)
                    count += len(keys)
                if cursor == 0:
                    break
            
            logger.info("tenant_cache_cleared", tenant_id=tenant_id, count=count)
            return count
        except Exception as e:
            logger.error("cache_clear_failed", tenant_id=tenant_id, error=str(e))
            return 0
    
    async def set_async(self, tenant_id: str, key: str, value: Any, ttl: int = None) -> bool:
        """Async set value in cache"""
        try:
            cache_key = self.get_cache_key(tenant_id, key)
            ttl = ttl or settings.redis_ttl_seconds
            
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            
            await self.async_client.setex(cache_key, ttl, value)
            return True
        except Exception as e:
            logger.error("cache_set_async_failed", tenant_id=tenant_id, error=str(e))
            return False
    
    async def get_async(self, tenant_id: str, key: str) -> Optional[Any]:
        """Async get value from cache"""
        try:
            cache_key = self.get_cache_key(tenant_id, key)
            value = await self.async_client.get(cache_key)
            
            if value:
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            return None
        except Exception as e:
            logger.error("cache_get_async_failed", tenant_id=tenant_id, error=str(e))
            return None


# Global cache instance
cache = RedisCache()


def cache_result(ttl: int = None):
    """Decorator for caching function results with tenant isolation"""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(tenant_id: str, *args, **kwargs):
            cache_key = f"{func.__name__}:{':'.join(str(arg) for arg in args + tuple(kwargs.values()))}"
            
            # Try to get from cache
            cached = await cache.get_async(tenant_id, cache_key)
            if cached is not None:
                logger.debug("cache_hit", func=func.__name__, tenant_id=tenant_id)
                return cached
            
            # Execute function
            result = await func(tenant_id, *args, **kwargs)
            
            # Store in cache
            await cache.set_async(tenant_id, cache_key, result, ttl=ttl)
            return result
        
        @wraps(func)
        def sync_wrapper(tenant_id: str, *args, **kwargs):
            cache_key = f"{func.__name__}:{':'.join(str(arg) for arg in args + tuple(kwargs.values()))}"
            
            # Try to get from cache
            cached = cache.get(tenant_id, cache_key)
            if cached is not None:
                logger.debug("cache_hit", func=func.__name__, tenant_id=tenant_id)
                return cached
            
            # Execute function
            result = func(tenant_id, *args, **kwargs)
            
            # Store in cache
            cache.set(tenant_id, cache_key, result, ttl=ttl)
            return result
        
        # Return appropriate wrapper
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
