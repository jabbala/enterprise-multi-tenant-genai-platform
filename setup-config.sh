#!/usr/bin/env bash
# Configuration Quick Start Script
# ================================
# This script helps setup the configuration for development, staging, or production

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Enterprise Multi-Tenant GenAI Platform                    ║${NC}"
echo -e "${BLUE}║  Configuration Quick Start                                ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Function to print section headers
print_header() {
    echo ""
    echo -e "${BLUE}→ $1${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Function to print success
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print warning
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Function to print error
print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Detect current environment
detect_environment() {
    if [ ! -z "$APP_ENV" ]; then
        echo "$APP_ENV"
    elif [ -f ".env.production" ] && [ -f ".env.staging" ]; then
        echo "development"  # Multiple env files suggest dev setup
    else
        echo "development"  # Default
    fi
}

# Setup for development
setup_development() {
    print_header "Setting Up Development Environment"
    
    # Check if .env exists
    if [ -f ".env" ]; then
        print_warning ".env already exists"
        read -p "Overwrite? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_success "Skipped .env creation"
            return 0
        fi
    fi
    
    # Copy example file
    cp .env.example .env
    print_success "Created .env from .env.example"
    
    # Ask for critical values
    echo ""
    echo "Configure critical settings for local development:"
    echo ""
    
    read -p "Database URL [postgresql://genai:genai_password@localhost:5432/genai_platform]: " DB_URL
    DB_URL=${DB_URL:-postgresql://genai:genai_password@localhost:5432/genai_platform}
    sed -i "s|DATABASE_URL=.*|DATABASE_URL=$DB_URL|" .env
    
    read -p "Redis URL [redis://localhost:6379/0]: " REDIS_URL
    REDIS_URL=${REDIS_URL:-redis://localhost:6379/0}
    sed -i "s|REDIS_URL=.*|REDIS_URL=$REDIS_URL|" .env
    
    read -s -p "OpenAI API Key [required]: " OPENAI_KEY
    if [ -z "$OPENAI_KEY" ]; then
        print_error "OpenAI API key is required"
        return 1
    fi
    echo
    sed -i "s|OPENAI_API_KEY=.*|OPENAI_API_KEY=$OPENAI_KEY|" .env
    print_success "Set OPENAI_API_KEY"
    
    # Generate JWT secret
    JWT_SECRET=$(openssl rand -base64 32)
    sed -i "s|JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$JWT_SECRET|" .env
    print_success "Generated JWT_SECRET_KEY ($(echo -n $JWT_SECRET | wc -c) chars)"
    
    # Load environment
    export $(cat .env | grep -v '#' | xargs)
    print_success "Loaded .env into environment"
    
    echo ""
    print_success "Development configuration complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Verify database is running: psql \$DATABASE_URL -c 'SELECT version();'"
    echo "  2. Verify Redis is running: redis-cli ping"
    echo "  3. Start application: python -m app.main"
}

# Setup for staging
setup_staging() {
    print_header "Setting Up Staging Environment"
    
    # Check if .env.staging exists
    if [ ! -f ".env.staging" ]; then
        print_error ".env.staging not found"
        echo "Copy from: cp .env.example .env.staging"
        return 1
    fi
    
    print_success "Found .env.staging"
    
    # Verify staging-specific settings
    echo ""
    echo "Verifying staging configuration:"
    
    # Check critical settings
    if grep -q "APP_ENV=staging" .env.staging; then
        print_success "APP_ENV=staging"
    else
        print_warning "APP_ENV not set to 'staging', updating..."
        sed -i 's/APP_ENV=.*/APP_ENV=staging/' .env.staging
    fi
    
    if grep -q "DEBUG=false" .env.staging; then
        print_success "DEBUG=false"
    else
        print_warning "DEBUG not disabled, updating..."
        sed -i 's/DEBUG=.*/DEBUG=false/' .env.staging
    fi
    
    # Load and validate
    export $(cat .env.staging | grep -v '#' | xargs)
    
    echo ""
    print_success "Staging configuration validated!"
    echo ""
    echo "To deploy staging:"
    echo "  docker build -t genai-platform:staging ."
    echo "  docker run -e APP_ENV=staging --env-file .env.staging genai-platform:staging"
}

# Setup for production
setup_production() {
    print_header "Setting Up Production Environment"
    
    print_warning "⚠️  PRODUCTION SETUP - Handle with care!"
    echo ""
    
    # Confirm production
    read -p "Are you SURE you want to setup PRODUCTION? Type 'yes' to confirm: " confirm
    if [ "$confirm" != "yes" ]; then
        print_warning "Production setup cancelled"
        return 1
    fi
    
    echo ""
    
    # Check .env.production
    if [ ! -f ".env.production" ]; then
        print_error ".env.production not found"
        return 1
    fi
    
    print_success "Found .env.production"
    
    # Verify all required keys are set
    print_header "Validating Required Production Settings"
    
    REQUIRED_KEYS=(
        "DATABASE_URL"
        "REDIS_URL"
        "OPENAI_API_KEY"
        "JWT_SECRET_KEY"
        "KMS_PROVIDER"
    )
    
    MISSING=0
    for key in "${REQUIRED_KEYS[@]}"; do
        # Check both plain and environment variable
        if grep -q "^$key=" .env.production; then
            VALUE=$(grep "^$key=" .env.production | cut -d'=' -f2)
            if [ "$VALUE" = "\${$key}" ] || [ -z "$VALUE" ]; then
                print_warning "$key not set (requires environment variable)"
            else
                print_success "$key is configured"
            fi
        else
            print_error "$key not found in .env.production"
            MISSING=$((MISSING + 1))
        fi
    done
    
    if [ $MISSING -gt 0 ]; then
        print_error "$MISSING required settings missing"
        return 1
    fi
    
    # Check JWT secret strength
    print_header "Validating Security Settings"
    
    JWT_SECRET=$(grep "^JWT_SECRET_KEY=" .env.production | cut -d'=' -f2)
    if [ ! -z "$JWT_SECRET" ] && [ "$JWT_SECRET" != "\${JWT_SECRET_KEY}" ]; then
        JWT_LEN=${#JWT_SECRET}
        if [ $JWT_LEN -ge 32 ]; then
            print_success "JWT_SECRET_KEY is strong (${JWT_LEN} chars)"
        else
            print_error "JWT_SECRET_KEY is too short (${JWT_LEN} chars, need 32+)"
            return 1
        fi
    fi
    
    # Kubernetes setup
    print_header "Kubernetes Configuration"
    
    read -p "Kubernetes namespace [genai-prod]: " K8S_NS
    K8S_NS=${K8S_NS:-genai-prod}
    
    # Create secrets script
    cat > create-k8s-secrets.sh << 'SCRIPT'
#!/bin/bash
# Auto-generated Kubernetes secrets creation script

NAMESPACE=$1
if [ -z "$NAMESPACE" ]; then
    echo "Usage: ./create-k8s-secrets.sh <namespace>"
    exit 1
fi

echo "Creating Kubernetes namespace and secrets..."
kubectl create namespace $NAMESPACE || true

# Create secrets from .env.production
kubectl create secret generic genai-secrets \
    --from-file=.env.production \
    -n $NAMESPACE \
    --dry-run=client -o yaml | kubectl apply -f -

echo "✓ Secrets created in namespace: $NAMESPACE"
kubectl get secrets -n $NAMESPACE
SCRIPT
    
    chmod +x create-k8s-secrets.sh
    print_success "Created create-k8s-secrets.sh"
    
    echo ""
    print_success "Production configuration prepared!"
    echo ""
    echo "Next steps:"
    echo "  1. Review .env.production and update placeholder values"
    echo "  2. Generate strong JWT secret: openssl rand -base64 32"
    echo "  3. Setup Kubernetes: ./create-k8s-secrets.sh $K8S_NS"
    echo "  4. Deploy: kubectl apply -f k8s/deployment.yaml"
    echo ""
    echo "⚠️  IMPORTANT:"
    echo "  - Never commit .env.production to git"
    echo "  - Rotate JWT_SECRET_KEY on a regular basis"
    echo "  - Store .env.production in secure backup"
}

# Validate configuration
validate_config() {
    print_header "Validating Configuration"
    
    ENV_FILE="${1:-.env}"
    
    if [ ! -f "$ENV_FILE" ]; then
        print_error "Configuration file not found: $ENV_FILE"
        return 1
    fi
    
    print_success "Found $ENV_FILE"
    
    # Count settings
    COUNT=$(grep -c "^[A-Z_]*=" "$ENV_FILE" || true)
    print_success "Found $COUNT configuration settings"
    
    # Check for required keys
    REQUIRED=("DATABASE_URL" "REDIS_URL" "JWT_SECRET_KEY")
    MISSING=0
    
    for key in "${REQUIRED[@]}"; do
        if grep -q "^$key=" "$ENV_FILE"; then
            print_success "✓ $key present"
        else
            print_warning "✗ $key missing"
            MISSING=$((MISSING + 1))
        fi
    done
    
    if [ $MISSING -eq 0 ]; then
        print_success "All required settings present"
        return 0
    else
        print_warning "$MISSING required settings missing"
        return 1
    fi
}

# Main menu
if [ "$1" = "dev" ] || [ "$1" = "development" ]; then
    setup_development
elif [ "$1" = "staging" ]; then
    setup_staging
elif [ "$1" = "prod" ] || [ "$1" = "production" ]; then
    setup_production
elif [ "$1" = "validate" ]; then
    validate_config "${2:-.env}"
elif [ -z "$1" ]; then
    # Interactive menu
    echo "Choose configuration environment:"
    echo ""
    echo "  1) Development (local)"
    echo "  2) Staging"
    echo "  3) Production"
    echo ""
    read -p "Enter choice (1-3): " choice
    
    case $choice in
        1) setup_development ;;
        2) setup_staging ;;
        3) setup_production ;;
        *) print_error "Invalid choice" ;;
    esac
else
    print_error "Unknown command: $1"
    echo ""
    echo "Usage: $0 [dev|staging|prod|validate] [file]"
    exit 1
fi

echo ""
