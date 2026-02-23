"""Query route handler with enhanced features"""
from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Optional
import numpy as np
from app.dependencies.tenant import get_current_tenant
from app.models.schemas import QueryRequest, QueryResponse, SourceDocument
from app.services.rag_service import rag_service
from app.core.config import settings
from app.core.metrics import query_latency, query_count
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


def get_query_embedding(query: str) -> list:
    """Generate embedding for query (mock implementation)"""
    # In production, use actual embedding model (e.g., OpenAI, Hugging Face)
    # For now, return mock embedding
    np.random.seed(hash(query) % 2**32)
    return np.random.randn(settings.faiss_dimension).tolist()


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(
    request: QueryRequest,
    tenant_payload=Depends(get_current_tenant),
    x_user_id: Optional[str] = Header(None),
):
    """
    Process a query using the RAG pipeline.
    
    Features:
    - Multi-tenant isolation via JWT
    - Hybrid BM25 + vector search
    - Prompt injection detection
    - PII redaction
    - Cross-tenant leakage prevention
    - Cost tracking
    - Audit logging
    """
    try:
        tenant_id = tenant_payload["tenant_id"]
        user_id = x_user_id or tenant_payload.get("user_id", "unknown")
        
        logger.info(
            "query_received",
            tenant_id=tenant_id,
            user_id=user_id,
            query_length=len(request.query)
        )
        
        # Generate query embedding
        query_embedding = get_query_embedding(request.query)
        
        # Generate response using RAG
        answer, docs = await rag_service.generate_response(
            request.query,
            query_embedding,
            tenant_id,
            user_id
        )
        
        # Transform documents to source format
        sources = [
            SourceDocument(
                content=doc.get("content", ""),
                score=float(doc.get("score", 0))
            )
            for doc in docs
        ]
        
        response = QueryResponse(
            answer=answer,
            sources=sources,
            tenant_id=tenant_id,
        )
        
        logger.info(
            "query_response_sent",
            tenant_id=tenant_id,
            sources_count=len(sources)
        )
        
        return response
    
    except ValueError as e:
        logger.error("query_validation_failed", error=str(e))
        query_count.labels(tenant_id=tenant_payload.get("tenant_id", "unknown"), status="error").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("query_failed", error=str(e))
        query_count.labels(tenant_id=tenant_payload.get("tenant_id", "unknown"), status="error").inc()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/query-status/{query_id}")
async def get_query_status(
    query_id: str,
    tenant_payload=Depends(get_current_tenant),
):
    """Get status of a recent query"""
    tenant_id = tenant_payload["tenant_id"]
    
    # In production, check query cache or database
    logger.debug("query_status_requested", tenant_id=tenant_id, query_id=query_id)
    
    return {
        "query_id": query_id,
        "tenant_id": tenant_id,
        "status": "completed",
    }
