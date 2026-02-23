# Enterprise Multi-Tenant GenAI Platform - Configuration Management Guide
# =====================================================================

## Overview

The application supports multiple configuration sources with a clear priority order:

1. **Environment Variables** (highest priority - overrides everything)
2. **Cloud KMS** (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager)
3. **Kubernetes Secrets** (mounted at /etc/secrets)
4. **.env.{environment} files** (dev/.env, staging/.env.staging, prod/.env.production)
5. **.env.example** (defaults - lowest priority)

## Development Environment

```bash
# 1. Copy example file
cp .env.example .env

# 2. Update with your local values
# Minimal requirements:
DATABASE_URL=postgresql://user:password@localhost:5432/genai_platform
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=sk-...
JWT_SECRET_KEY=your-secret-key-min-32-chars

# 3. Load environment
export $(cat .env | grep -v '#' | xargs)

# 4. Run application
python -m app.main
```

## Staging Environment

```bash
# Create staging-specific overrides
cat > .env.staging << 'EOF'
APP_ENV=staging
DEBUG=false
LOGGING_LEVEL=INFO
DEFAULT_QPS_LIMIT=10
DATABASE_URL=${STAGING_DB_URL}
REDIS_URL=${STAGING_REDIS_URL}
OPENAI_API_KEY=${STAGING_OPENAI_KEY}
EOF

# Deploy with staging config
docker build -t genai-platform:staging .
docker run -e APP_ENV=staging \
  --env-file .env.staging \
  -v /etc/secrets/genai-config:/etc/secrets/genai-config:ro \
  genai-platform:staging
```

## Production Deployment with Kubernetes

### 1. Create Namespace

```bash
kubectl create namespace genai-prod
```

### 2. Create Secrets from .env.production

```bash
# Create generic secret from file
kubectl create secret generic genai-config \
  --from-file=.env.production \
  -n genai-prod

# Or create individual secrets for sensitive values
kubectl create secret generic genai-secrets \
  --from-literal=DATABASE_URL="postgresql://..." \
  --from-literal=REDIS_URL="redis://..." \
  --from-literal=OPENAI_API_KEY="sk-..." \
  --from-literal=JWT_SECRET_KEY="$(openssl rand -base64 32)" \
  -n genai-prod

# Verify secret was created
kubectl get secrets -n genai-prod
kubectl describe secret genai-secrets -n genai-prod
```

### 3. Create ConfigMap for Non-Sensitive Settings

```bash
# Extract non-sensitive config to separate file
grep -v "API_KEY\|PASSWORD\|SECRET\|TOKEN" .env.production > .env.configmap

# Create ConfigMap
kubectl create configmap genai-config \
  --from-file=.env.configmap \
  -n genai-prod

# Verify
kubectl get configmap genai-config -n genai-prod
```

### 4. Deployment Manifest with Secret Injection

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: genai-app-config
  namespace: genai-prod
data:
  APP_ENV: "production"
  LOG_LEVEL: "WARNING"
  PROMETHEUS_PORT: "8001"
  # Non-sensitive settings from .env.production
  OPENSEARCH_HOSTS: "opensearch.genai-prod.svc.cluster.local:9200"
  OPENSEARCH_VERIFY_CERTS: "true"

---
apiVersion: v1
kind: Secret
metadata:
  name: genai-secrets
  namespace: genai-prod
type: Opaque
stringData:
  DATABASE_URL: "postgresql://user:password@postgres.genai-prod.svc.cluster.local/genai_prod"
  REDIS_URL: "redis://redis.genai-prod.svc.cluster.local:6379/0"
  OPENAI_API_KEY: "sk-..."
  JWT_SECRET_KEY: "..."  # Use $(openssl rand -base64 32)
  OPENSEARCH_PASSWORD: "..."
  KMS_KEY_ID: "arn:aws:kms:us-east-1:ACCOUNT:key/KEY_ID"

---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: genai-platform
  namespace: genai-prod
spec:
  serviceName: genai-platform
  replicas: 3
  selector:
    matchLabels:
      app: genai-platform
  template:
    metadata:
      labels:
        app: genai-platform
    spec:
      serviceAccountName: genai-platform
      containers:
      - name: genai-platform
        image: genai-platform:v1.0.0
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 8000
          name: http
          protocol: TCP
        - containerPort: 8001
          name: metrics
          protocol: TCP
        
        # Health checks
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 2
        
        # Configuration from ConfigMap
        envFrom:
        - configMapRef:
            name: genai-app-config
        
        # Sensitive values from Secret
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: genai-secrets
              key: DATABASE_URL
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: genai-secrets
              key: REDIS_URL
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: genai-secrets
              key: OPENAI_API_KEY
        - name: JWT_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: genai-secrets
              key: JWT_SECRET_KEY
        - name: OPENSEARCH_PASSWORD
          valueFrom:
            secretKeyRef:
              name: genai-secrets
              key: OPENSEARCH_PASSWORD
        - name: KMS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: genai-secrets
              key: KMS_KEY_ID
        
        # Pod metadata for configuration
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        
        # Resource limits
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "2000m"
            memory: "4Gi"
        
        # Security context
        securityContext:
          runAsNonRoot: true
          runAsUser: 1000
          readOnlyRootFilesystem: true
          allowPrivilegeEscalation: false
          capabilities:
            drop:
            - ALL
        
        # Volume mounts
        volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: cache
          mountPath: /app/cache
        - name: secrets
          mountPath: /etc/secrets/genai-config
          readOnly: true
      
      # Pod security policy
      securityContext:
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      
      # Volumes
      volumes:
      - name: tmp
        emptyDir: {}
      - name: cache
        emptyDir: {}
      - name: secrets
        secret:
          secretName: genai-secrets
          defaultMode: 0400

---
apiVersion: v1
kind: Service
metadata:
  name: genai-platform
  namespace: genai-prod
  labels:
    app: genai-platform
spec:
  ports:
  - port: 8000
    targetPort: 8000
    protocol: TCP
    name: http
  - port: 8001
    targetPort: 8001
    protocol: TCP
    name: metrics
  clusterIP: None  # Headless service for StatefulSet
  selector:
    app: genai-platform

---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: genai-platform-pdb
  namespace: genai-prod
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: genai-platform

---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: genai-platform-hpa
  namespace: genai-prod
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: genai-platform
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 100
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Pods
        value: 1
        periodSeconds: 60
```

### 5. Secret Rotation Strategy

```bash
#!/bin/bash
# rotate-secrets.sh - Rotate secrets monthly

NAMESPACE=genai-prod
SECRET_NAME=genai-secrets

# Generate new values
NEW_JWT_SECRET=$(openssl rand -base64 32)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Backup old secret
kubectl get secret $SECRET_NAME -n $NAMESPACE -o yaml > secret_backup_$TIMESTAMP.yaml

# Update secret
kubectl patch secret $SECRET_NAME -n $NAMESPACE \
  --type merge \
  -p "{\"data\":{\"JWT_SECRET_KEY\":\"$(echo -n $NEW_JWT_SECRET | base64 -w0)\"}}"

# Trigger pod restart to pick up new values
kubectl rollout restart deployment/genai-platform -n $NAMESPACE

# Verify rollout
kubectl rollout status deployment/genai-platform -n $NAMESPACE
```

## Environment-Specific Deployment

### Development (Local)
```bash
APP_ENV=development python -m app.main
```

### Staging (Docker)
```bash
docker build -t genai-platform:staging .
docker run -e APP_ENV=staging --env-file .env.staging genai-platform:staging
```

### Production (Kubernetes)
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
```

## Configuration Best Practices

### 1. Secrets Management
```bash
# ✅ DO: Use Kubernetes Secrets for sensitive data
kubectl create secret generic app-secrets \
  --from-literal=API_KEY="..." \
  --from-literal=DB_PASSWORD="..."

# ❌ DON'T: Commit secrets to Git
# ❌ DON'T: Use plain text .env in production
# ❌ DON'T: Pass secrets as command-line arguments
```

### 2. Configuration Validation
```python
from app.core.config_loader import ConfigLoader

loader = ConfigLoader(env="production")
try:
    settings = loader.load_settings()
except ConfigValidationError as e:
    logger.error(f"Configuration invalid: {e}")
    sys.exit(1)
```

### 3. Environment-Specific Overrides
```bash
# Different settings per environment
# Development: DEBUG=true, LOG_LEVEL=DEBUG, smaller pools
# Staging: DEBUG=false, LOG_LEVEL=INFO, medium pools
# Production: DEBUG=false, LOG_LEVEL=WARNING, large pools, all checks
```

### 4. Hot Reloading (for ConfigMap changes)
```yaml
# Add annotation to trigger pod restart on ConfigMap change
apiVersion: apps/v1
kind: Deployment
metadata:
  name: genai-platform
spec:
  template:
    metadata:
      annotations:
        configmap.reloader/watch: "genai-config"
    spec:
      # ... rest of spec
```

## Common Configuration Issues

### Issue: "Required configuration key missing: DATABASE_URL"
**Solution**: 
```bash
# Check if DATABASE_URL is set
echo $DATABASE_URL

# Load from .env file
source .env

# Or set directly
export DATABASE_URL="postgresql://..."
```

### Issue: "JWT_SECRET_KEY must be at least 32 characters"
**Solution**:
```bash
# Generate proper secret
NEW_SECRET=$(openssl rand -base64 32)
echo "JWT_SECRET_KEY=$NEW_SECRET" >> .env.production
```

### Issue: "Failed to load AWS KMS secrets"
**Solution**:
```bash
# Check AWS credentials
aws sts get-caller-identity

# Verify KMS key exists
aws kms describe-key --key-id $KMS_KEY_ID

# Check IAM permissions for secretsmanager
aws secretsmanager describe-secret --secret-id genai-platform/secrets
```

## Configuration Testing

```bash
# Test configuration loading
python -c "
from app.core.config_loader import ConfigLoader
loader = ConfigLoader(env='development')
config = loader.load_settings()
print(f'Loaded {len(config)} configuration keys')
print('✅ Configuration valid')
"

# Test specific settings
python -c "
from app.core.settings import get_settings
settings = get_settings()
print(f'API: {settings.host}:{settings.port}')
print(f'Database: {settings.database_url[:50]}...')
print(f'Redis: {settings.redis_url}')
"
```

## Sensitive Configuration Management

### For AWS Deployments
```bash
# Use AWS Secrets Manager
aws secretsmanager create-secret \
  --name genai-platform/prod \
  --secret-string file://.env.production

# Attach to ECS/EKS via IAM role
# Pod will automatically load via config_loader.py
```

### For Azure Deployments
```bash
# Use Azure Key Vault
az keyvault secret set \
  --vault-name genai-keyvault \
  --name DATABASE-URL \
  --value "postgresql://..."

# Access via DefaultAzureCredential
```

### For Multi-Cloud
```bash
# Store provider credentials in Kubernetes Secret
kubectl create secret generic cloud-credentials \
  --from-literal=AWS_ACCESS_KEY_ID="..." \
  --from-literal=AZURE_SUBSCRIPTION_ID="..." \
  --from-literal=GCP_PROJECT_ID="..."
```

## Monitoring Configuration

```bash
# Monitor where configuration comes from
kubectl logs -n genai-prod deployment/genai-platform | grep "Loading configuration"

# Check which secrets are mounted
kubectl exec -n genai-prod <pod-name> -- ls -la /etc/secrets/genai-config

# Verify config was loaded
kubectl exec -n genai-prod <pod-name> -- env | grep -E "APP_ENV|DATABASE"
```
