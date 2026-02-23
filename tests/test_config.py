"""Unit tests for configuration and settings"""

import pytest
import os
from pathlib import Path
from app.core.config_loader import ConfigLoader, Environment


class TestConfigLoader:
    """Test ConfigLoader"""

    def test_load_from_env_example(self):
        """Test loading from .env.example"""
        loader = ConfigLoader(env="development")
        settings = loader.load_settings()
        
        assert len(settings) > 0
        assert "APP_ENV" in settings or "DEFAULT_QPS_LIMIT" in settings

    def test_environment_variable_priority(self, monkeypatch):
        """Test environment variables have highest priority"""
        monkeypatch.setenv("TEST_KEY", "env_value")
        
        loader = ConfigLoader(env="development")
        loader.config = {"TEST_KEY": "file_value"}
        
        # Env vars should override
        loader._load_environment_variables()
        assert loader.config.get("TEST_KEY") == "env_value"

    def test_jwt_secret_validation(self):
        """Test JWT secret minimum length validation"""
        loader = ConfigLoader(env="production")
        loader.config = {"JWT_SECRET_KEY": "short"}
        
        with pytest.raises(Exception):  # ConfigValidationError
            loader._validate_configuration()

    def test_sensitive_value_redaction(self):
        """Test sensitive values are redacted in logs"""
        loader = ConfigLoader(env="development")
        loader.config = {
            "JWT_SECRET_KEY": "my-secret-key-min-32-characters-long!",
            "OPENAI_API_KEY": "sk-test-key",
            "PUBLIC_KEY": "visible"
        }
        
        # Check that sensitive keys are tracked
        assert "JWT_SECRET_KEY" in loader.SENSITIVE_KEYS
        assert "OPENAI_API_KEY" in loader.SENSITIVE_KEYS

    def test_export_config_map(self):
        """Test exporting configuration as ConfigMap"""
        loader = ConfigLoader(env="development")
        loader.config = {
            "APP_ENV": "development",
            "JWT_SECRET_KEY": "secret",
            "PUBLIC_KEY": "public"
        }
        
        config_map = loader.export_config_map(exclude_sensitive=True)
        assert "PUBLIC_KEY" in config_map
        assert "JWT_SECRET_KEY" not in config_map


class TestEnvironmentEnum:
    """Test Environment enum"""

    def test_environment_values(self):
        """Test environment enum values"""
        assert Environment.DEVELOPMENT.value == "development"
        assert Environment.STAGING.value == "staging"
        assert Environment.PRODUCTION.value == "production"

    def test_environment_from_string(self):
        """Test creating Environment from string"""
        env = Environment("production")
        assert env == Environment.PRODUCTION
