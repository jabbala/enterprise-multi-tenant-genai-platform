# Security Operations & Incident Response

## 1. Security Event Observable

### 1.1 Security Event Dashboard

**Real-Time Security Dashboard (Grafana):**

```
┌─────────────────────────────────────────────────────────┐
│                  SECURITY OPERATIONS                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ⚠️  ACTIVE THREATS: 0                                  │
│  🟡 WARNINGS: 3                                         │
│  ✅ HEALTHY: All systems                                │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  INCIDENT TIMELINE (Last 24H)                          │
│                                                         │
│  12:45  Failed auth: user-123 (10 attempts) 🔴         │
│  11:30  Prompt injection detected (BLOCKED) 🟡         │
│  11:15  Cross-tenant access attempt (DENIED) 🔴        │
│  10:00  Unusual API usage: tenant-456 🟡              │
│  09:30  PII redaction triggered (45 fields) ℹ️         │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  METRIC GRAPHS                                         │
│                                                         │
│ Failed Auth Attempts:      │ Injection Attempts:       │
│  ▲                         │  ▲                        │
│  │    ▁▂▁                  │  │  ▂▁                    │
│  │ ▂▄██▄▂                  │  │ ▄▄██▁▁                 │
│  └─────────────────────────└─────────────────────────  │
│        24H                          24H               │
│                                                         │
│ Cross-Tenant Attempts:     Rate Limit Violations:      │
│  ▲                         │  ▲                        │
│  │  ▁                      │  │                        │
│  │ ▁▁                      │  │  ▁▂▁▁▂                 │
│  └─────────────────────────└─────────────────────────  │
│        24H                          24H               │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  TOP SECURITY EVENTS (Last 24H)                        │
│                                                         │
│ 1. Prompt Injection       45 attempts      BLOCKED     │
│ 2. Failed Auth            23 users         FLAGGED     │
│ 3. PII Detection          12 fields        REDACTED    │
│ 4. Rate Limit Bypass      3 users          BLOCKED     │
│ 5. Geo Anomaly            2 sessions       FLAGGED     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Metrics Available:**
```prometheus
# Authentication
failed_auth_total{user_id, tenant_id, reason}          # Total failed logins
failed_auth_rate_per_hour{tenant_id}                   # Rate of failures
unique_failed_users{tenant_id}                         # Users with failures
account_lockouts_total{tenant_id}                      # Locked accounts

# Prompt Injection
prompt_injections_total{pattern, tenant_id}           # Blocked attempts
injection_rate_per_minute{tenant_id}                  # Attack rate
blocked_prompt_count_total{tenant_id}                 # Total blocked

# Cross-Tenant
cross_tenant_attempts_total{attacker_id}              # Breach attempts
cross_tenant_detected_total{tenant_id}                # Detected accesses

# PII & Data
pii_redactions_total{type, tenant_id}                 # Redacted fields
anomaly_score{tenant_id, metric}                      # Anomaly detection

# Rate Limiting
rate_limit_violations_total{tenant_id}                # Quota violations
burst_rate_exceeded{tenant_id}                        # Burst limit hit
```

### 1.2 Injection Attempt Monitoring

**Real-Time Attack Pattern Detection:**

```python
class PromptInjectionDashboard:
    """Monitor and track injection attempts"""
    
    async def track_injection(self, tenant_id: str, pattern: str):
        """Log detected injection"""
        metrics.prompt_injections_total.labels(
            pattern=pattern,
            tenant_id=tenant_id
        ).inc()
        
        # Store for timeline
        await redis.lpush(
            f"security:injections:{tenant_id}",
            json.dumps({
                "timestamp": now(),
                "pattern": pattern,
                "query_hash": sha256(query),
                "user_id": user_id
            })
        )
    
    async def get_injection_timeline(self, tenant_id: str, hours=24):
        """Get injection attempts over time"""
        key = f"security:injections:{tenant_id}"
        events = await redis.lrange(key, 0, -1)
        
        # Aggregate by pattern
        patterns = {}
        for event in events:
            data = json.loads(event)
            pattern = data["pattern"]
            patterns[pattern] = patterns.get(pattern, 0) + 1
        
        return {
            "total": len(events),
            "unique_patterns": list(patterns.keys()),
            "pattern_counts": patterns,
            "trend": "increasing|stable|decreasing"
        }
```

**Alert Rules:**
```yaml
groups:
- name: security.rules
  rules:
  - alert: HighPromptInjectionRate
    expr: rate(prompt_injections_total[5m]) > 10  # > 10 per 5 min
    for: 5m
    annotations:
      severity: warning
      summary: "High prompt injection attack rate: {{ $value }}/min"
  
  - alert: NewInjectionPattern
    expr: count(increase(prompt_injections_total[5m]) > 0) by (pattern) > 0
    for: 1m
    annotations:
      severity: info
      summary: "New injection pattern detected: {{ $labels.pattern }}"
  
  - alert: SingleTenantHighInjections
    expr: rate(prompt_injections_total{tenant_id!=""}[1m]) > 5
    for: 2m
    annotations:
      severity: critical
      summary: "Tenant {{ $labels.tenant_id }} under attack: {{ $value }}/min"
```

### 1.3 Cross-Tenant Breach Monitoring

**Continuous Validation:**
```python
async def validate_cross_tenant_isolation():
    """Continuous check for data leakage"""
    
    # Sample queries over last hour
    queries = await db.query("""
        SELECT id, tenant_id, user_id, query_hash
        FROM query_log
        WHERE created_at > NOW() - INTERVAL 1 HOUR
        ORDER BY RANDOM()
        LIMIT 1000
    """)
    
    breaches = []
    for query in queries:
        # Re-verify tenant ownership of results
        results = await retrieval_service.hybrid_retrieve(
            query=query["query_hash"],
            tenant_id=query["tenant_id"]
        )
        
        # Validate each result
        for doc in results:
            if doc["metadata"]["tenant_id"] != query["tenant_id"]:
                breaches.append({
                    "query_id": query["id"],
                    "expected_tenant": query["tenant_id"],
                    "found_tenant": doc["metadata"]["tenant_id"],
                    "severity": "critical"
                })
                
                # Immediate alert
                alert_oncall(
                    f"CROSS-TENANT BREACH DETECTED: "
                    f"{query['tenant_id']} → {doc['metadata']['tenant_id']}"
                )
    
    # Log results
    if breaches:
        logger.error(f"Cross-tenant breaches detected: {len(breaches)}")
        metrics.cross_tenant_breaches_total.add(len(breaches))
```

### 1.4 Tenant Anomaly Detection

**Behavioral Analytics:**

```python
class TenantAnomalyDetector:
    """Detect unusual tenant behavior"""
    
    async def detect_anomalies(self, tenant_id: str) -> List[Anomaly]:
        """Detect deviation from baseline"""
        
        baseline = await get_tenant_baseline(tenant_id)  # Last 30 days
        current = await get_tenant_metrics(tenant_id, last_hour=True)
        
        anomalies = []
        
        # Query volume spike
        if current["queries_per_hour"] > baseline["queries_per_hour"] * 5:
            anomalies.append({
                "type": "query_volume_spike",
                "baseline": baseline["queries_per_hour"],
                "current": current["queries_per_hour"],
                "severity": "warning"
            })
        
        # Unusual error rate
        if current["error_rate"] > baseline["error_rate"] + 0.1:  # 10% higher
            anomalies.append({
                "type": "error_rate_increase",
                "baseline": baseline["error_rate"],
                "current": current["error_rate"],
                "severity": "warning"
            })
        
        # Geo-location anomaly
        user_locations = await get_user_locations(tenant_id, last_hour=True)
        if len(user_locations) > 5:  # More than 5 locations in 1 hour
            anomalies.append({
                "type": "geo_anomaly",
                "locations": user_locations,
                "severity": "info"
            })
        
        # Failed auth spike
        failed_auth = await get_failed_auth_count(tenant_id, last_hour=True)
        if failed_auth > baseline["daily_failed_auth"] * 3:
            anomalies.append({
                "type": "auth_spike",
                "baseline": baseline["daily_failed_auth"],
                "current": failed_auth,
                "severity": "critical"
            })
        
        return anomalies
```

**Anomaly Score Calculation:**
```python
def calculate_anomaly_score(
    baseline: dict,
    current: dict,
    weights: dict
) -> float:
    """
    Score from 0.0 (normal) to 1.0 (highly anomalous)
    
    Factors:
    - Query volume deviation (weight: 0.3)
    - Error rate change (weight: 0.2)
    - Latency increase (weight: 0.2)
    - Auth failures (weight: 0.2)
    - Cost change (weight: 0.1)
    """
    
    score = 0.0
    
    # Volume
    vol_deviation = abs(current["qph"] - baseline["qph"]) / baseline["qph"]
    score += min(vol_deviation, 1.0) * weights["volume"]
    
    # Errors
    err_deviation = (current["error_rate"] - baseline["error_rate"]) / baseline["error_rate"]
    score += min(abs(err_deviation), 1.0) * weights["errors"]
    
    # Latency
    lat_deviation = (current["p95_latency"] - baseline["p95_latency"]) / baseline["p95_latency"]
    score += min(lat_deviation, 1.0) * weights["latency"]
    
    # Auth
    auth_deviation = current["failed_auth"] / max(baseline["daily_auth"],1)
    score += min(auth_deviation, 1.0) * weights["auth"]
    
    # Cost
    cost_deviation = (current["cost"] - baseline["daily_cost"]) / baseline["daily_cost"]
    score += min(abs(cost_deviation), 1.0) * weights["cost"]
    
    return min(score, 1.0)
```

---

## 2. Incident Response Procedures

### 2.1 Security Incident Classification

| Level | Type | Impact | Response | Timeline |
|-------|------|--------|----------|----------|
| **P0** | Data breach | Tenant data exposed | Full response | < 5 min |
| **P1** | Auth compromise | Account takeover | IR team | < 15 min |
| **P2** | Intrusion attempt | Blocked attack | Logging | < 1 hour |
| **P3** | Suspicious activity | Possible threat | Monitoring | < 24 hours |

### 2.2 Breach Response Playbook

**P0: Suspected Data Breach**

```
Timeline:
T0:    Alert received (automated or manual report)
T1:    Incident commander assigned
T5:    IR team assembled (security lead + engineers)
T10:   Initial investigation (breach scope assessment)
T15:   Containment (isolate affected systems if needed)
T20:   Evidence preservation (copy logs, snapshots)
T30:   Notification decision (legal consultation)
T60:   Customer notification (if required)
T24h:  Full investigation report
T72h:  Remediation plan
T∞:    Ongoing monitoring

Team:
- Incident Commander (lead)
- Security Engineer (investigation)
- Platform Engineer (system access)
- Legal/Compliance (notification)
- Communications (customer updates)
```

**Investigation Checklist:**
```
[ ] Scope of breach
    - [ ] Which tenants affected?
    - [ ] What data accessed?
    - [ ] How much data?
    - [ ] For how long?

[ ] Root cause
    - [ ] Attack vector
    - [ ] Entry point
    - [ ] Detection gap
    - [ ] Why not earlier detected?

[ ] Evidence
    - [ ] Access logs from logs.genai.internal
    - [ ] Network traffic (PCAP from siem.internal)
    - [ ] Database audit logs
    - [ ] Kubernetes audit logs
    - [ ] Source of compromise

[ ] Containment
    - [ ] Revoke compromised credentials
    - [ ] Patch vulnerability
    - [ ] Isolate affected components
    - [ ] Rotate encryption keys

[ ] Recovery
    - [ ] Restore from clean backup
    - [ ] Verify integrity
    - [ ] Monitoring for re-exploitation
    - [ ] Gradual traffic restoration

[ ] Notification
    - [ ] Determine which tenants to notify
    - [ ] Regulatory notification (72-hour GDPR)
    - [ ] Call templates prepared
    - [ ] FAQ document ready
```

### 2.3 Compromised Credential Response

**When Attacker Gains API Key:**

```python
async def handle_compromised_credentials(
    api_key: str,
    detected_at: datetime
):
    """Respond to leaked/compromised credentials"""
    
    # 1. Immediate: Revoke key
    await revoke_api_key(api_key)
    audit_logger.log(f"Revoked key: {api_key_hash}")
    
    # 2. Investigate: Find all usage
    usage = await db.query("""
        SELECT *
        FROM api_access_log
        WHERE api_key_hash = %s
        ORDER BY timestamp DESC
        LIMIT 10000
    """, api_key_hash)
    
    suspicious = []
    for req in usage:
        if req["timestamp"] > detected_at - timedelta(hours=24):
            suspicious.append(req)
    
    # 3. Assess: Determine damage
    tenants_accessed = set(req["tenant_id"] for req in suspicious)
    documents_exposed = await count_documents_by_tenant(tenants_accessed)
    
    # 4. Notify: Inform customers
    for tenant_id in tenants_accessed:
        await notify_tenant(
            tenant_id=tenant_id,
            incident_type="compromised_key",
            affected_documents=documents_exposed[tenant_id],
            remediation="New API key issued, old key revoked"
        )
    
    # 5. Monitor: Watch for re-usage
    await create_alert_rule(
        name=f"watch_key_{api_key_hash}",
        condition=f"api_key == '{api_key_hash}'",
        duration="30d",
        action="immediate_block_and_alert"
    )
```

---

## 3. Audit Logging & Forensics

### 3.1 Audit Log Schema

```json
{
  "event_id": "evt-uuid-1234",
  "timestamp": "2024-02-23T12:00:00.123456Z",
  "event_type": "QUERY_EXECUTED|AUTH_FAILED|DATA_ACCESS|CONFIG_CHANGED",
  
  "actor": {
    "user_id": "user-5678",
    "tenant_id": "acme-corp",
    "api_key_hash": "sha256(...)",
    "source_ip": "1.2.3.4",
    "user_agent": "Mozilla/5.0...",
    "country": "US"
  },
  
  "resource": {
    "type": "query|document|setting",
    "id": "resource-uuid",
    "path": "/api/query"
  },
  
  "action": {
    "type": "read|write|delete|execute",
    "allowed": true,
    "enforcement_point": "rate_limit|auth|governance"
  },
  
  "result": {
    "status": "success|denied|error",
    "reason": "Prompt injection detected",
    "duration_ms": 1234,
    "cost_tokens": 450,
    "cost_dollars": 0.015
  },
  
  "security": {
    "threat_detected": false,
    "anomaly_score": 0.05,
    "alerts_triggered": []
  }
}
```

### 3.2 Forensic Analysis

**Query Audit Trail:**
```python
async def get_complete_audit_trail(
    query_id: str
):
    """Complete forensics for single query"""
    
    events = await audit_log.search({
        "query": {
            "match": {"transaction_id": query_id}
        }
    })
    
    # Reconstruct timeline
    timeline = []
    for event in sorted(events, key=lambda x: x["timestamp"]):
        timeline.append({
            "T": event["timestamp"],
            "Stage": event["event_type"],
            "User": event["actor"]["user_id"],
            "IP": event["actor"]["source_ip"],
            "Action": event["action"]["type"],
            "Result": event["result"]["status"],
            "Duration": f"{event['result']['duration_ms']}ms"
        })
    
    return timeline

# Example output:
# T  | Stage           | User      | IP      | Action  | Result  | Duration
# ---|-----------------|-----------|---------|---------|---------|----------
# 00 | AUTH            | user-5678 | 1.2.3.4 | read    | success | 2ms
# 01 | RATE_LIMIT      | user-5678 | 1.2.3.4 | check   | success | 1ms
# 02 | PROMPT_VALIDATE | user-5678 | 1.2.3.4 | check   | success | 3ms
# 03 | EMBEDDING       | user-5678 | 1.2.3.4 | execute | success | 450ms
# 04 | BM25_SEARCH     | user-5678 | 1.2.3.4 | read    | success | 125ms
# 05 | VECTOR_SEARCH   | user-5678 | 1.2.3.4 | read    | success | 89ms
# 06 | PII_REDACTION   | user-5678 | 1.2.3.4 | execute | success | 5ms
# 07 | LLM_CALL        | user-5678 | 1.2.3.4 | execute | success | 2300ms
# 08 | AUDIT_LOG       | system    | local   | write   | success | 12ms
```

---

## 4. Compliance & Certifications

### 4.1 Audit Schedule

| Certification | Frequency | Cost | Coverage |
|---------------|-----------|------|----------|
| **SOC 2 Type II** | Annually | $20K | Security, Availability, Processing Integrity |
| **HIPAA BAA** | Annually | $10K | Health data handling |
| **GDPR DPA** | Ongoing | Legal | Data processing agreement |
| **ISO 27001** | Every 3y | $30K | Information security mgmt |
| **PCI DSS** | Annually | $5K | Payment card handling (if applicable) |

### 4.2 Audit Preparation Checklist

```
[ ] Security Controls
    [ ] All systems encrypted (in-transit + at-rest)
    [ ] Access controls enforced (RBAC)
    [ ] Audit logging 100% complete
    [ ] Incident response procedures tested

[ ] Documentation
    [ ] Security policy documented
    [ ] Acceptable use policy available
    [ ] Incident response plan
    [ ] Disaster recovery plan
    [ ] Risk assessment documents

[ ] Testing
    [ ] Penetration test results (< 1 year old)
    [ ] Vulnerability scan results (< 30 days)
    [ ] Security control testing
    [ ] Access control verification

[ ] Personnel
    [ ] Background checks on admins
    [ ] Security training completion (100%)
    [ ] Confidentiality agreements signed
    [ ] Key personnel documented

[ ] Tools & Systems
    [ ] SIEM configured and monitored
    [ ] Log aggregation active
    [ ] Backup and recovery tested
   [ ] Change management process defined
```

---

## 5. Glossary

- **IR**: Incident Response
- **SIEM**: Security Information and Event Management
- **RCA**: Root Cause Analysis
- **P0-P3**: Priority levels (0=highest)
- **SOC 2**: System and Organization Controls
- **HIPAA**: Health Insurance Portability Act
- **GDPR**: General Data Protection Regulation
- **PII**: Personally Identifiable Information
- **Forensics**: Investigation of security incidents
- **Audit Trail**: Complete log of all actions

