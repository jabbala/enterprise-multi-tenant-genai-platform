# Enterprise Multi-Tenant GenAI Platform - Deployment Guide

## Overview

This guide provides comprehensive instructions for deploying the Enterprise Multi-Tenant GenAI Platform in production environments with Kubernetes.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Load Balancer / Ingress                   │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         │                               │
    ┌────▼────┐                    ┌────▼──────┐
    │  GenAI  │◄─────────┐         │  Metrics  │
    │   API   │          │         │ Scraping  │
    │  Pods   │◄─────┐   │         └────┬──────┘
    └────┬────┘      │   │              │
         │           │   │         ┌────▼────────┐
         │      ┌────▼───▼──┐      │ Prometheus  │
         │      │   Redis   │◄─────┤  Alerting   │
         │      │ (Caching) │      │  Grafana    │
         │      └────┬──────┘      └─────────────┘
         │           │
    ┌────▼───────────▼────────┐
    │   OpenSearch Cluster    │
    │  (Hybrid Search Index)  │
    └─────────────────────────┘
```

## Prerequisites

- Kubernetes 1.25+
- kubectl configured
- Docker registry access
- 5+ worker nodes (2 CPUs, 4GB RAM each for production)
- Persistent volumes provisioner (EBS, GCE, Azure Disks, etc.)

## Deployment Steps

### 1. Build Docker Image

```bash
docker build -t genai-platform:1.0.0 .
docker push <your-registry>/genai-platform:1.0.0
```

Update image reference in `k8s/01-deployment.yaml` if needed.

### 2. Create Kubernetes Namespace and Secrets

```bash
kubectl apply -f k8s/00-namespace-config.yaml

# Update secrets with production values
kubectl edit secret genai-secrets -n genai-platform
```

**Important**: Change the following in production:
- `JWT_SECRET`: Strong random string
- `LLM_API_KEY`: Your LLM provider API key
- `OPENSEARCH_PASSWORD`: Strong password
- `DB_PASSWORD`: Strong password

### 3. Deploy Infrastructure Components

Deploy in order:

```bash
# Deploy Redis for caching
kubectl apply -f k8s/03-redis.yaml

# Deploy OpenSearch cluster (wait 2-3 minutes)
kubectl apply -f k8s/04-opensearch.yaml

# Check OpenSearch status
kubectl rollout status statefulset opensearch -n genai-platform

# Deploy monitoring (Jaeger, Prometheus)
kubectl apply -f k8s/05-monitoring.yaml
```

### 4. Deploy Application

```bash
# Deploy RAG API and autoscaling
kubectl apply -f k8s/01-deployment.yaml
kubectl apply -f k8s/02-autoscaling.yaml

# Check rollout status
kubectl rollout status deployment genai-api -n genai-platform
```

### 5. Verify Deployment

```bash
# Check all pods are running
kubectl get pods -n genai-platform

# Check services
kubectl get svc -n genai-platform

# Get API service IP
kubectl get svc genai-api -n genai-platform -o wide
```

## Configuration Management

### Environment Variables

All environment variables are managed via ConfigMap and Secrets:

- **ConfigMap** (`genai-config`):
  - Non-sensitive configuration
  - Application behavior settings
  - Feature flags

- **Secret** (`genai-secrets`):
  - API keys
  - Passwords
  - Private configuration

### Updating Configuration

```bash
# Update ConfigMap
kubectl edit configmap genai-config -n genai-platform

# Update Secrets
kubectl edit secret genai-secrets -n genai-platform

# Restart pods to apply changes
kubectl rollout restart deployment genai-api -n genai-platform
```

## Scaling Configuration

### Horizontal Pod Autoscaler (HPA)

The HPA automatically scales RAG API pods based on:
- CPU utilization (target: 70%)
- Memory utilization (target: 80%)
- Query latency (target: 2.5s P95)

Scaling limits:
- Minimum: 2 pods
- Maximum: 20 pods

```bash
# View HPA status
kubectl get hpa -n genai-platform

# Edit HPA
kubectl edit hpa genai-api-hpa -n genai-platform
```

### Manual Scaling

```bash
# Scale to specific number of replicas
kubectl scale deployment genai-api --replicas=5 -n genai-platform
```

## Observability

### Metrics Collection

Prometheus automatically scrapes metrics from:
- GenAI API: `/metrics` endpoint (port 9090)
- Interval: 30 seconds

### Key Metrics

- `genai_queries_total`: Total queries by status
- `genai_query_latency_seconds`: Query latency histogram
- `genai_circuit_breaker_state`: Circuit breaker state
- `genai_cross_tenant_leakage_attempts_total`: Security violations
- `genai_cost_total_dollars`: Cost tracking by tenant

### Alerts

Critical alerts are configured in `02-autoscaling.yaml`:

- **HighQueryLatency**: P95 latency > 2.5s
- **HighErrorRate**: Error rate > 1%
- **CircuitBreakerOpen**: Service circuit breaker open
- **CrossTenantLeakageAttempt**: Security violation
- **PodDown**: Pod not responding

Configure alert recipients in Prometheus:

```bash
kubectl edit prometheus -n genai-platform
```

### Accessing Dashboards

1. **Grafana** (optional, install separately):
   ```bash
   kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
   ```

2. **Jaeger UI** (Distributed Tracing):
   ```bash
   kubectl port-forward -n genai-platform svc/jaeger 16686:16686
   # Visit http://localhost:16686
   ```

3. **Prometheus UI**:
   ```bash
   kubectl port-forward -n monitoring svc/prometheus-k8s 9090:9090
   # Visit http://localhost:9090
   ```

## Load Testing

### Local Development Testing

```bash
pip install locust
locust -f load_test.py --host=http://localhost:8000
```

### Kubernetes Load Testing

```bash
# Port-forward the service
kubectl port-forward -n genai-platform svc/genai-api 8000:8000

# Run load test
locust -f load_test.py --host=http://localhost:8000 -u 100 -r 10
```

Test scenarios verify:
- No cross-tenant data leakage
- Stable latency under load (target: 2.5s P95)
- Error rate < 1%
- Autoscaling effectiveness

## Logging

### View Logs

```bash
# View recent logs from a pod
kubectl logs -n genai-platform deployment/genai-api --tail=100 -f

# View logs from specific pod
kubectl logs -n genai-platform genai-api-xyz123

# View previous logs (after crash)
kubectl logs -n genai-platform genai-api-xyz123 --previous
```

### Structured Logging

All logs are in JSON format for easy parsing:

```json
{
  "timestamp": "2024-02-23T12:34:56.789Z",
  "level": "INFO",
  "logger": "genai_service",
  "event": "query_completed",
  "tenant_id": "tenant-001",
  "user_id": "user-a1",
  "duration": 1.234,
  "docs_retrieved": 5
}
```

## Upgrading

### Rolling Update

```bash
# Update image
kubectl set image deployment/genai-api genai-api=<registry>/genai-platform:2.0.0 -n genai-platform

# Monitor rollout
kubectl rollout status deployment/genai-api -n genai-platform

# Rollback if needed
kubectl rollout undo deployment/genai-api -n genai-platform
```

## Security

### Security Context

All pods run with:
- Non-root user (UID 1000)
- No privilege escalation
- Dropped all capabilities
- Read-only root filesystem (where possible)

### RBAC

Service accounts have minimal permissions:
- Read ConfigMaps and Secrets
- List pods in namespace

### Network Policies

Network policies restrict traffic:
- Ingress: Only on defined ports
- Egress: Only to required services

## Backup and Disaster Recovery

### Redis Backup

```bash
# Enable Redis persistence (configured by default)
# Manual backup:
kubectl exec -n genai-platform redis-0 -- redis-cli BGSAVE

# Export backup
kubectl cp genai-platform/redis-0:/data/dump.rdb ./dump.rdb
```

### OpenSearch Backup

```bash
# Create snapshot repository
kubectl exec -n genai-platform opensearch-0 -- \
  curl -X PUT "localhost:9200/_snapshot/backup" \
  -H 'Content-Type: application/json' \
  -d '{"type": "fs", "settings": {"location": "/mnt/backups"}}'

# Create snapshot
kubectl exec -n genai-platform opensearch-0 -- \
  curl -X PUT "localhost:9200/_snapshot/backup/snapshot-1"
```

### Full Cluster Backup

```bash
# Backup all resources
kubectl get all -n genai-platform -o yaml > genai-platform-backup.yaml

# Restore from backup
kubectl apply -f genai-platform-backup.yaml
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl describe pod genai-api-xxx -n genai-platform

# View pod events
kubectl get events -n genai-platform --sort-by='.lastTimestamp'

# Check init containers
kubectl logs genai-api-xxx -n genai-platform -c wait-for-redis
```

### High Latency

1. Check Prometheus metrics:
   ```bash
   kubectl port-forward -n monitoring svc/prometheus-k8s 9090:9090
   ```

2. Analyze HPA status:
   ```bash
   kubectl describe hpa genai-api-hpa -n genai-platform
   ```

3. Check resource constraints:
   ```bash
   kubectl top pods -n genai-platform
   kubectl top nodes
   ```

### Cross-Tenant Leakage

Monitor security alerts:
```bash
kubectl logs -n genai-platform deployment/genai-api \
  | grep cross_tenant
```

Check OpenSearch queries:
```bash
kubectl port-forward -n genai-platform svc/opensearch 9200:9200
# Query: GET /genai_*/documents/_search?q=tenant_id
```

## Performance Tuning

### JVM Tuning for OpenSearch

Edit `k8s/04-opensearch.yaml`:
```yaml
env:
  - name: OPENSEARCH_JAVA_OPTS
    value: "-Xms2g -Xmx2g"  # Adjust based on node size
```

### Connection Pool Tuning

Update in `app/core/config.py`:
```python
redis_max_connections: int = 50  # Adjust based on load
```

### Cache TTL

Configure in `app/core/config.py`:
```python
redis_ttl_seconds: int = 3600  # 1 hour, adjust as needed
```

## Compliance and Audit

### Audit Logging

All data access is logged with:
- Tenant ID
- User ID
- Action performed
- Timestamp
- IP address

Logs stored in JSON format for compliance tools:
```bash
kubectl logs -n genai-platform deployment/genai-api \
  | grep "audit" | jq .
```

### Cost Tracking

Monitor costs per tenant:
```bash
kubectl logs -n genai-platform deployment/genai-api \
  | grep "cost_event" | jq '.amount'
```

## Support and Troubleshooting

For issues, check:
1. Application logs: `kubectl logs`
2. Pod events: `kubectl describe pod`
3. Prometheus metrics: `/metrics` endpoint
4. Jaeger traces: http://localhost:16686

## Additional Resources

- Kubernetes Documentation: https://kubernetes.io/docs/
- OpenSearch Documentation: https://opensearch.org/docs/
- Prometheus Documentation: https://prometheus.io/docs/
- Jaeger Documentation: https://www.jaegertracing.io/docs/
