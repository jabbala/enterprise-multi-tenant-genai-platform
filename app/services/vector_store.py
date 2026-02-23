"""Vector store integration with OpenSearch and FAISS"""
import os
import numpy as np
import faiss
from typing import List, Dict, Optional, Tuple
from opensearchpy import OpenSearch, exceptions
from app.core.config import settings
from app.core.resilience import with_retry, with_circuit_breaker, vector_store_circuit_breaker
import structlog

logger = structlog.get_logger(__name__)


class VectorStore:
    """Base class for vector storage"""
    
    async def store_vector(self, tenant_id: str, doc_id: str, vector: List[float], metadata: dict):
        raise NotImplementedError
    
    async def search(self, tenant_id: str, query_vector: List[float], top_k: int = 5) -> List[Dict]:
        raise NotImplementedError
    
    async def delete(self, tenant_id: str, doc_id: str):
        raise NotImplementedError


class FAISSVectorStore(VectorStore):
    """Local FAISS vector store for semantic search"""
    
    def __init__(self):
        self.indexes = {}  # tenant_id -> (index, id_to_doc_mapping)
        self.data_path = settings.faiss_index_path
        os.makedirs(self.data_path, exist_ok=True)
    
    def _get_tenant_index(self, tenant_id: str):
        """Get or create FAISS index for tenant"""
        if tenant_id not in self.indexes:
            index_path = os.path.join(self.data_path, f"{tenant_id}.index")
            
            if os.path.exists(index_path):
                self.indexes[tenant_id] = (
                    faiss.read_index(index_path),
                    {}
                )
            else:
                # Create new index
                index = faiss.IndexFlatL2(settings.faiss_dimension)
                self.indexes[tenant_id] = (index, {})
        
        return self.indexes[tenant_id]
    
    async def store_vector(self, tenant_id: str, doc_id: str, vector: List[float], metadata: dict):
        """Store vector in FAISS index"""
        try:
            index, id_mapping = self._get_tenant_index(tenant_id)
            
            # Convert to numpy array
            vector_array = np.array([vector], dtype=np.float32)
            
            # Add to index
            vector_id = index.ntotal
            index.add(vector_array)
            
            # Store mapping
            id_mapping[vector_id] = {
                "doc_id": doc_id,
                "metadata": metadata,
            }
            
            # Save index
            self._save_tenant_index(tenant_id, index)
            
            logger.debug("faiss_vector_stored", tenant_id=tenant_id, doc_id=doc_id)
        except Exception as e:
            logger.error("faiss_store_failed", tenant_id=tenant_id, error=str(e))
            raise
    
    async def search(self, tenant_id: str, query_vector: List[float], top_k: int = 5) -> List[Dict]:
        """Search in FAISS index"""
        try:
            index, id_mapping = self._get_tenant_index(tenant_id)
            
            if index.ntotal == 0:
                return []
            
            # Convert to numpy array
            query_array = np.array([query_vector], dtype=np.float32)
            
            # Search
            distances, indices = index.search(query_array, min(top_k, index.ntotal))
            
            results = []
            for idx, distance in zip(indices[0], distances[0]):
                if idx in id_mapping:
                    # Convert L2 distance to similarity score
                    similarity = 1 / (1 + distance)
                    results.append({
                        "doc_id": id_mapping[idx]["doc_id"],
                        "score": float(similarity),
                        "metadata": id_mapping[idx]["metadata"],
                    })
            
            logger.debug("faiss_search_completed", tenant_id=tenant_id, results_count=len(results))
            return results
        except Exception as e:
            logger.error("faiss_search_failed", tenant_id=tenant_id, error=str(e))
            return []
    
    def _save_tenant_index(self, tenant_id: str, index):
        """Save FAISS index to disk"""
        index_path = os.path.join(self.data_path, f"{tenant_id}.index")
        faiss.write_index(index, index_path)
    
    async def delete(self, tenant_id: str, doc_id: str):
        """Note: FAISS doesn't support deletion, so we'd need to rebuild"""
        logger.warning("faiss_deletion_not_supported", tenant_id=tenant_id, doc_id=doc_id)


class OpenSearchStore(VectorStore):
    """OpenSearch vector store for hybrid search"""
    
    def __init__(self):
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """Initialize OpenSearch client"""
        try:
            auth = None
            if settings.opensearch_username and settings.opensearch_password:
                auth = (settings.opensearch_username, settings.opensearch_password)
            
            self.client = OpenSearch(
                hosts=[{
                    "host": settings.opensearch_host,
                    "port": settings.opensearch_port
                }],
                http_auth=auth,
                use_ssl=False,
                verify_certs=False,
                ssl_show_warn=False,
            )
            
            self.client.info()
            logger.info("opensearch_connected", host=settings.opensearch_host)
        except Exception as e:
            logger.error("opensearch_connection_failed", error=str(e))
            self.client = None
    
    def _get_index_name(self, tenant_id: str, index_type: str = "documents") -> str:
        """Get tenant-isolated index name"""
        return f"{settings.opensearch_index_prefix}_{tenant_id}_{index_type}"
    
    async def store_vector(self, tenant_id: str, doc_id: str, vector: List[float], metadata: dict):
        """Store document with vector in OpenSearch"""
        if not self.client:
            logger.warning("opensearch_not_available")
            return
        
        try:
            index_name = self._get_index_name(tenant_id)
            
            # Ensure index exists
            self._ensure_index(index_name)
            
            # Store document
            doc = {
                "doc_id": doc_id,
                "vector": vector,
                "metadata": metadata,
                "tenant_id": tenant_id,
            }
            
            self.client.index(
                index=index_name,
                id=doc_id,
                body=doc,
                refresh=True,
            )
            
            logger.debug("opensearch_document_stored", tenant_id=tenant_id, doc_id=doc_id)
        except Exception as e:
            logger.error("opensearch_store_failed", tenant_id=tenant_id, error=str(e))
            raise
    
    async def search(self, tenant_id: str, query_vector: List[float], top_k: int = 5) -> List[Dict]:
        """Search in OpenSearch with vector similarity"""
        if not self.client:
            logger.warning("opensearch_not_available")
            return []
        
        try:
            index_name = self._get_index_name(tenant_id)
            
            query = {
                "size": top_k,
                "query": {
                    "script_score": {
                        "query": {"match_all": {}},
                        "script": {
                            "source": "Math.sqrt(Math.pow(params.query_vector[0] - doc['vector'][0], 2) + Math.pow(params.query_vector[1] - doc['vector'][1], 2))",
                            "params": {
                                "query_vector": query_vector[:2]  # Simplified for demo
                            }
                        }
                    }
                },
                "collapse": {
                    "field": "doc_id.keyword"
                }
            }
            
            response = self.client.search(index=index_name, body=query)
            
            results = []
            for hit in response['hits']['hits']:
                results.append({
                    "doc_id": hit['_source']['doc_id'],
                    "score": hit['_score'],
                    "metadata": hit['_source'].get('metadata', {}),
                })
            
            logger.debug("opensearch_search_completed", tenant_id=tenant_id, results_count=len(results))
            return results
        except exceptions.NotFoundError:
            logger.debug("opensearch_index_not_found", tenant_id=tenant_id)
            return []
        except Exception as e:
            logger.error("opensearch_search_failed", tenant_id=tenant_id, error=str(e))
            return []
    
    async def delete(self, tenant_id: str, doc_id: str):
        """Delete document from OpenSearch"""
        if not self.client:
            return
        
        try:
            index_name = self._get_index_name(tenant_id)
            self.client.delete(index=index_name, id=doc_id)
            logger.debug("opensearch_document_deleted", tenant_id=tenant_id, doc_id=doc_id)
        except Exception as e:
            logger.error("opensearch_delete_failed", tenant_id=tenant_id, error=str(e))
    
    def _ensure_index(self, index_name: str):
        """Create index if it doesn't exist"""
        try:
            if not self.client.indices.exists(index=index_name):
                self.client.indices.create(
                    index=index_name,
                    body={
                        "settings": {
                            "number_of_shards": settings.opensearch_number_of_shards,
                            "number_of_replicas": settings.opensearch_number_of_replicas,
                        },
                        "mappings": {
                            "properties": {
                                "doc_id": {"type": "keyword"},
                                "vector": {
                                    "type": "dense_vector",
                                    "dims": settings.faiss_dimension,
                                    "index": True,
                                    "similarity": "cosine"
                                },
                                "metadata": {"type": "object"},
                                "tenant_id": {"type": "keyword"},
                            }
                        }
                    }
                )
                logger.info("opensearch_index_created", index_name=index_name)
        except Exception as e:
            logger.error("opensearch_index_creation_failed", index_name=index_name, error=str(e))


# Global vector store instances
faiss_store = FAISSVectorStore()
opensearch_store = OpenSearchStore()


class HybridVectorStore:
    """Hybrid vector store using both FAISS and OpenSearch"""
    
    @with_circuit_breaker(vector_store_circuit_breaker, "hybrid")
    async def store(self, tenant_id: str, doc_id: str, vector: List[float], metadata: dict):
        """Store in both FAISS and OpenSearch"""
        try:
            await faiss_store.store_vector(tenant_id, doc_id, vector, metadata)
            await opensearch_store.store_vector(tenant_id, doc_id, vector, metadata)
            logger.debug("hybrid_vector_stored", tenant_id=tenant_id, doc_id=doc_id)
        except Exception as e:
            logger.error("hybrid_store_failed", tenant_id=tenant_id, error=str(e))
            raise
    
    @with_circuit_breaker(vector_store_circuit_breaker, "hybrid")
    async def search(self, tenant_id: str, query_vector: List[float], top_k: int = 5) -> List[Dict]:
        """Search in both stores and merge results"""
        try:
            faiss_results = await faiss_store.search(tenant_id, query_vector, top_k)
            opensearch_results = await opensearch_store.search(tenant_id, query_vector, top_k)
            
            # Merge and deduplicate by doc_id
            merged = {}
            for result in faiss_results + opensearch_results:
                doc_id = result['doc_id']
                if doc_id not in merged:
                    merged[doc_id] = result
                else:
                    # Average scores
                    merged[doc_id]['score'] = (merged[doc_id]['score'] + result['score']) / 2
            
            # Sort by score and return top k
            results = sorted(merged.values(), key=lambda x: x['score'], reverse=True)[:top_k]
            
            logger.debug("hybrid_search_completed", tenant_id=tenant_id, results_count=len(results))
            return results
        except Exception as e:
            logger.error("hybrid_search_failed", tenant_id=tenant_id, error=str(e))
            return []
    
    async def delete(self, tenant_id: str, doc_id: str):
        """Delete from both stores"""
        await faiss_store.delete(tenant_id, doc_id)
        await opensearch_store.delete(tenant_id, doc_id)


hybrid_vector_store = HybridVectorStore()
