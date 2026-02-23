"""Enterprise Multi-Tenant GenAI Platform - Main Application"""
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import asyncio

# Import routes
from app.routes import query, health

# Import observability
from app.core.logging_config import configure_logging, get_logger
from app.core.metrics import get_registry
from app.core.tracing import init_tracing, instrument_fastapi, instrument_redis
from app.core.cache import cache
from app.services.rag_service import rag_service

# Import middleware
from app.middleware import (
    CostTrackingMiddleware,
    MetricsMiddleware,
    SecurityMiddleware,
    AuditLoggingMiddleware,
    RateLimitMiddleware,
)

# Configure logging
configure_logging()
logger = get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Enterprise Multi-Tenant GenAI Platform",
    description="Scalable, secure RAG-based AI service with multi-tenant isolation",
    version="1.0.0",
)

# Initialize tracing
logger.info("initializing_application")
init_tracing()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add observability and security middleware (order matters)
app.add_middleware(CostTrackingMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(SecurityMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=100)

# Instrument FastAPI
instrument_fastapi(app)
instrument_redis()

# Include routers
app.include_router(query.router, prefix="/api", tags=["Query"])
app.include_router(health.router, tags=["Health"])


@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    logger.info("application_startup")
    
    try:
        # Initialize Redis cache
        cache.connect()
        logger.info("redis_cache_initialized")
    except Exception as e:
        logger.warning("redis_cache_initialization_failed", error=str(e))
    
    # Initialize RAG service
    await rag_service.initialize()
    logger.info("rag_service_initialized")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("application_shutdown")
    
    try:
        cache.disconnect()
        logger.info("redis_cache_closed")
    except Exception as e:
        logger.warning("redis_cache_shutdown_error", error=str(e))


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(
        content=generate_latest(get_registry()),
        media_type=CONTENT_TYPE_LATEST
    )


@app.get("/health/detailed")
async def detailed_health():
    """Detailed health check"""
    return {
        "status": "healthy",
        "components": {
            "api": "healthy",
            "redis": "checking...",
            "vector_store": "checking...",
        }
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Enterprise Multi-Tenant GenAI Platform",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "health": "/health",
            "health_detailed": "/health/detailed",
            "metrics": "/metrics",
            "query": "/api/query",
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_config=None,  # Use our custom logging
    )
