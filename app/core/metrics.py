"""Prometheus metrics for observability"""
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry
import time
from functools import wraps
from typing import Callable
import structlog

logger = structlog.get_logger(__name__)

# Create custom registry
registry = CollectorRegistry()

# Query metrics
query_count = Counter(
    'genai_queries_total',
    'Total number of queries',
    ['tenant_id', 'status'],
    registry=registry
)

query_latency = Histogram(
    'genai_query_latency_seconds',
    'Query latency in seconds',
    ['tenant_id'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=registry
)

retrieval_docs_returned = Histogram(
    'genai_retrieval_docs_count',
    'Number of documents retrieved',
    ['tenant_id'],
    buckets=(1, 3, 5, 10, 20),
    registry=registry
)

retrieval_score = Histogram(
    'genai_retrieval_score',
    'Average retrieval score',
    ['tenant_id', 'retrieval_type'],
    buckets=(0.1, 0.3, 0.5, 0.7, 0.9),
    registry=registry
)

# Cache metrics
cache_hits = Counter(
    'genai_cache_hits_total',
    'Total cache hits',
    ['tenant_id', 'cache_type'],
    registry=registry
)

cache_misses = Counter(
    'genai_cache_misses_total',
    'Total cache misses',
    ['tenant_id', 'cache_type'],
    registry=registry
)

cache_latency = Histogram(
    'genai_cache_latency_seconds',
    'Cache operation latency',
    ['operation', 'cache_type'],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1),
    registry=registry
)

# Error metrics
error_count = Counter(
    'genai_errors_total',
    'Total errors by type',
    ['tenant_id', 'error_type'],
    registry=registry
)

# Circuit breaker metrics
circuit_breaker_state = Gauge(
    'genai_circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=open, 2=half-open)',
    ['service'],
    registry=registry
)

# Cost tracking metrics
cost_total = Counter(
    'genai_cost_total_dollars',
    'Total cost in dollars',
    ['tenant_id', 'cost_type'],
    registry=registry
)

# LLM metrics
llm_tokens_used = Counter(
    'genai_llm_tokens_total',
    'Total LLM tokens used',
    ['tenant_id', 'token_type'],
    registry=registry
)

llm_latency = Histogram(
    'genai_llm_latency_seconds',
    'LLM API latency',
    ['tenant_id'],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0),
    registry=registry
)

# Active requests
active_requests = Gauge(
    'genai_active_requests',
    'Number of active requests',
    ['tenant_id', 'endpoint'],
    registry=registry
)

# Vector store metrics
vector_store_query_latency = Histogram(
    'genai_vector_store_latency_seconds',
    'Vector store query latency',
    ['operation'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0),
    registry=registry
)

# OpenSearch metrics
opensearch_index_size = Gauge(
    'genai_opensearch_index_bytes',
    'OpenSearch index size in bytes',
    ['tenant_id', 'index_name'],
    registry=registry
)

opensearch_query_latency = Histogram(
    'genai_opensearch_latency_seconds',
    'OpenSearch query latency',
    ['operation'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0),
    registry=registry
)

# Tenant isolation metrics
cross_tenant_leakage_attempts = Counter(
    'genai_cross_tenant_leakage_attempts',
    'Suspected cross-tenant leakage attempts blocked',
    ['source'],
    registry=registry
)

# PII redaction metrics
pii_redactions_performed = Counter(
    'genai_pii_redactions_total',
    'Total PII redactions performed',
    ['tenant_id', 'pii_type'],
    registry=registry
)


def track_latency(metric: Histogram, labels: dict = None):
    """Decorator to track function latency"""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def track_counter(metric: Counter, labels: dict):
    """Decorator to track function calls"""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                metric.labels(**labels).inc()
                return result
            except Exception as e:
                error_labels = {**labels, 'status': 'error'}
                metric.labels(**error_labels).inc()
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                metric.labels(**labels).inc()
                return result
            except Exception as e:
                error_labels = {**labels, 'status': 'error'}
                metric.labels(**error_labels).inc()
                raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def get_registry():
    """Get Prometheus registry"""
    return registry
