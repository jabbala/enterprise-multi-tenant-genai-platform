# Enterprise Multi-Tenant GenAI Platform

A production-ready, scalable RAG-based AI service platform with strict multi-tenant isolation, hybrid semantic+lexical search, and enterprise-grade observability.

## 🎯 Key Features

### Core Capabilities
- **Secure Multi-Tenant Document Retrieval**: Strict tenant isolation at every layer
- **Hybrid Search**: BM25 lexical + vector semantic search with intelligent merging
- **Production-Ready RAG**: Full retrieval-augmented generation pipeline with LLM integration
- **Zero Cross-Tenant Leakage Target**: Multi-layer isolation guarantees
- **Enterprise Observability**: Prometheus metrics, OpenTelemetry tracing, structured logging

### Scaling & Performance
- **Kubernetes-Native**: HPA auto-scaling, stateless architecture, rolling updates
- **P95 Latency Target**: < 2.5 seconds with intelligent caching
- **99.9% Uptime SLA**: Pod disruption budgets, health checks, circuit breakers
- **≥90% Precision@5**: Hybrid retrieval with reranking

### Security & Governance
- **JWT-Based Tenant Resolution**: Token-driven tenant identification
- **PII Automatic Redaction**: Email, SSN, phone, credit cards, IP addresses
- **Cross-Tenant Leakage Prevention**: Multi-layer validation and monitoring
- **Audit Logging**: Complete compliance trail for all operations
- **Rate Limiting**: Per-tenant request quotas

## 🚀 Quick Start

### Local Development

```bash
# Clone and setup
git clone https://github.com/jabbala/enterprise-multi-tenant-genai-platform.git
cd enterprise-multi-tenant-genai-platform
cp .env.example .env

# Start all services
docker-compose up -d

# Test the API
curl -X POST http://localhost:8000/api/query \
  -H "X-Tenant-ID: tenant-001" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is RAG?"}'
```

## 📦 Production Deployment

```bash
# Kubernetes deployment
kubectl apply -f k8s/00-namespace-config.yaml
kubectl apply -f k8s/01-deployment.yaml
kubectl apply -f k8s/02-autoscaling.yaml
kubectl apply -f k8s/03-redis.yaml
kubectl apply -f k8s/04-opensearch.yaml
kubectl apply -f k8s/05-monitoring.yaml
```

## 📚 Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)**: System design and patterns
- **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)**: Production deployment
- **[TESTING_GUIDE.md](TESTING_GUIDE.md)**: Testing strategies

## 🔐 Tenant Isolation

Isolation enforced at 5 layers:
1. Authentication (JWT validation)
2. Request validation (Header matching)
3. Metadata tagging (Index isolation)
4. Vector store filtering (Per-tenant indices)
5. Application validation (Cross-tenant checks)

**Target: 0 cross-tenant leakage incidents**

## 📈 Performance Targets

| Metric | Target |
|--------|--------|
| P95 Latency | < 2.5s |
| Uptime | ≥ 99.9% |
| Error Rate | < 1% |
| Precision@5 | ≥ 90% |

## 🛠️ Technology Stack

- **Framework**: FastAPI 0.104+ | **Server**: Uvicorn
- **Vector Search**: FAISS + OpenSearch | **Cache**: Redis 7
- **Observability**: Prometheus + Jaeger | **Orchestration**: Kubernetes

## 🧪 Load Testing

```bash
locust -f load_test.py --host=http://localhost:8000 \
  -u 100 -r 10 --run-time 5m --headless
```

## 📞 Support

- Issues: Check [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- Logs: `kubectl logs deployment/genai-api -n genai-platform`
- Metrics: http://localhost:9091
- Traces: http://localhost:16686

---

**Status**: Production-Ready | **Version**: 1.0.0 | **Updated**: Feb 2024
