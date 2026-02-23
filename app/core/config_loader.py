"""
Configuration Loading and Validation Utility

This module provides utilities for loading and validating configuration from multiple sources:
1. Environment variables (highest priority)
2. .env files (dev/staging/production)
3. Kubernetes Secrets (production via mounted volumes)
4. Cloud Key Management Services (AWS KMS, Azure Key Vault, Google Secret Manager)

Usage:
    from app.core.config_loader import ConfigLoader
    
    loader = ConfigLoader(env="production")
    settings = loader.load_settings()
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

import boto3
from dotenv import load_dotenv


logger = logging.getLogger(__name__)


class Environment(str, Enum):
    """Deployment environment """
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class ConfigSource:
    """Metadata about a configuration source"""
    name: str
    priority: int  # Higher number = higher priority, overrides lower priority
    sensitive: bool = False  # Hide value in logs
    required: bool = True
    
    
class ConfigValidationError(Exception):
    """Raised when configuration validation fails"""
    pass


class ConfigLoader:
    """
    Comprehensive configuration loader with multi-source support and validation.
    
    Priority order (highest to lowest):
    1. Environment variables (APP_ENV=production)
    2. Cloud KMS (AWS KMS, Azure Key Vault, GCP Secret Manager)
    3. Kubernetes Secrets (mounted as files)
    4. .env files (.env.{environment})
    5. .env.example (fallback defaults)
    """
    
    # Configuration source priority
    SOURCES_PRIORITY = {
        "environment": 100,  # Highest
        "aws_kms": 90,
        "kubernetes_secret": 80,
        ".env.production": 70,
        ".env.staging": 60,
        ".env": 50,
        ".env.example": 10,  # Lowest
    }
    
    # Environment-specific file mappings
    ENV_FILES = {
        Environment.DEVELOPMENT: [".env", ".env.example"],
        Environment.STAGING: [".env.staging", ".env", ".env.example"],
        Environment.PRODUCTION: [".env.production", ".env.example"],
    }
    
    # Sensitive keys that should never be logged
    SENSITIVE_KEYS = {
        "JWT_SECRET_KEY",
        "OPENAI_API_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "OPENSEARCH_PASSWORD",
        "KMS_KEY_ID",
        "AWS_KMS_KEY_ARN",
        "OPENAI_ORG_ID",
    }
    
    # Required keys that must be present in production
    REQUIRED_PRODUCTION_KEYS = {
        "DATABASE_URL",
        "REDIS_URL",
        "OPENAI_API_KEY",
        "JWT_SECRET_KEY",
        "KMS_PROVIDER",
    }
    
    def __init__(self, env: Optional[str] = None, config_dir: str = "."):
        """
        Initialize configuration loader.
        
        Args:
            env: Environment name (development, staging, production)
                 If None, reads from APP_ENV environment variable
            config_dir: Directory containing .env files (default: current dir)
        """
        self.env = Environment(env or os.getenv("APP_ENV", "development"))
        self.config_dir = Path(config_dir)
        self.config: Dict[str, Any] = {}
        self.sources: Dict[str, str] = {}  # Track where each config came from
        
        logger.info(f"Initializing ConfigLoader for environment: {self.env.value}")
    
    def load_settings(self) -> Dict[str, Any]:
        """
        Load settings from all configured sources in priority order.
        
        Returns:
            Dictionary of all configuration settings
            
        Raises:
            ConfigValidationError: If required settings are missing in production
        """
        logger.info(f"Loading configuration from {self.env.value} environment...")
        
        # Load from all sources in priority order
        self._load_env_files()
        self._load_kubernetes_secrets()
        self._load_kms_secrets()
        self._load_environment_variables()
        
        # Validate configuration
        self._validate_configuration()
        
        logger.info(f"Successfully loaded {len(self.config)} configuration keys")
        self._log_configuration_summary()
        
        return self.config
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value with optional default."""
        return self.config.get(key, default)
    
    def get_required(self, key: str) -> Any:
        """Get a required configuration value, raising error if missing."""
        if key not in self.config:
            raise ConfigValidationError(f"Required configuration key missing: {key}")
        return self.config[key]
    
    def _load_env_files(self) -> None:
        """Load configuration from .env files for the current environment."""
        env_files = self.ENV_FILES.get(self.env, [])
        
        for env_file in env_files:
            env_path = self.config_dir / env_file
            
            if env_path.exists():
                logger.info(f"Loading configuration from {env_file}")
                load_dotenv(env_path, override=False)
                
                # Extract loaded variables
                try:
                    with open(env_path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            # Skip comments and empty lines
                            if line and not line.startswith('#'):
                                if '=' in line:
                                    key, value = line.split('=', 1)
                                    key = key.strip()
                                    value = value.strip().strip('"\'')
                                    
                                    # Skip if already loaded from higher priority source
                                    if key not in self.config:
                                        self.config[key] = value
                                        self.sources[key] = env_file
                except Exception as e:
                    logger.warning(f"Error parsing {env_file}: {e}")
            else:
                logger.debug(f"Configuration file not found: {env_file}")
    
    def _load_kubernetes_secrets(self) -> None:
        """Load configuration from Kubernetes Secret mounted volumes."""
        if self.env != Environment.PRODUCTION:
            return
        
        # Standard Kubernetes Secret mount path
        secret_path = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        
        # Custom application secrets path
        app_secret_path = Path("/etc/secrets/genai-config")
        
        for base_path in [app_secret_path, secret_path]:
            if base_path.exists():
                logger.info(f"Loading Kubernetes Secrets from {base_path}")
                
                for secret_file in base_path.glob("*"):
                    if secret_file.is_file():
                        key = secret_file.name.upper()
                        try:
                            value = secret_file.read_text().strip()
                            
                            # Only use if not already loaded from higher priority
                            if key not in self.config:
                                self.config[key] = value
                                self.sources[key] = f"K8S Secret: {secret_file}"
                        except Exception as e:
                            logger.warning(
                                f"Error reading Kubernetes Secret {secret_file.name}: {e}"
                            )
    
    def _load_kms_secrets(self) -> None:
        """Load encrypted secrets from cloud KMS."""
        kms_provider = os.getenv("KMS_PROVIDER", "").lower()
        
        if kms_provider == "aws-kms":
            self._load_aws_kms_secrets()
        elif kms_provider == "azure-keyvault":
            self._load_azure_keyvault_secrets()
        elif kms_provider == "gcp-secret-manager":
            self._load_gcp_secrets()
    
    def _load_aws_kms_secrets(self) -> None:
        """Load secrets from AWS KMS."""
        try:
            aws_region = os.getenv("AWS_KMS_REGION", "us-east-1")
            secret_name = os.getenv("AWS_SECRET_NAME", "genai-platform/secrets")
            
            logger.info(f"Loading secrets from AWS Secrets Manager: {secret_name}")
            
            client = boto3.client("secretsmanager", region_name=aws_region)
            response = client.get_secret_value(SecretId=secret_name)
            
            if "SecretString" in response:
                secrets = json.loads(response["SecretString"])
                
                for key, value in secrets.items():
                    # Only use if not already loaded from higher priority
                    if key not in self.config:
                        self.config[key] = str(value)
                        self.sources[key] = "AWS Secrets Manager"
                
                logger.info(f"Loaded {len(secrets)} secrets from AWS Secrets Manager")
        except Exception as e:
            logger.warning(f"Failed to load AWS KMS secrets: {e}")
    
    def _load_azure_keyvault_secrets(self) -> None:
        """Load secrets from Azure Key Vault."""
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
            
            vault_url = os.getenv("AZURE_KEYVAULT_URL")
            if not vault_url:
                logger.warning("AZURE_KEYVAULT_URL not set, skipping Azure Key Vault")
                return
            
            logger.info(f"Loading secrets from Azure Key Vault: {vault_url}")
            
            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=vault_url, credential=credential)
            
            # List all secrets (may require permissions)
            for secret_properties in client.list_properties_of_secrets():
                try:
                    secret = client.get_secret(secret_properties.name)
                    key = secret_properties.name.upper().replace("-", "_")
                    
                    if key not in self.config:
                        self.config[key] = secret.value
                        self.sources[key] = "Azure Key Vault"
                except Exception as e:
                    logger.warning(f"Error loading secret {secret_properties.name}: {e}")
        except ImportError:
            logger.warning("Azure SDK not installed, skipping Azure Key Vault")
        except Exception as e:
            logger.warning(f"Failed to load Azure Key Vault secrets: {e}")
    
    def _load_gcp_secrets(self) -> None:
        """Load secrets from Google Cloud Secret Manager."""
        try:
            from google.cloud import secretmanager
            
            project_id = os.getenv("GCP_PROJECT_ID")
            if not project_id:
                logger.warning("GCP_PROJECT_ID not set, skipping GCP Secret Manager")
                return
            
            logger.info(f"Loading secrets from GCP Secret Manager (project: {project_id})")
            
            client = secretmanager.SecretManagerServiceClient()
            
            # List secrets (may require permissions)
            parent = f"projects/{project_id}"
            for secret in client.list_secrets(request={"parent": parent}):
                try:
                    secret_name = secret.name.split("/")[-1].upper()
                    secret_version = client.access_secret_version(
                        request={"name": f"{secret.name}/versions/latest"}
                    )
                    value = secret_version.payload.data.decode("UTF-8")
                    
                    if secret_name not in self.config:
                        self.config[secret_name] = value
                        self.sources[secret_name] = "GCP Secret Manager"
                except Exception as e:
                    logger.warning(f"Error loading secret {secret.name}: {e}")
        except ImportError:
            logger.warning("Google Cloud SDK not installed, skipping GCP Secret Manager")
        except Exception as e:
            logger.warning(f"Failed to load GCP Secret Manager secrets: {e}")
    
    def _load_environment_variables(self) -> None:
        """Load configuration from OS environment variables (highest priority)."""
        logger.debug("Loading configuration from environment variables")
        
        for key, value in os.environ.items():
            # Only consider uppercase keys (convention for config)
            if key.isupper() and any(x in key for x in ["APP_", "DB_", "REDIS_", "OPEN", "FAISS_", "LLM_", "JWT_", "ENCRYPTION_", "KMS_", "AWS_", "OPENAI_"]):
                self.config[key] = value
                self.sources[key] = "Environment Variable"
    
    def _validate_configuration(self) -> None:
        """Validate configuration for completeness and correctness."""
        logger.info("Validating configuration...")
        
        # Check required keys in production
        if self.env == Environment.PRODUCTION:
            missing_keys = []
            for key in self.REQUIRED_PRODUCTION_KEYS:
                if key not in self.config or not self.config[key]:
                    missing_keys.append(key)
            
            if missing_keys:
                raise ConfigValidationError(
                    f"Missing required configuration in production: {missing_keys}"
                )
        
        # Validate database URL format
        if "DATABASE_URL" in self.config:
            db_url = self.config["DATABASE_URL"]
            if not db_url.startswith("postgresql://") and not db_url.startswith("postgresql+psycopg2://"):
                logger.warning(f"DATABASE_URL may be invalid: {db_url[:20]}...")
        
        # Validate Redis URL
        if "REDIS_URL" in self.config:
            redis_url = self.config["REDIS_URL"]
            if not redis_url.startswith("redis://") and not redis_url.startswith("rediss://"):
                logger.warning(f"REDIS_URL may be invalid: {redis_url[:20]}...")
        
        # Validate JWT secret strength
        if "JWT_SECRET_KEY" in self.config:
            jwt_secret = self.config["JWT_SECRET_KEY"]
            if len(jwt_secret) < 32:
                raise ConfigValidationError(
                    "JWT_SECRET_KEY must be at least 32 characters in production"
                )
        
        # Validate numeric values
        numeric_keys = {
            "PORT": 1,
            "WORKERS": 1,
            "DATABASE_POOL_SIZE": 1,
            "REDIS_SOCKET_TIMEOUT": 1,
            "MAX_QUEUE_DEPTH": 1,
            "WORKER_POOL_SIZE": 1,
        }
        
        for key, min_val in numeric_keys.items():
            if key in self.config:
                try:
                    val = int(self.config[key])
                    if val < min_val:
                        logger.warning(f"{key} value {val} is below recommended minimum {min_val}")
                except ValueError:
                    logger.warning(f"{key} has non-numeric value: {self.config[key]}")
        
        logger.info("Configuration validation passed")
    
    def _log_configuration_summary(self) -> None:
        """Log configuration summary (without sensitive values)."""
        logger.info(f"Configuration Summary for {self.env.value} environment:")
        
        # Group by source
        by_source = {}
        for key, source in self.sources.items():
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(key)
        
        for source, keys in sorted(by_source.items()):
            logger.info(f"  {source}: {len(keys)} settings")
            
            # Log sample non-sensitive keys
            sample_keys = [k for k in keys[:3] if k not in self.SENSITIVE_KEYS]
            if sample_keys:
                logger.debug(f"    Examples: {', '.join(sample_keys)}")
    
    def export_config_map(self, exclude_sensitive: bool = True) -> Dict[str, str]:
        """
        Export configuration as Kubernetes ConfigMap-compatible format.
        
        Args:
            exclude_sensitive: If True, exclude sensitive keys (passwords, keys, etc.)
            
        Returns:
            Dictionary suitable for Kubernetes ConfigMap
        """
        config_map = {}
        
        for key, value in self.config.items():
            if exclude_sensitive and key in self.SENSITIVE_KEYS:
                continue
            
            config_map[key] = str(value)
        
        return config_map
    
    def export_env_file(self, output_path: str, exclude_sensitive: bool = False) -> None:
        """
        Export configuration to .env file format.
        
        Args:
            output_path: Path to write .env file
            exclude_sensitive: If True, skip sensitive keys (use for repos)
        """
        with open(output_path, 'w') as f:
            f.write(f"# Generated configuration file\n")
            f.write(f"# Environment: {self.env.value}\n")
            f.write(f"# Generated: {Path(__file__).stat().st_mtime}\n\n")
            
            for key in sorted(self.config.keys()):
                if exclude_sensitive and key in self.SENSITIVE_KEYS:
                    f.write(f"# {key}=***REDACTED***\n")
                else:
                    value = self.config[key]
                    # Quote values with spaces
                    if ' ' in str(value):
                        f.write(f'{key}="{value}"\n')
                    else:
                        f.write(f'{key}={value}\n')
        
        logger.info(f"Exported configuration to {output_path}")


def get_config_loader(env: Optional[str] = None) -> ConfigLoader:
    """Factory function to create a ConfigLoader instance."""
    return ConfigLoader(env=env)
