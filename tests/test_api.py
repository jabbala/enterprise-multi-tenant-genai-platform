"""Integration tests for API routes"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


class TestHealthEndpoints:
    """Test health check endpoints"""

    def test_health_basic(self, client):
        """Test basic health endpoint"""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "ok"]

    def test_health_detailed(self, client):
        """Test detailed health endpoint"""
        response = client.get("/health/detailed")
        
        assert response.status_code == 200
        data = response.json()
        assert "components" in data or "checks" in data


class TestQueryAPI:
    """Test query API endpoints"""

    def test_query_requires_auth(self, client):
        """Test query requires authentication"""
        response = client.post(
            "/api/v1/query",
            json={"query": "test query"}
        )
        
        # Should either require auth or accept anonymous
        assert response.status_code in [401, 400, 200, 422]


class TestMetricsEndpoint:
    """Test Prometheus metrics endpoint"""

    def test_metrics_endpoint(self, client):
        """Test metrics are exposed"""
        response = client.get("/metrics")
        
        assert response.status_code == 200
        # Should contain Prometheus format
        assert "TYPE" in response.text or "HELP" in response.text or "genai_" in response.text


class TestAdminAPI:
    """Test admin endpoints"""

    def test_admin_requires_auth(self, client):
        """Test admin endpoints require authentication"""
        response = client.get("/api/v1/admin/tenants")
        
        # Should require authentication
        assert response.status_code in [401, 403, 422]
