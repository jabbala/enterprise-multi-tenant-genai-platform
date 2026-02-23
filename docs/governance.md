# Data Governance & Privacy

## 1. Overview

This document details data governance controls, privacy compliance, and data protection mechanisms for the Enterprise Multi-Tenant GenAI Platform.

---

## 2. Right-to-Erasure (GDPR Article 17)

### 2.1 Request Workflow

**API Endpoint:**
```
DELETE /admin/v1/tenants/{tenant_id}/users/{user_id}/data
Authorization: Bearer {jwt_admin}
```

**Request Body:**
```json
{
  "reason": "user-request|contract-termination|data-expiration",
  "effective_date": "2024-02-23T00:00:00Z",
  "callback_url": "https://webhook.example.com/erasure-complete"
}
```

**Response:**
```json
{
  "erasure_request_id": "erase-uuid-1234",
  "status": "pending",
  "estimated_completion": "2024-03-01T00:00:00Z",
  "scope": {
    "documents_to_delete": 1245,
    "queries_to_delete": 8900,
    "cache_entries": 450,
    "backups_to_exclude": true
  }
}
```

### 2.2 Implementation Details

**Phase 1: Immediate (< 1 minute)**
- Mark user as "pending deletion" in metadata
- Reject any new queries from this user
- Return 410 Gone for user requests
- Log erasure request with audit ID

**Phase 2: Indexed Data (< 1 hour)**
- OpenSearch: Delete documents with match `author.user_id = {user_id}`
- FAISS: Mark vectors as deleted, rebuild index
- Cache: Flush all user query results
- Audit: Preserve audit log (GDPR allows audit trail)

**Phase 3: Historical Data (< 30 days)**
- Search backups for user data
- Tag for exclusion from future backups
- Schedule deletion from archive storage
- Verify deletion via spot checks

**Phase 4: Verification (30-60 days)**
- Run full audit scan
- Confirm no user data remains
- Generate erasure certificate
- Notify user via callback URL

### 2.3 Data to Erase

**Always Deleted:**
- Documents authored by user
- Query text submitted by user
- User profile and preferences
- User API keys and credentials

**Preserved (Allowed under GDPR):**
- Audit logs (for compliance)
- Anonymized aggregated metrics
- System logs (with user info redacted)
- Deleted document metadata (if used for compliance)

### 2.4 Erasure Guarantee

**Technical Guarantee:**
- Writes are idempotent (safe to retry)
- Deletion is irreversible (no undo)
- Cascading delete removes all references
- Cryptographic proof of deletion maintained

**Compliance Assurance:**
- Third-party audit annually
- Erasure certificate issued per request
- Emergency deletion procedures documented
- Legal hold procedures in place

---

## 3. Data Residency Support

### 3.1 Residency Options

| Region | Code | Compliance | Latency (US) | Primary Use |
|--------|------|-----------|-------------|------------|
| **EU** | eu-central | GDPR, NIS2 | 150-200ms | European enterprises |
| **US** | us-east | SOC2, HIPAA | < 50ms | US/Canada companies |
| **APAC** | ap-sg | PDPA, C2PA | 100-150ms | Singapore/Australia |

### 3.2 Enforcement

**Configuration (per tenant):**
```yaml
tenant-001:
  residency: "eu-central"
  allowed_regions: ["eu-central"]  # Optional whitelist
  cross_region_access: "deny"       # Block if accessed from other region
  data_export_allowed: false        # Prevent downloads
  subprocessor_list: [...]          # Approved processors
```

**Kubernetes Enforcement:**
```yaml
# Pod anti-affinity: deployments must be in region
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchExpressions:
        - key: region
          operator: NotIn
          values: ["eu-central"]  # Forces pod to NOT be in other region
      topologyKey: "region"
```

**Network Enforcement:**
```
OpenSearch:
  - Shard allocation: Only nodes in specified region
  - Index replication: Same region only
  - Snapshots: Region-locked storage

Redis:
  - Master: Primary region
  - Replicas: Same region only
  - No cross-region replication
```

### 3.3 Monitoring

**Residency Violation Detection:**
```
Metric: data_residency_violations_total
Alert: IF region(query) != region(data) THEN page_oncall
```

**Audit Trail:**
```json
{
  "event_type": "DATA_RESIDENCY_ENFORCEMENT",
  "timestamp": "2024-02-23T12:00:00Z",
  "tenant_id": "acme-corp",
  "action": "denied",
  "reason": "cross-region-access-attempt",
  "request_region": "us-east",
  "data_region": "eu-central",
  "source_ip": "1.2.3.4"
}
```

---

## 4. Encryption & Key Management

### 4.1 Encryption Architecture

**In-Transit:**
- TLS 1.3 for all network communication
- Certificate: Let's Encrypt or enterprise CA
- HSTS header: 31536000 seconds (1 year)
- Perfect forward secrecy enabled

**At-Rest (Optional - Off by Default):**
```
OpenSearch indices:
  - DEK (Data Encryption Key): AES-256-GCM
  - KEK (Key Encryption Key): Stored in KMS
  - Rotation: Every 90 days

Redis cache:
  - Transparent field encryption (optional)
  - Value encryption: AES-256-CBC
  - TTL: Same as cache entry

FAISS indices:
  - File-level encryption
  - Encryption at storage layer (OS/filesystem)
  - Backup encryption: AES-256
```

### 4.2 Key Management Options

**Option 1: Kubernetes Secrets (Managed)**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: encryption-keys-tenant-001
type: Opaque
data:
  kek.pem: <base64-encoded-key>
```
- Pros: Simple, managed by Kubernetes
- Cons: Keys stored on etcd disk, not HSM-backed
- Use: Development, non-sensitive workloads

**Option 2: AWS KMS (Customer-Managed Key)**
```python
import boto3
kms = boto3.client('kms')
response = kms.decrypt(
    CiphertextBlob=encrypted_dek
)
```
- Pros: AWS-managed, CloudTrail audit
- Cons: AWS-specific, additional latency (< 10ms)
- Use: AWS deployments

**Option 3: HashiCorp Vault (Enterprise)**
```python
import hvac
client = hvac.Client(url='https://vault.internal')
secret = client.secrets.kv.read_secret_version(path='tenant-001/dek')
```
- Pros: Multi-cloud, enterprise features, Dynamic secrets
- Cons: Operational complexity
- Use: Multi-cloud, high-security requirements

### 4.3 Key Rotation Policy

**Automatic Rotation Schedule:**
```
DEK (Data Encryption Key):
  - Rotation interval: Every 90 days
  - Trigger: Automated Kubernetes CronJob
  - Process: Re-encrypt all data with new key
  - Duration: < 1 hour (off-peak)
  - Verification: Hash comparison before/after

KEK (Key Encryption Key):
  - Rotation interval: Every 180 days
  - Process: AWS KMS automatic rotation (if enabled)
  - Manual approval: Required for critical tenants
  - Fallback keys: Keep 2 previous versions for decryption

Audit Logging:
  - Every rotation logged with timestamp
  - Failed rotations: Alerting
  - Key versions tracked in audit trail
```

### 4.4 Key Escrow & Disaster Recovery

**Escrow Procedure:**
```
1. Generate DEK: Application creates key
2. Encrypt DEK with KEK: Standard key hierarchy
3. Create escrow copy: Encrypt DEK with escrow public key
4. Store separately: Escrow key in secure location
5. Audit: Log escrow copy creation
6. Recovery: If primary keys lost, reconstruct from escrow
```

**Escrow Storage:**
- Primary location: Company vault (physical)
- Backup: Safe deposit box
- Third-party: Optional external escrow service
- Access control: Requires 2 executives + legal

---

## 5. Prompt Retention & Expiration

### 5.1 Retention Policies

**Default Policy (by classification):**

| Data Type | Default TTL | Minimum | Maximum | Use Case |
|-----------|------------|---------|---------|----------|
| **User Query** | 30 days | 7 days | 90 days | Analysis, SLA verification |
| **LLM Prompt** | 30 days | 7 days | 90 days | Quality review, debugging |
| **LLM Response** | 30 days | 7 days | 90 days | Audit trail |
| **Sensitive PII** | 7 days | 0 days* | 30 days | Auto-redact after 7 days |
| **Audit Log** | 90 days | 30 days | 1 year | Compliance |
| **Cost Events** | 366 days | 90 days | 3 years | Billing |

\* For HIPAA: 0 days = immediate deletion

**Premium Tier Customization:**
```
POST /admin/v1/tenants/{tenant_id}/retention-policy
{
  "queries": 14,           # 14 days
  "llm_prompts": 7,       # 7 days
  "sensitive_data": 0,    # Immediate deletion
  "audit_logs": 365       # 1 year
}
```

### 5.2 Automatic Deletion Process

**Daily Delete Job (00:00 UTC):**
```python
async def delete_expired_prompts():
    # Query documents past TTL
    expired = db.query(
        "timestamp < NOW() - INTERVAL {retention_days} DAY"
    )
    
    # Delete in batches to avoid locks
    for batch in chunk(expired, 1000):
        delete_documents(batch)
        # Reindex to compact
        optimize_indices()
        
    # Audit log
    audit_logger.log_deletion(
        count=len(expired),
        reason="automated_retention_expiration"
    )
```

**Scheduled Deletion Proof:**
```json
{
  "event_type": "DATA_DELETION",
  "timestamp": "2024-02-23T00:05:00Z",
  "job_id": "delete-job-20240223",
  "deleted_count": 45000,
  "retention_policy": "default",
  "verification_hash": "sha256(...)",
  "executed_by": "system:retention-manager"
}
```

### 5.3 Exception Handling

**Request Extended Retention:**
```
POST /admin/v1/queries/{query_id}/extend-retention
{
  "extension_days": 30,
  "reason": "active_litigation|under_review"
}
```

**Legal Hold:**
```
PUT /admin/v1/tenants/{tenant_id}/legal-hold
{
  "enabled": true,
  "reason": "litigation_notice_123",
  "issued_by": "legal@company.com",
  "until": "2024-12-31"
}
```
- When enabled: All scheduled deletes paused
- Retention: Indefinite until hold removed
- Logging: Every access logged

**Data Subject Request (GDPR):**
```
GET /v1/user/{user_id}/data-export?format=json
```
- Returns all data for a user
- Format: Machine-readable JSON
- Includes: Queries, embeddings, metadata
- Completes within 30 days

---

## 6. Compliance Frameworks

### 6.1 GDPR (General Data Protection Regulation)

**Article 17 - Right to Erasure** ✓ Implemented
**Article 27 - Data Processing Agreement** ✓ Template provided
**Article 32 - Security Measures** ✓ Encryption, access controls
**Article 33 - Breach Notification** ⏳ 72-hour requirement
**Article 35 - DPIA** ⏳ Template available

### 6.2 HIPAA (Health Insurance Portability & Accountability)

**Security Rule** ✓ AES-256 encryption
**Breach Notification** ⏳ 60-day notification
**Business Associate Agreement** ⏳ Template available
**Audit & Accountability** ✓ Comprehensive logging
**Access Controls** ✓ Role-based access

### 6.3 CCPA (California Consumer Privacy Act)

**Consumer Rights:**
- **Access:** Data download available
- **Deletion:** Right to erasure implemented
- **Opt-out:** Can restrict sale of data
- **Non-discrimination:** No pricing variation

### 6.4 SOC 2 Type II

**Controls Implemented:**
- Security: Encryption, access controls, vulnerability management
- Availability: 99.9% SLA, multi-region failover
- Processing Integrity: Audit logs, checksums
- Confidentiality: Tenant isolation, PII redaction
- Privacy: Retention policies, data residency

**Annual Audit:** Third-party audited December-February

---

## 7. Privacy by Design

### 7.1 Data Minimization

**Collect Only Necessary Data:**
```python
# Bad: Capture everything
query_request = {
    "query": "...",
    "user_agent": "...",
    "ip_address": "...",
    "device_id": "...",
    "full_name": "...",
    "email": "...",
    "phone": "..."
}

# Good: Collect minimal required
query_request = {
    "query": "...",
    "user_id": "opaque-uuid"  # Hashed, not traceable
}
```

**Fields Never Collected:**
- IPv6 addresses (too identifiable)
- Device IDs (unless explicitly needed)
- Full email (just domain)
- Phone numbers
- Browser fingerprints

### 7.2 Pseudonymization

**User Hashing:**
```python
# Never store: "john.doe@acme.com"
# Store instead: hash(user_id, tenant_secret)

from hashlib import sha256

def pseudonymize_user(user_id: str, tenant_id: str) -> str:
    secret = os.getenv(f"TENANT_{tenant_id}_SECRET")
    return sha256(f"{user_id}:{secret}".encode()).hexdigest()[:16]
```

**Document Hashing:**
```python
# Never store: "Employee SSN 123-45-6789"
# Hash and redact before storage

def anonymize_before_storage(doc_text: str) -> str:
    doc_text = PII_REDACTOR.redact(doc_text)  # [REDACTED_SSN]
    return doc_text
```

### 7.3 Consent Management

**Consent Tracking:**
```json
{
  "user_id": "user-uuid",
  "tenant_id": "acme-corp",
  "consents": {
    "analytics": {
      "granted": true,
      "timestamp": "2024-02-01T00:00:00Z",
      "version": "1.2"
    },
    "marketing": {
      "granted": false,
      "timestamp": "2024-02-01T00:00:00Z"
    },
    "data_sharing": {
      "granted": false,
      "timestamp": "2024-02-01T00:00:00Z"
    }
  }
}
```

**Consent Validation in Queries:**
```python
if not user_consent.analytics:
    # Don't track metrics
    # Don't send to analytics service
    pass
```

---

## 8. Glossary

- **DEK**: Data Encryption Key (encrypts actual data)
- **KEK**: Key Encryption Key (encrypts DEK)
- **KMS**: Key Management Service (AWS, HashiCorp Vault, etc.)
- **GDPR**: General Data Protection Regulation (EU)
- **HIPAA**: Health Insurance Portability Act (US healthcare)
- **CCPA**: California Consumer Privacy Act (California)
- **SOC2**: Security and Availability controls (audited)
- **PII**: Personally Identifiable Information
- **DPA**: Data Processing Agreement
- **DPIA**: Data Protection Impact Assessment

