# Operations & SRE Guide

## 1. Error Budget & Burn Rate Policy

### 1.1 Monthly Error Budget

**Service Level Objective (SLO): 99.9% Availability**

```
Monthly budget = (1 - 99.9%) × minutes_per_month
               = 0.001 × 43,800 minutes
               = 43.8 minutes per month
```

**Error Budget Tracking:**
```python
class ErrorBudget:
    monthly_budget = 43.8  # minutes
    
    def remaining_budget(self) -> float:
        """Minutes remaining this month"""
        errors_this_month = get_error_count(start_of_month())
        minutes_spent = errors_this_month / 60  # Convert to minutes
        return self.monthly_budget - minutes_spent
    
    def burn_rate(self, window="1h") -> float:
        """Percentage of budget burned per unit time"""
        errors_in_window = get_error_count(now() - window)
        return (errors_in_window / 60) / (self.monthly_budget / days_in_month())
```

### 1.2 Burn Rate Alerts

| Burn Rate | Alert Severity | Response Time | Escalation |
|-----------|---------------|---------------|-----------|
| 0-2% | Healthy | None | None |
| 2-5% | Warning | 1 hour | Log & monitor |
| 5-10% | High | 30 minutes | Alert ops |
| 10-50% | Critical | 15 minutes | Page on-call |
| 50%+ | Severe | 5 minutes | All hands |

**Alert Implementation:**
```yaml
alert: HighBurnRate
expr: burn_rate_1h > 0.05
for: 15m
annotations:
  summary: "High error budget burn rate ({{ $value }}%)"
  runbook: "https://wiki/incident-response"

alert: CriticalBurnRate
expr: burn_rate_5m > 0.10
for: 5m
annotations:
  summary: "CRITICAL: Error budget burning fast"
  priority: "SEV-1"
```

### 1.3 Incident Classification

**Severity Levels:**

| Level | Condition | Error Rate | Duration | Impact | Response |
|-------|-----------|-----------|----------|--------|----------|
| **SEV-1** | Critical | > 50% (5min) | Any | Complete outage | Page on-call, all hands |
| **SEV-2** | High | 25-50% | > 5min | Major degradation | Alert ops, brief |
| **SEV-3** | Medium | 5-25% | > 15min | Partial impact | Log & escalate |
| **SEV-4** | Low | 1-5% | > 1h | Minor issues | Log & triage |
| **Info** | Notification | < 1% | N/A | No impact | Log only |

**Response Times (SLA):**
```
SEV-1: Initial response < 15 minutes (paged)
SEV-2: Initial response < 1 hour (email alert)
SEV-3: Acknowledged within 4 hours (next shift)
SEV-4: Triaged within 1 business day
```

### 1.4 SRE Policy & Error Budget Usage

**When to Deploy:**
- ✅ Error budget > 50%: Can deploy anytime
- ✅ Error budget 20-50%: Deploy during low-traffic hours
- ⚠️ Error budget 5-20%: No deployments unless critical fix
- ❌ Error budget < 5%: Deployments blocked (FULL HOLD)

**When to Implement Features:**
- High stability features: Always allowed
- Medium-risk features: Only if budget > 30%
- High-risk features: Only if budget > 50%

**Post-Incident Process:**
- All SEV-1/SEV-2: Post-mortem within 48 hours
- Recurrence: Must improve design (not just operate differently)
- Learning: Document in runbooks

---

## 2. Rate Limiting & Quota Management

### 2.1 Multi-Level Rate Limiting

**API Level (Distributed):**
```
Per-Tenant Rate Limit: 10 QPS (default)
   ├─ Sustained: 10 req/sec
   └─ Burst: 20 req/sec for 5 seconds

Redis-backed (distributed across pods):
   ├─ Sliding window: 1-second buckets
   ├─ Tenant isolation: `rate_limit:tenant-001:qps`
   └─ Fallback: In-memory if Redis down
```

**LLM Provider Limits:**
```
OpenAI Rate Limits:
   ├─ GPT-4-turbo: 200 RPM (requests/min)
   ├─ GPT-4: 200 RPM
   └─ GPT-3.5: 1000 RPM

Management:
   ├─ Track usage per model
   ├─ Switch to cheaper model on quota
   ├─ Queue requests if approaching limit
   └─ Alert on 80% utilization
```

### 2.2 Quota Enforcement

**Daily Quota (Redis):**
```python
# Example: 100K queries/day per tenant
async def check_daily_quota(tenant_id: str) -> bool:
    key = f"quota:daily:{tenant_id}"
    today = date.today().isoformat()
    
    # Increment counter (auto-reset at midnight UTC)
    count = redis.incr(f"{key}:{today}")
    
    # Set TTL on first increment of day
    if count == 1:
        redis.expire(f"{key}:{today}", 86400)  # 24 hours
    
    return count <= DAILY_QUOTA_LIMIT
```

**Quota Response:**
```json
{
  "error": "quota_exceeded",
  "message": "Daily quota of 100000 queries reached",
  "retry_after": 86400,
  "quota_reset": "2024-02-24T00:00:00Z",
  "current_usage": 100000,
  "limit": 100000
}
```

### 2.3 Quota Customization

**Tenant Tiers:**
```yaml
# config/pricing.yaml
tiers:
  free:
    qps: 1
    daily_quota: 1000
    monthly_cost: 0
  
  starter:
    qps: 5
    daily_quota: 50000
    monthly_cost: 50
  
  professional:
    qps: 20
    daily_quota: 500000
    monthly_cost: 500
  
  enterprise:
    qps: null              # Unlimited
    daily_quota: null      # Unlimited
    monthly_cost: custom_enterprise
```

**Adjustment API:**
```
POST /admin/v1/tenants/{tenant_id}/quotas
{
  "qps": 15,
  "daily_quota": 200000,
  "effective_date": "2024-03-01"
}
```

---

## 3. Chaos Engineering & Failure Testing

### 3.1 Chaos Test Scenarios

**Scenario 1: Vector DB Outage**
```yaml
name: "Vector Database Total Failure"
duration: 5 minutes
impact: None (fallback to search results)

procedure:
  1. Kill OpenSearch primary node
  2. Observe FAISS local fallback
  3. Verify queries return search results (no LLM)
  4. Restore OpenSearch
  5. Verify recovery automatic

success_criteria:
  - Queries continue within 5 seconds
  - Error rate < 5%
  - No data loss
  - Recovery automatic (no manual intervention)
```

**Scenario 2: LLM Provider Outage**
```yaml
name: "LLM Service Unavailable"
duration: 1 hour
impact: Graceful degradation expected

procedure:
  1. Block all OpenAI API calls (tc/iptables)
  2. Observe circuit breaker behavior
  3. Verify fallback to Tier 4/5 (cached + search)
  4. Monitor response times
  5. Restore OpenAI connectivity
  6. Verify recovery

success_criteria:
  - Circuit breaks within 30 seconds
  - P95 latency < 3 seconds (degraded but functional)
  - Error rate < 2% (user perceives as slow not broken)
  - Fallback responses helpful (not just empty)
```

**Scenario 3: Redis Cache Complete Failure**
```yaml
name: "Cache System Failure"
duration: 30 minutes
impact: Performance degradation (safe)

procedure:
  1. Stop Redis pod
  2. Observe direct cache bypass
  3. Monitor latency increase (expected 2-3x)
  4. Track OpenSearch/FAISS load increase
  5. Restart Redis
  6. Verify cache rebuild (warm-up)

success_criteria:
  - No queries rejected or failed
  - Latency < 5 seconds (acceptable degraded)
  - No data corruption
  - Cache warm-up within 10 minutes
```

**Scenario 4: Kubernetes Node Failure**
```yaml
name: "Node Outage (3/10 nodes)"
duration: 10 minutes
impact: Handled by auto-scaling

procedure:
  1. Corddon 3 nodes (drain workload)
  2. Pod disruption budget should prevent all eviction
  3. Observe graceful rescheduling
  4. Monitor request routing to remaining nodes
  5. Un-cordden nodes
  6. Verify recovery

success_criteria:
  - Zero queries dropped (PDB protection)
  - Auto-scale up: scale to max capacity
  - Latency affected < 20% (load distribution)
  - Recovery automatic when nodes return
```

### 3.2 Execution & Monitoring

**Test Schedule:**
- **Monthly**: Production-like staging environment
- **Quarterly**: Limited production test (off-hours, small % traffic)
- **On-demand**: After major changes

**Execution Runbook:**
```bash
#!/bin/bash
# Pre-flight checks
kubectl get nodes -o wide              # Verify cluster health
kubectl get pdb                         # Verify PDBs exist
kubectl get hpa                         # Verify auto-scaling

# Run chaos
kubectl apply -f chaos/scenario-1.yaml

# Monitor
watch kubectl get pods
watch -n 1 'curl localhost:8000/metrics | grep queries'

# Rollback on failure
kubectl delete -f chaos/scenario-1.yaml
```

**Success Validation:**
```yaml
metrics_to_validate:
  - queries_total: Should continue incrementing
  - query_duration_seconds: P95 < threshold
  - errors_total: < 2% of baseline
  - circuit_breaker_state: Should transition to open→half-open
  - active_requests: Should distribute across pods
```

---

## 4. Runbook Examples

### 4.1 Response Runbook: High Latency

**Detection:**
- Prometheus alert: `query_duration_p95_seconds > 5`
- Page on-call within 30 seconds

**Immediate Actions (< 5 minutes):**
```bash
# Check Kubernetes metrics
kubectl top pods -n genai
kubectl top nodes

# Check service health
curl https://api.genai.internal/health/detailed
curl https://api.genai.internal/metrics | grep query_duration

# Check for errors
kubectl logs -l app=genai-api --tail=100 | grep ERROR
```

**Diagnosis (5-15 minutes):**
- ✅ CPU/Memory usage normal?
- ✅ Database connections healthy?
- ✅ OpenSearch cluster healthy? `curl https://opensearch:9200/_cluster/health`
- ✅ Redis responding? `redis-cli ping`
- ✅ Specific endpoint slow or all endpoints?

**Remediation:**
```bash
# If OpenSearch slow:
  - Check shard count and rebalance
  - Clear old indices (ILM)
  - Consider scale-up

# If Redis slow:
  - Check memory usage: `redis-cli info memory`
  - Evict expired keys: `redis-cli memory evict-policies`
  - Scale replicas

# If pod resource exhausted:
  - Scale up replicas immediately:
    kubectl scale deployment genai-api --replicas=10
  - Update HPA min:
    kubectl patch hpa genai-hpa -p '{"spec":{"minReplicas":5}}'
```

### 4.2 Recovery Runbook: Complete Outage

**Scenario: API completely down (no pods running)**

**Escalation:**
- Page on-call (SEV-1)
- Slack: #incidents channel
- Status page: "Investigating"

**Recovery Steps (< 5 minutes):**
```bash
# 1. Verify no pods
kubectl get pods -n genai

# 2. Try immediate restart
kubectl rollout restart deployment/genai-api

# 3. Check deployment status
kubectl describe deployment genai-api
kubectl logs -n genai deployment/genai-api

# 4. If stuck pending: Check for resource issues
kubectl describe nodes | grep -A 5 "Allocatable"
kubectl top nodes
```

**If local restart fails:**
```bash
# 5. Check external dependencies
kubectl exec -it redis-0 -- redis-cli ping
kubectl exec -it opensearch-0 -- curl localhost:9200

# 6. If dependency down: Scale down GenAI to 0, fix dependency, restart
kubectl scale deployment genai-api --replicas=0
# Fix dependency...
kubectl scale deployment genai-api --replicas=2

# 7. Monitor recovery
kubectl logs -f deployment/genai-api
```

**Communication (Continuous):**
- Update status page every 15 minutes
- Incident war room (Zoom)
- Post-mortem within 4 hours (if > 1 hour outage)

---

## 5. Deployment Strategy

### 5.1 Rolling Update Process

**Configuration:**
```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1        # One extra pod during update
      maxUnavailable: 0  # Never take pods down
  minReadySeconds: 30    # Wait 30s before marking ready
```

**Timeline:**
```
T0:  New code deployed → Pod 1 starts (now 3 pods)
T30: Pod 1 passes health checks → Pod 2 starts
T60: Pod 2 passes health checks → Pod 3 starts
T90: Pod 3 passes health checks → Pod 1 (old) terminates
     Pod 4 (old) starts terminating gracefully (drain)
     Pod 5 (old) terminates (now 2 new, 1 old)
T120: Last old pod drained → All pods new
```

**Rollback Process:**
```bash
# If something goes wrong:
kubectl rollout undo deployment/genai-api
kubectl rollout status deployment/genai-api

# Faster: Revert in registry
docker tag registry/genai:buggy-v1.2.3 registry/genai:v1.2.2
kubectl set image deployment/genai-api genai=registry/genai:v1.2.2
```

### 5.2 Canary Deployment

**For high-risk changes:**
```yaml
# Deploy to 10% of traffic first
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: genai-api
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: genai-api
  progressDeadlineSeconds: 600
  service:
    port: 8000
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50   # Max 50% traffic to canary
    stepWeight: 10  # Increase by 10% every step
    metrics:
    - name: error_rate
      thresholdRange:
        max: 5  # Fail if > 5% errors
    - name: latency
      thresholdRange:
        max: 500  # Fail if p99 > 500ms
```

---

## 6. Glossary

- **SLO**: Service Level Objective (target uptime)
- **SLA**: Service Level Agreement (contract uptime)
- **Error Budget**: Allowed downtime per month
- **Burn Rate**: How fast error budget is consumed
- **MTTR**: Mean Time To Recovery
- **RCA**: Root Cause Analysis
- **Post-Mortem**: Incident review meeting
- **PDB**: Pod Disruption Budget (Kubernetes protection)
- **Graceful Shutdown**: Complete in-flight requests before terminating

