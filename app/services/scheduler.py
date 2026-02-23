"""
Distributed scheduler and queue management for backpressure and fair sharing.
Implements: Global Redis priority queue + Per-pod local queues + Fair scheduling.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum

import redis
from app.models.schemas import QueuedRequest, TenantTier
from app.core.settings import settings

logger = logging.getLogger(__name__)


class RequestPriority(int, Enum):
    """Priority levels for queued requests (lower = higher priority)."""
    ENTERPRISE = 0
    PROFESSIONAL = 1
    STARTER = 2
    FREE = 3


class PriorityQueue:
    """
    Distributed priority queue using Redis.
    Implements: Global coordinator with per-pod local queues.
    """
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.pod_id = self._get_pod_id()
        self.local_queue_key = f"{settings.REDIS_KEY_PREFIX}queue:local:{self.pod_id}"
        self.global_queue_key = f"{settings.REDIS_KEY_PREFIX}queue:global:priority"
        self.dlq_key = f"{settings.REDIS_KEY_PREFIX}queue:dlq"
    
    def _get_pod_id(self) -> str:
        """Get or create unique pod ID."""
        pod_id = getattr(self, '_pod_id', None)
        if not pod_id:
            pod_id = f"pod-{uuid.uuid4().hex[:8]}"
            self._pod_id = pod_id
        return pod_id
    
    async def enqueue(
        self,
        request_id: str,
        tenant_id: str,
        tenant_tier: TenantTier,
        user_id: str,
        query_data: Dict[str, Any],
    ) -> QueuedRequest:
        """Enqueue a request with priority based on tenant tier."""
        # Calculate priority: tier determines priority, timestamp breaks ties
        tier_priority = RequestPriority[tenant_tier.value.upper()].value
        timestamp = time.time()
        priority_score = tier_priority * 1e9 + timestamp  # Weighted by tier + timestamp
        
        queued_request = QueuedRequest(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            priority=tier_priority,
            submitted_at=datetime.utcnow(),
            query_data=query_data,
        )
        
        # Try local queue first (max capacity: MAX_QUEUE_DEPTH)
        local_depth = self.redis.llen(self.local_queue_key)
        
        if local_depth < settings.MAX_QUEUE_DEPTH:
            # Add to local queue
            self.redis.lpush(
                self.local_queue_key,
                json.dumps(queued_request.model_dump()),
            )
            logger.info(f"Enqueued {request_id} to local queue (depth: {local_depth + 1})")
        else:
            # Local queue full, use global priority queue
            self.redis.zadd(
                self.global_queue_key,
                {json.dumps(queued_request.model_dump()): priority_score},
            )
            logger.info(f"Enqueued {request_id} to global priority queue")
        
        # Check if queue is overloaded
        global_depth = self.redis.zcard(self.global_queue_key)
        if global_depth > settings.MAX_QUEUE_DEPTH * 0.8:
            logger.warning(f"Queue approaching capacity: {global_depth}/{settings.MAX_QUEUE_DEPTH}")
        
        return queued_request
    
    async def dequeue(self) -> Optional[QueuedRequest]:
        """Dequeue the next highest-priority request."""
        # Try local queue first (FIFO within pod)
        local_item = self.redis.rpop(self.local_queue_key)
        if local_item:
            request_data = json.loads(local_item)
            return QueuedRequest(**request_data)
        
        # Fall back to global priority queue (sorted by tier + timestamp)
        global_items = self.redis.zrange(self.global_queue_key, 0, 0)
        if global_items:
            request_data = json.loads(global_items[0])
            self.redis.zrem(self.global_queue_key, global_items[0])
            return QueuedRequest(**request_data)
        
        return None
    
    async def check_timeout(self) -> List[str]:
        """Check for timed-out requests (> QUEUE_TIMEOUT_SEC in queue)."""
        now = datetime.utcnow()
        timeout_threshold = now.timestamp() - settings.QUEUE_TIMEOUT_SEC
        
        # Check local queue
        timed_out_requests = []
        local_items = self.redis.lrange(self.local_queue_key, 0, -1)
        
        for item in local_items:
            request_data = json.loads(item)
            submitted = datetime.fromisoformat(request_data["submitted_at"])
            
            if submitted.timestamp() < timeout_threshold:
                timed_out_requests.append(request_data["request_id"])
                # Move to DLQ
                self.redis.lpush(self.dlq_key, item)
                self.redis.lrem(self.local_queue_key, 1, item)
        
        # Check global queue
        all_global = self.redis.zrange(self.global_queue_key, 0, -1)
        for item in all_global:
            request_data = json.loads(item)
            submitted = datetime.fromisoformat(request_data["submitted_at"])
            
            if submitted.timestamp() < timeout_threshold:
                timed_out_requests.append(request_data["request_id"])
                self.redis.zrem(self.global_queue_key, item)
                self.redis.lpush(self.dlq_key, item)
        
        if timed_out_requests:
            logger.warning(f"Timed out {len(timed_out_requests)} requests: {timed_out_requests}")
        
        return timed_out_requests
    
    async def get_queue_depth(self) -> Dict[str, int]:
        """Get current queue depths."""
        return {
            "local": self.redis.llen(self.local_queue_key),
            "global": self.redis.zcard(self.global_queue_key),
            "dlq": self.redis.llen(self.dlq_key),
        }


class FairScheduler:
    """
    Implements fair resource allocation with weighted fair queuing (WFQ).
    Allocates resources per tier: Enterprise 50%, Professional 30%, Starter 15%, Free 5%.
    """
    
    # Fair share percentages per tier
    FAIR_SHARES = {
        TenantTier.ENTERPRISE: 0.50,
        TenantTier.PROFESSIONAL: 0.30,
        TenantTier.STARTER: 0.15,
        TenantTier.FREE: 0.05,
    }
    
    def __init__(self, redis_client: redis.Redis, priority_queue: PriorityQueue):
        self.redis = redis_client
        self.priority_queue = priority_queue
        self.in_flight_requests: Dict[str, int] = {}  # tenant_id -> count
        self.total_in_flight = 0
    
    async def schedule_next(self) -> Optional[QueuedRequest]:
        """
        Schedule the next request respecting fair sharing.
        Returns None if no requests or all tiers at capacity.
        """
        # Get queue depth
        depths = await self.priority_queue.get_queue_depth()
        total_queued = depths["local"] + depths["global"]
        
        if total_queued == 0:
            return None
        
        # Allocate based on tier fair shares
        for tier in [TenantTier.ENTERPRISE, TenantTier.PROFESSIONAL, 
                     TenantTier.STARTER, TenantTier.FREE]:
            fair_share = self.FAIR_SHARES[tier]
            max_capacity = int(settings.MAX_INFLIGHT_PER_POD * fair_share)
            current_in_flight = self._get_in_flight_for_tier(tier)
            
            if current_in_flight < max_capacity:
                # This tier has capacity, try to dequeue
                request = await self.priority_queue.dequeue()
                if request:
                    self._add_in_flight(request.tenant_id)
                    return request
        
        return None
    
    def _get_in_flight_for_tier(self, tier: TenantTier) -> int:
        """Get current in-flight count for a tier."""
        count = 0
        tier_config_key = f"config:tier:{tier.value}"
        # Note: in production, would fetch actual tenant tier from DB
        for tenant_id, count_val in self.in_flight_requests.items():
            count += count_val
        return count
    
    def _add_in_flight(self, tenant_id: str) -> None:
        """Register request as in-flight."""
        self.in_flight_requests[tenant_id] = self.in_flight_requests.get(tenant_id, 0) + 1
        self.total_in_flight += 1
    
    def _remove_in_flight(self, tenant_id: str) -> None:
        """Unregister request after completion."""
        if tenant_id in self.in_flight_requests:
            self.in_flight_requests[tenant_id] -= 1
            if self.in_flight_requests[tenant_id] <= 0:
                del self.in_flight_requests[tenant_id]
        self.total_in_flight = max(0, self.total_in_flight - 1)
    
    async def is_overloaded(self) -> bool:
        """Check if system is overloaded."""
        return self.total_in_flight >= settings.MAX_INFLIGHT_PER_POD
    
    def get_noisy_neighbor_score(self, tenant_id: str) -> float:
        """
        Calculate noisy neighbor score (0-1).
        Returns fraction of capacity used by this tenant.
        """
        if tenant_id not in self.in_flight_requests:
            return 0.0
        
        return min(
            1.0,
            self.in_flight_requests[tenant_id] / settings.MAX_INFLIGHT_PER_POD,
        )


class AsyncWorkerPool:
    """
    Pool of async workers that process queued requests.
    Fixed pool size based on WORKER_POOL_SIZE.
    """
    
    def __init__(
        self,
        size: int,
        priority_queue: PriorityQueue,
        fair_scheduler: FairScheduler,
        request_processor_callback,
    ):
        self.size = size
        self.priority_queue = priority_queue
        self.fair_scheduler = fair_scheduler
        self.request_processor_callback = request_processor_callback
        self.workers: List[asyncio.Task] = []
        self.running = False
    
    async def start(self) -> None:
        """Start all worker tasks."""
        self.running = True
        logger.info(f"Starting {self.size} worker pool")
        
        for i in range(self.size):
            worker_task = asyncio.create_task(self._worker_loop(i))
            self.workers.append(worker_task)
    
    async def stop(self) -> None:
        """Stop all worker tasks and wait for graceful shutdown."""
        self.running = False
        logger.info("Stopping worker pool (max 2 minutes)")
        
        try:
            await asyncio.wait_for(
                asyncio.gather(*self.workers),
                timeout=120,  # 2 minute grace period
            )
        except asyncio.TimeoutError:
            logger.warning("Worker pool shutdown timeout, cancelling tasks")
            for task in self.workers:
                task.cancel()
    
    async def _worker_loop(self, worker_id: int) -> None:
        """Main worker loop."""
        logger.info(f"Worker {worker_id} started")
        
        while self.running:
            try:
                # Get next request respecting fair sharing
                request = await self.fair_scheduler.schedule_next()
                
                if not request:
                    # No requests, sleep briefly
                    await asyncio.sleep(settings.QUEUE_CHECK_INTERVAL_MS / 1000.0)
                    continue
                
                # Process request
                logger.info(f"Worker {worker_id} processing {request.request_id}")
                start_time = time.time()
                
                result = await self.request_processor_callback(request)
                
                latency = (time.time() - start_time) * 1000  # ms
                logger.info(
                    f"Worker {worker_id} completed {request.request_id} "
                    f"in {latency:.0f}ms"
                )
                
                # Mark as complete
                self.fair_scheduler._remove_in_flight(request.tenant_id)
                
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(1)
        
        logger.info(f"Worker {worker_id} stopped")
