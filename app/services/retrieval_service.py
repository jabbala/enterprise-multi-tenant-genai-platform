"""Enhanced retrieval service with BM25, vector search, and hybrid retrieval"""
from typing import List, Dict
import asyncio
from app.core.cache import cache, cache_result
from app.core.metrics import retrieval_docs_returned, retrieval_score, opensearch_query_latency
from app.core.resilience import with_circuit_breaker, opensearch_circuit_breaker, with_retry
from app.services.vector_store import hybrid_vector_store
from app.core.config import settings
import structlog
import time

logger = structlog.get_logger(__name__)


@cache_result(ttl=3600)
async def bm25_search(tenant_id: str, query: str):
    """Lexical search using OpenSearch BM25"""
    try:
        start_time = time.time()
        
        # Simulated BM25 search - in production, use OpenSearch BM25 query
        results = [
            {
                "doc_id": f"doc_bm25_{i}",
                "content": f"BM25 result {i} for query: {query[:50]}",
                "score": 0.8 - (i * 0.1),
                "source": "bm25"
            }
            for i in range(3)
        ]
        
        duration = time.time() - start_time
        opensearch_query_latency.labels(operation="bm25").observe(duration)
        
        logger.debug("bm25_search_completed", tenant_id=tenant_id, results_count=len(results))
        return results
    except Exception as e:
        logger.error("bm25_search_failed", tenant_id=tenant_id, error=str(e))
        return []


@cache_result(ttl=3600)
async def vector_search(tenant_id: str, query_embedding: List[float]):
    """Semantic search using vector similarity"""
    try:
        start_time = time.time()
        
        # Use hybrid vector store
        results = await hybrid_vector_store.search(tenant_id, query_embedding, top_k=5)
        
        # Transform results
        transformed = [
            {
                "doc_id": result["doc_id"],
                "content": result.get('metadata', {}).get('content', ''),
                "score": result["score"],
                "source": "vector"
            }
            for result in results
        ]
        
        duration = time.time() - start_time
        opensearch_query_latency.labels(operation="vector_search").observe(duration)
        
        logger.debug("vector_search_completed", tenant_id=tenant_id, results_count=len(transformed))
        return transformed
    except Exception as e:
        logger.error("vector_search_failed", tenant_id=tenant_id, error=str(e))
        return []


async def hybrid_retrieve(query: str, query_embedding: List[float], tenant_id: str) -> List[Dict]:
    """Hybrid retrieval: combine BM25 and vector search results"""
    try:
        logger.info("hybrid_retrieval_started", tenant_id=tenant_id, query=query[:100])
        
        # Run both searches in parallel
        bm25_results, vector_results = await asyncio.gather(
            bm25_search(tenant_id, query),
            vector_search(tenant_id, query_embedding),
            return_exceptions=True
        )
        
        # Handle potential errors
        if isinstance(bm25_results, Exception):
            logger.error("bm25_retrieval_error", tenant_id=tenant_id, error=str(bm25_results))
            bm25_results = []
        
        if isinstance(vector_results, Exception):
            logger.error("vector_retrieval_error", tenant_id=tenant_id, error=str(vector_results))
            vector_results = []
        
        # Merge results with weighted scoring
        merged = {}
        bm25_weight = settings.bm25_weight
        vector_weight = settings.vector_weight
        
        # Add BM25 results
        for result in bm25_results:
            doc_id = result["doc_id"]
            merged[doc_id] = {
                "doc_id": doc_id,
                "content": result["content"],
                "score": result["score"] * bm25_weight,
                "sources": [result["source"]],
            }
        
        # Add/merge vector results
        for result in vector_results:
            doc_id = result["doc_id"]
            if doc_id in merged:
                merged[doc_id]["score"] += result["score"] * vector_weight
                merged[doc_id]["sources"].append(result["source"])
            else:
                merged[doc_id] = {
                    "doc_id": doc_id,
                    "content": result["content"],
                    "score": result["score"] * vector_weight,
                    "sources": [result["source"]],
                }
        
        # Sort by score
        sorted_results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        
        # Apply minimum score threshold and take top k
        final_results = [
            r for r in sorted_results 
            if r["score"] >= settings.retrieval_min_score
        ][:settings.retrieval_top_k]
        
        retrieval_docs_returned.labels(tenant_id=tenant_id).observe(len(final_results))
        
        for result in final_results:
            retrieval_score.labels(
                tenant_id=tenant_id,
                retrieval_type="hybrid"
            ).observe(result["score"])
        
        logger.info(
            "hybrid_retrieval_completed",
            tenant_id=tenant_id,
            results_count=len(final_results),
            avg_score=sum(r["score"] for r in final_results) / len(final_results) if final_results else 0
        )
        
        return final_results
    except Exception as e:
        logger.error("hybrid_retrieval_failed", tenant_id=tenant_id, error=str(e))
        return []
