# Disaster Recovery & Multi-Region Strategy

## 1. Architecture Overview

### 1.1 Active-Passive Failover Model

```
NORMAL OPERATION (Primary Region)
┌──────────────────────────────────┐
│         US-EAST (Primary)        │
│  ┌────────────────────────────┐  │
│  │   GenAI API Pods (10)      │  │
│  │   - Handling: 100% traffic │  │
│  │   - Active: Yes            │  │
│  └────────────────────────────┘  │
│  ┌────────────────────────────┐  │
│  │   Redis (master)           │  │
│  │   OpenSearch (3 nodes)     │  │
│  └────────────────────────────┘  │
└──────────────────────────────────┘
              │
              ├─→ DNS Points to: us-east.api.platform
              │
              └─→ Replication
EU-CENTRAL (Secondary - Hot Standby)
┌──────────────────────────────────┐
│       EU-CENTRAL (Standby)       │
│  ┌────────────────────────────┐  │
│  │   GenAI API Pods (2)       │  │
│  │   - Handling: 0% traffic   │  │
│  │   - Active: Monitoring only│  │
│  └────────────────────────────┘  │
│  ┌────────────────────────────┐  │
│  │   Redis (replica)          │  │
│  │   OpenSearch (1 replica)   │  │
│  └────────────────────────────┘  │
└──────────────────────────────────┘

FAILOVER EVENT (Primary Region Down)
                  ↓
         (Automatic Detection)
                  ↓
EU-CENTRAL promoted to PRIMARY in:
  - DNS: eu-central.api.platform
  - API pods: Scale 2→10 replicas
  - Connections: Accept write traffic
  - Duration: ~2-5 minutes
```

### 1.2 Multi-Region Configuration

**Regions Supported:**

| Region | Code | Primary | Backup | Failover | Use Case |
|--------|------|---------|--------|----------|----------|
| **US East** | us-east-1 | ✅ Yes | ❌ | 0 min | Main workload |
| **EU Central** | eu-central | ✅ Yes | ✅ | ~5 min | Failover + GDPR |
| **APAC** | ap-sg | ❌ | ✅ | ~10 min | Edge caching (future) |

---

## 2. Failover Mechanism

### 2.1 Health Check & Detection

**Health Check Configuration:**
```yaml
# Kubernetes liveness probe
livenessProbe:
  httpGet:
    path: /health/detailed
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3
  
# Result: Pod marked unhealthy after 15s (3 × 5s)
```

**Cluster-Level Health Check:**
```python
async def cluster_health_check():
    """Check every 30 seconds if primary is healthy"""
    primary_health = await check_region(REGION_PRIMARY)
    
    if not primary_health["api_available"]:
        return await trigger_failover()
    
    if primary_health["error_rate"] > 0.50:  # > 50% errors
        return await trigger_failover()
    
    if primary_health["latency_p95"] > 10_000:  # > 10s
        return await trigger_failover()
```

### 2.2 Automatic Failover Procedure

**Timeline:**

| T | Event | Duration | Action |
|---|-------|----------|--------|
| T0 | Primary failure detected | - | 3 health checks fail (15s) |
| T15 | Failover decision made | - | SRE receives alert |
| T30 | DNS update starts | ~60s | Route53 TTL reduced to 60s |
| T90 | Secondary promotion begins | - | EU-Central scaling up |
| T120 | Secondary at 100% capacity | ~30s | 10 pods running in EU |
| T150 | Cutover complete | - | All traffic now in EU |
| T150+ | Primary investigation | Ongoing | Root cause analysis |

**Failover Procedure (Automated):**

```python
async def trigger_failover():
    # 1. Verify secondary is healthy
    secondary = await verify_secondary_ready()
    if not secondary:
        alert("Secondary region unhealthy, cannot failover")
        return
    
    # 2. Scale secondary
    await scale_deployment(
        region="eu-central",
        deployment="genai-api",
        replicas=10  # Full capacity
    )
    
    # 3. Update DNS (TTL: 60 seconds)
    await update_dns_record(
        name="api.platform.com",
        value="eu-central.api.platform",
        ttl=60  # Short TTL for fast revert
    )
    
    # 4. Health check wait
    await wait_for_healthy_replicas(
        region="eu-central",
        min_replicas=8,  # Need 80% before full cutover
        timeout=120
    )
    
    # 5. Notification
    await notify_team(
        channel="#incidents",
        message="FAILOVER COMPLETE: API now in EU-CENTRAL"
    )
    
    # 6. Investigative logging
    await log_failover_event(
        primary_failure_reason="...",
        failover_duration_seconds=150,
        data_loss_detected=False
    )
```

### 2.3 Manual Failback Procedure

**When Primary Region is Restored:**

```bash
#!/bin/bash
# Step 1: Verify primary is fully healthy
kubectl cluster-info --context us-east-1
kubectl get nodes --context us-east-1
kubectl get pods --context us-east-1

# Step 2: Scale up primary to 50% capacity
kubectl scale deployment genai-api --replicas=5 --context us-east-1
kubectl wait --for=condition=Ready pod -l app=genai-api \
  --context us-east-1 --timeout=300s

# Step 3: Canary traffic (10% to primary)
kubectl patch service genai-api --context us-east-1 -p \
  '{"spec":{"trafficPolicy":{"canary":{"weight":10}}}}'

# Step 4: Monitor for errors (5 minutes)
watch -n 1 'kubectl logs -l app=genai-api --context us-east-1 | grep ERROR'

# Step 5: If healthy, increase to 50%
kubectl patch service genai-api --context us-east-1 -p \
  '{"spec":{"trafficPolicy":{"canary":{"weight":50}}}}'

# Step 6: Monitor errors (5 minutes)
# ... same monitoring ...

# Step 7: If healthy, full cutover
kubectl patch service genai-api --context us-east-1 -p \
  '{"spec":{"trafficPolicy":{"canary":{"weight":100}}}}'

# Step 8: Scale down secondary
kubectl scale deployment genai-api --replicas=2 --context eu-central

# Step 9: Update DNS back to primary
aws route53 change-resource-record-sets \
  --zone-id Z123ABC \
  --change-batch '{...}'

# Step 10: Verify complete
curl https://api.platform.com/health/detailed
```

---

## 3. Data Replication Strategy

### 3.1 OpenSearch Replication

**Replication Architecture:**
```yaml
# Primary (us-east-1)
---
apiVersion: opensearch.opster.io/v1
kind: OpenSearchCluster
metadata:
  name: genai-primary
spec:
  general:
    version: 2.11.0
    replicas: 3
    storage: 50Gi
  nodeManager:
    replicas: 3

# Secondary (eu-central) - Follower
---
apiVersion: opensearch.opster.io/v1
kind: OpenSearchCluster
metadata:
  name: genai-secondary
spec:
  general:
    version: 2.11.0
    replicas: 1  # Single replica in standby
    storage: 50Gi
  # Cross-cluster replication configured
```

**Cross-Cluster Replication:**
```bash
# On primary cluster (us-east-1)
PUT _plugins/_replication/genai-documents/start
{
  "leader_alias": "us-east-1-genai-alias",
  "leader_index": "genai-documents",
  "follower_index": "genai-documents"
}

# On secondary cluster (eu-central)
PUT _plugins/_replication/genai-documents/start
{
  "leader_alias": "us-east-1-genai-alias",
  "leader_index": "genai-documents",
  "follower_index": "genai-documents"
}

# Monitor replication
GET _plugins/_replication/genai-documents/status
```

**Replication Lag Monitoring:**
```python
# Prometheus metric
opensearch_replication_lag_bytes{region="eu-central"} = 45000
opensearch_replication_lag_seconds{region="eu-central"} = 2.5

# Alert if lag > 5 seconds
alert: HighReplicationLag
expr: opensearch_replication_lag_seconds > 5
for: 5m
```

### 3.2 Redis Replication

**Redis Master-Replica (Single Node Master)**
```yaml
# Primary (us-east-1)
apiVersion: v1
kind: Service
metadata:
  name: redis-master
spec:
  ports:
  - port: 6379

---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-master
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: redis
        image: redis:7
        command: ["redis-server", "--port", "6379"]

# Secondary (eu-central) - Replica
---
apiVersion: v1
kind: Service
metadata:
  name: redis-replica
spec:
  ports:
  - port: 6379

---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-replica
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: redis
        image: redis:7
        command: 
        - redis-server
        - --port
        - "6379"
        - --replicaof
        - "redis-master.us-east-1"
        - "6379"
```

**Replication Configuration:**
```bash
# Primary: No special config (accepts writes)
# Replica: Read-only
CONFIG SET replica-read-only yes

# Monitor replication
INFO replication

# Expected output:
# role:slave
# master_host:redis-master.us-east-1
# master_repl_offset:1234567
# slave_repl_offset:1234567  # Should match
```

### 3.3 FAISS Index Replication

**Periodic Backup Strategy:**
```bash
# Every 6 hours, backup FAISS indices
0 */6 * * * /scripts/backup-faiss.sh

# Backup script
#!/bin/bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

for tenant in $(list_tenants); do
  SOURCE="/data/indices/$tenant/vectors.faiss"
  DEST="s3://genai-backups/faiss/$tenant/$TIMESTAMP/"
  
  # Compress + upload
  tar czf - "$SOURCE" | aws s3 cp - "$DEST/vectors.tar.gz"
  
  # Verify
  aws s3 ls "$DEST/"
done

# Retention: Keep 30 days
aws s3 sync s3://genai-backups/faiss/ \
  --exclude "*" \
  --include "*" \
  --delete \
  --only-show-errors
```

**FAISS Recovery (if needed):**
```bash
# Restore from backup:
RESTORE_DATE="20240223_120000"

for tenant in $(list_tenants); do
  aws s3 cp \
    "s3://genai-backups/faiss/$tenant/$RESTORE_DATE/vectors.tar.gz" \
    - | tar xzf - -C /data/indices/$tenant
done

# Verify integrity
python -c "
import faiss
import os
for tenant in os.listdir('/data/indices'):
  index = faiss.read_index(f'/data/indices/{tenant}/vectors.faiss')
  print(f'{tenant}: {index.ntotal} vectors')
"
```

---

## 4. Recovery Procedures

### 4.1 Recovery Time Objectives (RTO)

| Scenario | RTO | Approach | Notes |
|----------|-----|----------|-------|
| **Single pod crash** | < 2 min | Kubernetes restart | Auto-healing |
| **Single node failure** | < 5 min | Pod reschedule | Drain & migrate |
| **Region primary down** | < 5 min | Failover | Hot standby ready |
| **Data corruption (DB)** | < 30 min | Restore from snapshot | 6-hour RPO |
| **Complete data loss** | < 60 min | Full region restore | Last backup |

### 4.2 Recovery Point Objectives (RPO)

| Data Type | RPO | Mechanism | Acceptable Loss |
|-----------|-----|-----------|-----------------|
| **Query data** | 6 hours | OpenSearch snapshots | 6 hours worth |
| **Cache** | 0 hours | In-memory, recreated | No loss |
| **Audit logs** | 1 hour | Log aggregation backup | < 1 hour |
| **Vector indices** | 6 hours | FAISS snapshots | Rebuild from docs |
| **Customer data** | 0 hours | Replicated | Zero loss target |

### 4.3 Disaster Recovery Drill

**Quarterly DR Test:**

```bash
#!/bin/bash
# Simulates complete primary region failure

echo "=== DR DRILL: EU-CENTRAL Failover ==="

# 1. Announce drill
echo "DRILL START: Simulating us-east failure"
slack_notify "#incidents" "Starting DR drill"

# 2. Verify secondary health
kubectl cluster-info --context eu-central
kubectl get nodes --context eu-central
kubectl get pvc --context eu-central

# 3. Simulate primary failure (DNS blackhole)
# Change /etc/hosts to point us-east to 127.0.0.1
echo "127.0.0.1 us-east.api.platform" >> /etc/hosts

# 4. Verify failover detection
sleep 30
kubectl logs -l app=monitoring --context eu-central | grep "FAILOVER"

# 5. Execute failover
./scripts/manual-failover.sh eu-central

# 6. Verify secondary responds
curl https://eu-central.api.platform/health/detailed
curl -X POST https://eu-central.api.platform/api/query \
  -H "X-Tenant-ID: test-tenant" \
  -d '{"query":"test"}'

# 7. Check error metrics
curl eu-central:9090/api/v1/query?query=rate\(errors_total\[5m\]\)

# 8. Revert (remove blackhole)
sed -i '/127.0.0.1 us-east/d' /etc/hosts

# 9. Post-drill report
echo "DR DRILL SUCCESSFUL"
echo "Failover time: $(date -d @$((READY_TIME - START_TIME)) +%Hh%Mm%Ss)"
echo "Data loss: NONE"
```

---

## 5. Communication During Disaster

### 5.1 Incident Notification

**Automatic Notification (Triggered at T15 = Detection + 15s):**

```json
{
  "alert": "FAILOVER_INITIATED",
  "time": "2024-02-23T12:00:00Z",
  "severity": "SEV-1",
  "notifications": [
    {
      "channel": "slack",
      "target": "#incidents",
      "message": "⚠️ PRIMARY REGION FAILURE - Automatic failover initiated to EU-CENTRAL"
    },
    {
      "channel": "pagerduty",
      "target": "on-call-sre",
      "message": "Failover in progress"
    },
    {
      "channel": "status_page",
      "target": "status.platform.com",
      "message": "🟡 Investigating connectivity issues - Automatic failover in progress"
    },
    {
      "channel": "email",
      "target": "customers@platform.com",
      "subject": "Incident Notification: Service Continuity Maintained"
    }
  ]
}
```

### 5.2 Customer Communication

**Status Page Updates (Throughout):**

```
T0:  🟡 INVESTIGATING: We are experiencing issues with our service
     and are investigating the cause.

T5:  🟡 IDENTIFIED: Issue identified in primary region. Automatic 
     failover to secondary region in progress.

T10: 🟡 PARTIAL DEGRADATION: Service is operating in degraded mode 
     with reduced performance. Secondary region may experience higher 
     latency (+100-200ms).

T20: 🟠 MONITORING: Service is being monitored as failover completes. 
     Expected full recovery in 2-3 minutes.

T30: ✅ RESOLVED: Service has fully recovered and all systems are 
     operating normally.
```

### 5.3 War Room

**Incident War Room (Zoom):**
- SRE lead
- Platform engineer
- Database engineer  
- Security officer (if data involved)

**Every 5 minutes:**
- Current status
- ETA for resolution
- Any roadblocks

---

## 6. Post-Incident Review

### 6.1 Post-Mortem Template

```markdown
## Incident Report: [INCIDENT_ID]

### Summary
- **Incident**: [One sentence description]
- **Duration**: [Start time] - [End time] ([X minutes])
- **Servers Affected**: [List of systems]
- **Customer Impact**: [Description of user-facing impact]

### Root Cause
[Detailed explanation of why it happened]

### Detection & Response Timeline
- T0:   Primary region controller crash
- T15:  Health check detected failure (3 consecutive failures)
- T20:  Automatic failover initiated
- T150: Service fully recovered in secondary
- T155: Incident resolved (30 min total)

### What Went Well
- [ ] Automatic failover worked
- [ ] Monitoring detected issue quickly
- [ ] Communication to customers timely
- [ ] Secondary region had capacity

### What Went Wrong
- [ ] Primary region upgrade not staged properly
- [ ] Insufficient load testing before deployment
- [ ] Monitoring gap (missed early signals)

### Action Items
- [ ] Implement upgrade for primary region (Mandatory)
- [ ] Add pre-upgrade chaos test (Before any upgrade)
- [ ] Improve monitoring of controller health (Monitoring)
- [ ] Document failover procedure (Documentation)
```

---

## 7. Glossary

- **RTO**: Recovery Time Objective (how fast to recover)
- **RPO**: Recovery Point Objective (how much data can be lost)
- **Primary**: Active region handling traffic
- **Secondary**: Passive region ready for failover
- **Replication lag**: Delay between primary write and secondary commit
- **Failover**: Automatic switch to secondary
- **Failback**: Manual switch back to primary
- **DR drill**: Scheduled failover test

