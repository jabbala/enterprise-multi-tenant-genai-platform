#!/usr/bin/env markdown
# Configuration Quick Reference Card

## 🚀 Quick Start (Development)

```bash
# 1. Copy example configuration
cp .env.example .env

# 2. Update critical values
export OPENAI_API_KEY="sk-..."
export DATABASE_URL="postgresql://..."

# 3. Load and run
export $(cat .env | grep -v '#' | xargs)
python -m app.main
```

## 📝 Configuration File Locations

| Environment | File | Purpose | Committed |
|-------------|------|---------|-----------|
| Development | `.env` | Local overrides | ❌ No |
| Development | `.env.example` | Template | ✅ Yes |
| Staging | `.env.staging` | Staging settings | ⚠️ No secrets |
| Production | `.env.production` | Production template | ⚠️ No secrets |

## 🔑 Critical Settings (Always Required)

```bash
DATABASE_URL                  # PostgreSQL connection
REDIS_URL                     # Redis connection  
OPENAI_API_KEY                # LLM provider key
JWT_SECRET_KEY                # Auth secret (min 32 chars)
KMS_PROVIDER                  # Key management service
```

## 🌍 Environment Variables (Override Priority)

```bash
# Highest priority - these override everything
export APP_ENV=production
export DEBUG=false
export PORT=8000
export WORKERS=4

# Database
export DATABASE_URL="postgresql://user:pass@host:5432/db"

# Security
export JWT_SECRET_KEY="$(openssl rand -base64 32)"
export ENCRYPTION_ENABLED=true

# LLM
export OPENAI_API_KEY="sk-..."
export LLM_PROVIDER=openai

# Load from file (lower priority)
export $(cat .env.production | grep -v '#' | xargs)
```

## 🐳 Docker Deployment

```bash
# Development
docker build -t genai-app:dev .
docker run -e APP_ENV=development --env-file .env genai-app:dev

# Production  
docker build -t genai-app:prod .
docker run -e APP_ENV=production \
  -e DATABASE_URL="$DB_URL" \
  -e OPENAI_API_KEY="$OPENAI_KEY" \
  -e JWT_SECRET_KEY="$JWT_SECRET" \
  genai-app:prod
```

## ☸️  Kubernetes Deployment

```bash
# Create namespace
kubectl create namespace genai-prod

# Create secrets
kubectl create secret generic genai-secrets \
  --from-literal=DATABASE_URL="$DB_URL" \
  --from-literal=OPENAI_API_KEY="$OPENAI_KEY" \
  --from-literal=JWT_SECRET_KEY="$JWT_SECRET" \
  -n genai-prod

# Deploy
kubectl apply -f k8s/deployment.yaml -n genai-prod

# Verify
kubectl get pods -n genai-prod
```

## 🔍 Configuration Validation

```bash
# Validate .env file
./setup-config.sh validate .env

# Validate production config
./setup-config.sh validate .env.production

# Check what was loaded (with Python)
python -c "
from app.core.config_loader import ConfigLoader
loader = ConfigLoader(env='development')
settings = loader.load_settings()
print(f'✓ Loaded {len(settings)} settings')
"
```

## 📊 Configuration Categories (Quick Lookup)

| Category | Key Variables | Section |
|----------|---------------|---------|
| **Application** | APP_ENV, PORT, DEBUG | Top |
| **Database** | DATABASE_URL, POOL_SIZE | dev: local psql |
| **Redis** | REDIS_URL, CLUSTER | dev: localhost:6379 |
| **OpenSearch** | OPENSEARCH_HOSTS, USER | dev: localhost:9200 |
| **LLM** | OPENAI_API_KEY, MODEL | gpt-4-turbo default |
| **Security** | JWT_SECRET_KEY, ENCRYPTION | min 32 char secret |
| **Rate Limit** | QPS_LIMIT, BURST_QPS | 5 QPS dev, 20 prod |
| **Observability** | PROMETHEUS_ENABLED, LOG_LEVEL | INFO dev, WARNING prod |

## ⚡ Common Operations

### Generate JWT Secret
```bash
openssl rand -base64 32
# Output: c7d9f2a1e8b3g4h9i2j5k8l1m4n7o0p3q6r9s2t5u8v1w4x7y0z3
```

### Test Database Connection
```bash
psql $DATABASE_URL -c "SELECT version();"
```

### Test Redis Connection
```bash
redis-cli -u "$REDIS_URL" ping
# Should output: PONG
```

### Test Configuration Loading
```bash
export $(cat .env | grep -v '#' | xargs)
python -c "from app.core.settings import get_settings; print('✓ OK')"
```

## 🔒 Security Checklist

- [ ] JWT_SECRET_KEY is 32+ characters
- [ ] OPENAI_API_KEY is not in version control
- [ ] DATABASE_URL uses TLS (sslmode=require)
- [ ] ENCRYPTION_ENABLED is true in production
- [ ] .env file is in .gitignore
- [ ] .env.production is in .gitignore
- [ ] Kubernetes Secrets created (not ConfigMap)
- [ ] Secret rotation job scheduled

## 🚨 Common Issues & Fixes

### Issue: "DATABASE_URL not found"
```bash
# Fix 1: Set directly
export DATABASE_URL="postgresql://..."

# Fix 2: Load from .env
source .env

# Fix 3: Check file exists
ls -la .env
```

### Issue: "JWT_SECRET_KEY must be at least 32 characters"
```bash
# Fix: Generate strong secret
JWT=$(openssl rand -base64 32)
sed -i "s/JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$JWT/" .env
```

### Issue: "Failed to connect to Redis"
```bash
# Fix: Check Redis is running
redis-cli ping

# Fix: Update REDIS_URL
redis-cli -h hostname -p 6379 ping
```

### Issue: "OPENAI_API_KEY is invalid"
```bash
# Fix: Verify key format and permissions
echo $OPENAI_API_KEY  # Should start with 'sk-'
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

## 📚 File References

| What | Where |
|------|-------|
| Dev setup | `.env.example` |
| Prod template | `.env.production` |
| Loader code | `app/core/config_loader.py` |
| Full docs | `CONFIGURATION.md` |
| Checklist | `CONFIGURATION_CHECKLIST.md` |
| Summary | `CONFIG_SUMMARY.md` |

## 🎯 Configuration for Each Environment

### Development (Local)
```ini
APP_ENV=development
DEBUG=true
LOGGING_LEVEL=DEBUG
DEFAULT_QPS_LIMIT=5
DATABASE_URL=postgresql://genai:password@localhost:5432/genai_dev
```

### Staging
```ini
APP_ENV=staging
DEBUG=false
LOGGING_LEVEL=INFO
DEFAULT_QPS_LIMIT=10
DATABASE_URL=${STAGING_DB_URL}  # From secret
```

### Production
```ini
APP_ENV=production
DEBUG=false
LOGGING_LEVEL=WARNING
DEFAULT_QPS_LIMIT=20
DATABASE_URL=${PROD_DB_URL}     # From K8s Secret
KMS_PROVIDER=aws-kms            # Use cloud KMS
```

## 🔄 Secrets Rotation

### AWS Secrets Manager
```bash
# Rotate secret
aws secretsmanager rotate-secret \
  --secret-id genai-platform/prod \
  --rotation-rules AutomaticallyAfterDays=30
```

### Kubernetes Secrets
```bash
# Update secret
kubectl patch secret genai-secrets \
  --type merge \
  -p "{\"data\":{\"JWT_SECRET_KEY\":\"$(echo -n $NEW_SECRET | base64 -w0)\"}}"

# Restart pods to pick up new value
kubectl rollout restart deployment/genai-platform
```

## ✅ Pre-Deployment Checklist

- [ ] All required settings present
- [ ] URLs are correct (no typos)
- [ ] Secrets are strong (32+ chars)
- [ ] Cloud credentials configured
- [ ] Database accessible
- [ ] Redis accessible
- [ ] LLM API key valid
- [ ] Configuration validates without errors

## 📞 Getting Help

**Local Issues**:
```bash
./setup-config.sh validate .env
./setup-config.sh dev    # Interactive setup
```

**Production Issues**:
```bash
# Check mounted secrets
kubectl exec -it <pod-name> -n genai-prod -- env | grep DATABASE

# Check configuration loaded
kubectl logs <pod-name> -n genai-prod | grep "Loading configuration"
```

**Need Reset?**
```bash
# Development
rm .env && cp .env.example .env

# Production
kubectl delete secret genai-secrets -n genai-prod
kubectl create secret generic genai-secrets \
  --from-file=.env.production -n genai-prod
```

---

**Last Updated**: Configuration Phase 2  
**Status**: ✅ Complete and Production-Ready  
**Reference**: See `CONFIGURATION.md` for detailed documentation
