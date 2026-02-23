"""OpenTelemetry tracing setup for distributed tracing"""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)


def init_tracing():
    """Initialize OpenTelemetry tracing"""
    if not settings.opentelemetry_enabled:
        logger.info("opentelemetry_disabled")
        return None
    
    try:
        # Create Jaeger exporter
        jaeger_exporter = JaegerExporter(
            agent_host_name=settings.jaeger_host,
            agent_port=settings.jaeger_port,
        )
        
        # Create resource
        resource = Resource.create({
            "service.name": settings.app_name,
            "environment": settings.environment,
        })
        
        # Create TracerProvider
        trace_provider = TracerProvider(resource=resource)
        trace_provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
        
        # Set global tracer provider
        trace.set_tracer_provider(trace_provider)
        
        logger.info(
            "tracing_initialized",
            jaeger_host=settings.jaeger_host,
            jaeger_port=settings.jaeger_port
        )
        
        return trace_provider
    except Exception as e:
        logger.error("tracing_initialization_failed", error=str(e))
        return None


def instrument_fastapi(app):
    """Instrument FastAPI application"""
    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.info("fastapi_instrumented")
    except Exception as e:
        logger.error("fastapi_instrumentation_failed", error=str(e))


def instrument_redis():
    """Instrument Redis client"""
    try:
        RedisInstrumentor().instrument()
        logger.info("redis_instrumented")
    except Exception as e:
        logger.error("redis_instrumentation_failed", error=str(e))


def get_tracer(name: str):
    """Get tracer instance"""
    return trace.get_tracer(name)


def create_span(name: str, attributes: dict = None):
    """Create a new span"""
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        return span
