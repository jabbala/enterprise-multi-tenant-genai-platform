"""Enhanced RAG service with async processing, cost tracking, and audit logging"""
import asyncio
import time
from typing import List, Dict, Tuple
from app.services.retrieval_service import hybrid_retrieve
from app.services.governance_service import validate_prompt, redact_pii, check_cross_tenant_leakage
from app.core.cache import cache
from app.core.config import settings
from app.core.metrics import query_latency, llm_latency, llm_tokens_used, query_count
from app.core.resilience import with_circuit_breaker, llm_circuit_breaker, with_retry
from app.core.logging_config import audit_logger
import structlog
import httpx

logger = structlog.get_logger(__name__)


class RAGService:
    """Production-grade RAG service with all enterprise features"""
    
    def __init__(self):
        self.llm_client = None
        self.query_cache = {}
    
    async def initialize(self):
        """Initialize RAG service"""
        logger.info("rag_service_initializing")
    
    @with_circuit_breaker(llm_circuit_breaker)
    @with_retry(max_attempts=3, wait_multiplier=1, max_wait=10)
    async def _call_llm(self, prompt: str, tenant_id: str) -> Tuple[str, int]:
        """Call LLM with resilience patterns"""
        try:
            start_time = time.time()
            
            # Mock LLM call - in production, call OpenAI or similar
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    settings.llm_provider_url,
                    json={"prompt": prompt},
                    timeout=settings.llm_timeout,
                    headers={"X-Tenant-ID": tenant_id}
                )
            
            if response.status_code != 200:
                raise Exception(f"LLM API error: {response.status_code}")
            
            result = response.json()
            answer = result.get("answer", f"Answer based on context: {prompt[:100]}")
            tokens = result.get("tokens_used", len(prompt.split()))
            
            duration = time.time() - start_time
            llm_latency.labels(tenant_id=tenant_id).observe(duration)
            llm_tokens_used.labels(tenant_id=tenant_id, token_type="all").inc(tokens)
            
            # Track cost
            cost = (tokens / 1000) * settings.llm_cost_per_1k_tokens
            audit_logger.log_cost_event(
                tenant_id,
                "llm_inference",
                cost,
                {"tokens": tokens, "model": settings.llm_model}
            )
            
            logger.debug("llm_call_success", tenant_id=tenant_id, tokens=tokens, duration=duration)
            return answer, tokens
        except Exception as e:
            logger.error("llm_call_failed", tenant_id=tenant_id, error=str(e))
            raise
    
    async def generate_response(
        self,
        query: str,
        query_embedding: List[float],
        tenant_id: str,
        user_id: str = None
    ) -> Tuple[str, List[Dict]]:
        """Generate response using RAG pipeline"""
        start_time = time.time()
        query_id = f"{tenant_id}_{int(start_time * 1000)}"
        
        try:
            logger.info(
                "rag_generation_started",
                query_id=query_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            
            # Audit: Log query execution
            audit_logger.log_query(tenant_id, user_id or "unknown", query, "started")
            
            # Step 1: Validate prompt (check for injections)
            validate_prompt(query)
            
            # Step 2: Retrieval (hybrid BM25 + vector search)
            docs = await hybrid_retrieve(query, query_embedding, tenant_id)
            
            if not docs:
                logger.warning("no_documents_retrieved", query_id=query_id, tenant_id=tenant_id)
                audit_logger.log_query(tenant_id, user_id or "unknown", query, "no_docs")
                return "No relevant documents found for your query.", []
            
            # Step 3: Check cross-tenant leakage
            check_cross_tenant_leakage(docs, tenant_id)
            
            # Step 4: Build context
            context = "\n".join([f"[{doc['doc_id']}] {doc['content']}" for doc in docs])
            
            # Step 5: Redact PII
            redacted_context = redact_pii(context)
            
            # Step 6: Call LLM
            prompt = f"""Based on the following documents, answer the user's question.

Documents:
{redacted_context}

Question: {query}

Answer:"""
            
            answer, tokens = await self._call_llm(prompt, tenant_id)
            
            # Step 7: Redact PII from answer
            answer = redact_pii(answer)
            
            # Step 8: Add citations
            citations = self._generate_citations(docs)
            answer = f"{answer}\n\nCitations:\n{citations}"
            
            # Calculate latency
            duration = time.time() - start_time
            query_latency.labels(tenant_id=tenant_id).observe(duration)
            query_count.labels(tenant_id=tenant_id, status="success").inc()
            
            # Track total cost
            retrieval_cost = settings.retrieval_cost_per_query
            audit_logger.log_cost_event(
                tenant_id,
                "total_query",
                retrieval_cost,
                {"docs_retrieved": len(docs), "query_id": query_id}
            )
            
            # Audit: Log successful query
            audit_logger.log_query(tenant_id, user_id or "unknown", query, "completed")
            
            # Log performance
            logger.info(
                "rag_generation_completed",
                query_id=query_id,
                tenant_id=tenant_id,
                duration=duration,
                docs_retrieved=len(docs),
                tokens=tokens,
            )
            
            # Check latency SLA
            if duration > (settings.target_latency_p95_ms / 1000):
                logger.warning(
                    "latency_sla_violated",
                    query_id=query_id,
                    duration=duration,
                    threshold=settings.target_latency_p95_ms / 1000
                )
            
            return answer, docs
        
        except Exception as e:
            logger.error(
                "rag_generation_failed",
                query_id=query_id,
                tenant_id=tenant_id,
                error=str(e)
            )
            query_count.labels(tenant_id=tenant_id, status="error").inc()
            audit_logger.log_query(tenant_id, user_id or "unknown", query, "failed")
            raise
    
    def _generate_citations(self, docs: List[Dict]) -> str:
        """Generate citations for retrieved documents"""
        citations = []
        for i, doc in enumerate(docs, 1):
            citations.append(f"[{i}] {doc['doc_id']} (Score: {doc['score']:.2f})")
        return "\n".join(citations)


# Global RAG service instance
rag_service = RAGService()


async def generate_response(query: str, query_embedding: List[float], tenant_id: str) -> Tuple[str, List[Dict]]:
    """Wrapper function for backward compatibility"""
    return await rag_service.generate_response(query, query_embedding, tenant_id)
