"""Locust load testing suite for multi-tenant GenAI platform"""
from locust import HttpUser, task, between, events
from random import choice, uniform
import json
import time
import statistics

# Test data
TENANTS = ["tenant-001", "tenant-002", "tenant-003", "tenant-004", "tenant-005"]
USERS = {
    "tenant-001": ["user-a1", "user-a2"],
    "tenant-002": ["user-b1", "user-b2"],
    "tenant-003": ["user-c1", "user-c2"],
    "tenant-004": ["user-d1", "user-d2"],
    "tenant-005": ["user-e1", "user-e2"],
}

SAMPLE_QUERIES = [
    "What are the main features of our cloud infrastructure?",
    "How do I configure multi-tenant isolation?",
    "What is the RAG architecture used?",
    "How do I deploy to Kubernetes?",
    "What are the security best practices?",
    "How do I monitor the system?",
    "What authentication methods are supported?",
    "How do I scale the application?",
    "What metrics are available?",
    "How do I configure cost tracking?",
]

# Metrics collection
response_times = []
error_count = 0
success_count = 0


class GenAIUser(HttpUser):
    """Simulates a multi-tenant user"""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Called when a User starts"""
        self.tenant_id = choice(TENANTS)
        self.user_id = choice(USERS[self.tenant_id])
        self.token = None
        
        # Mock JWT token for testing
        self.token = f"Bearer mock-jwt-token-{self.tenant_id}"
    
    @task(70)  # 70% of requests
    def query_endpoint(self):
        """Test the query endpoint"""
        global response_times, success_count, error_count
        
        query_text = choice(SAMPLE_QUERIES)
        
        headers = {
            "X-Tenant-ID": self.tenant_id,
            "X-User-ID": self.user_id,
            "Authorization": self.token,
            "Content-Type": "application/json",
        }
        
        payload = {"query": query_text}
        
        start_time = time.time()
        
        with self.client.post(
            "/api/query",
            json=payload,
            headers=headers,
            catch_response=True,
            timeout=10,
        ) as response:
            duration = (time.time() - start_time) * 1000  # Convert to ms
            response_times.append(duration)
            
            if response.status_code == 200:
                success_count += 1
                
                # Verify response structure
                try:
                    data = response.json()
                    if "answer" in data and "sources" in data and data["tenant_id"] == self.tenant_id:
                        response.success()
                    else:
                        error_count += 1
                        response.failure("Invalid response structure")
                except json.JSONDecodeError:
                    error_count += 1
                    response.failure("Invalid JSON response")
            else:
                error_count += 1
                response.failure(f"HTTP {response.status_code}")
    
    @task(15)  # 15% of requests
    def health_check(self):
        """Test the health endpoint"""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")
    
    @task(10)  # 10% of requests
    def metrics_endpoint(self):
        """Test the metrics endpoint"""
        with self.client.get("/metrics", catch_response=True) as response:
            if response.status_code == 200 and "genai_queries_total" in response.text:
                response.success()
            else:
                response.failure("Metrics endpoint unavailable")
    
    @task(5)  # 5% of requests - test cross-tenant isolation
    def test_cross_tenant_isolation(self):
        """Verify no cross-tenant data leakage"""
        # Try to access another tenant's data with current tenant credentials
        other_tenant = choice([t for t in TENANTS if t != self.tenant_id])
        
        headers = {
            "X-Tenant-ID": self.tenant_id,
            "X-User-ID": self.user_id,
            "Authorization": self.token,
        }
        
        payload = {"query": f"Show me data for {other_tenant}"}
        
        with self.client.post(
            "/api/query",
            json=payload,
            headers=headers,
            catch_response=True,
        ) as response:
            # Should either return data only for requested tenant or error
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data.get("tenant_id") == self.tenant_id:
                        response.success()
                    else:
                        # Cross-tenant data returned
                        response.failure("SECURITY: Cross-tenant data leakage detected!")
                except:
                    response.failure("JSON parsing error")
            elif response.status_code in [400, 403]:
                response.success()  # Correctly rejected suspicious request
            else:
                response.failure(f"Unexpected status: {response.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when the Locust test starts"""
    print("\n" + "="*80)
    print("Starting Enterprise Multi-Tenant GenAI Platform Load Test")
    print("="*80)
    print(f"Target: {environment.host}")
    print(f"Tenants: {TENANTS}")
    print("="*80 + "\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when the Locust test stops"""
    global response_times, success_count, error_count
    
    print("\n" + "="*80)
    print("Load Test Results")
    print("="*80)
    
    # Calculate statistics
    total_requests = success_count + error_count
    
    if response_times:
        min_latency = min(response_times)
        max_latency = max(response_times)
        avg_latency = statistics.mean(response_times)
        p95_latency = statistics.quantiles(response_times, n=20)[18] if len(response_times) > 1 else avg_latency
        p99_latency = statistics.quantiles(response_times, n=100)[98] if len(response_times) > 1 else avg_latency
        
        print(f"\nLatency Metrics (ms):")
        print(f"  Min:     {min_latency:.2f}")
        print(f"  Max:     {max_latency:.2f}")
        print(f"  Average: {avg_latency:.2f}")
        print(f"  P95:     {p95_latency:.2f}")
        print(f"  P99:     {p99_latency:.2f}")
        
        # Check SLA targets
        target_p95 = 2500  # 2.5 seconds
        if p95_latency <= target_p95:
            print(f"\n✓ P95 Latency SLA MET: {p95_latency:.2f}ms <= {target_p95}ms")
        else:
            print(f"\n✗ P95 Latency SLA VIOLATED: {p95_latency:.2f}ms > {target_p95}ms")
    
    print(f"\nRequest Statistics:")
    print(f"  Successful: {success_count} ({100*success_count/total_requests:.1f}%)")
    print(f"  Failed:     {error_count} ({100*error_count/total_requests:.1f}%)")
    print(f"  Total:      {total_requests}")
    
    # Check error rate SLA
    error_rate = error_count / total_requests if total_requests > 0 else 0
    target_error_rate = 0.01  # 1%
    if error_rate <= target_error_rate:
        print(f"\n✓ Error Rate SLA MET: {error_rate*100:.2f}% <= {target_error_rate*100:.1f}%")
    else:
        print(f"\n✗ Error Rate SLA VIOLATED: {error_rate*100:.2f}% > {target_error_rate*100:.1f}%")
    
    print("\n" + "="*80)
    print("Test Complete")
    print("="*80 + "\n")


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """Called for every request"""
    # Could be used for real-time monitoring
    pass


# Test scenarios for specific use cases
class StressTestUser(GenAIUser):
    """Stress test with higher load"""
    wait_time = between(0.5, 1)  # More frequent requests


class EnduranceTestUser(GenAIUser):
    """Endurance test simulating long-running users"""
    wait_time = between(5, 10)  # Longer intervals


class PeakLoadTestUser(GenAIUser):
    """Peak load simulation"""
    wait_time = between(0.1, 0.5)  # Very frequent requests
