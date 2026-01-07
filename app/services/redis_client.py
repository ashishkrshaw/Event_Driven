"""Redis client service for queue operations."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from typing import Any, cast

import redis.asyncio as redis
import structlog

from app.config import get_settings
from app.models import Event

logger = structlog.get_logger()


class RedisClient:
    """Async Redis client for event queue operations."""

    def __init__(self, redis_url: str | None = None) -> None:
        """Initialize Redis client with connection URL."""
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.queue_name = settings.redis_queue_name
        self.dlq_name = settings.redis_dlq_name
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        """Establish connection to Redis."""
        if self._client is None:
            self._client = cast(
                redis.Redis,
                redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                ),
            )
            await logger.ainfo("redis_connected", url=self.redis_url)

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            await logger.ainfo("redis_disconnected")

    @property
    def client(self) -> redis.Redis:
        """Get Redis client, raising if not connected."""
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client

    async def enqueue_event(self, event: Event) -> None:
        """
        Push an event to the main processing queue.

        Uses LPUSH for FIFO semantics with BRPOP consumption.
        """
        event_json = event.model_dump_json()
        await cast(Any, self.client.lpush(self.queue_name, event_json))
        await logger.ainfo(
            "event_enqueued",
            event_id=str(event.event_id),
            event_type=event.event_type.value,
            queue=self.queue_name,
        )

    async def dequeue_event(self, timeout: int = 0) -> Event | None:
        """
        Block and pop an event from the queue.

        Args:
            timeout: Seconds to block. 0 means block indefinitely.

        Returns:
            Event if available, None on timeout.
        """
        result = await cast(Any, self.client.brpop([self.queue_name], timeout=timeout))
        if result is None:
            return None

        _, event_json = result
        event_data = json.loads(event_json)
        event = Event.model_validate(event_data)

        await logger.ainfo(
            "event_dequeued",
            event_id=str(event.event_id),
            retry_count=event.retry_count,
        )
        return event

    async def send_to_dlq(self, event: Event, reason: str) -> None:
        """
        Move a failed event to the dead-letter queue.

        Args:
            event: The failed event.
            reason: Reason for dead-lettering.
        """
        dlq_entry = {
            "event": event.model_dump(mode="json"),
            "reason": reason,
        }
        await cast(Any, self.client.lpush(self.dlq_name, json.dumps(dlq_entry)))
        await logger.awarning(
            "event_dead_lettered",
            event_id=str(event.event_id),
            reason=reason,
            retry_count=event.retry_count,
        )

    async def requeue_event(self, event: Event) -> None:
        """
        Requeue an event for retry with incremented retry count.
        """
        updated_event = event.increment_retry()
        await self.enqueue_event(updated_event)
        await logger.ainfo(
            "event_requeued",
            event_id=str(event.event_id),
            retry_count=updated_event.retry_count,
        )

    async def get_queue_length(self) -> int:
        """Get the current length of the event queue."""
        return cast(int, await cast(Any, self.client.llen(self.queue_name)))

    async def get_dlq_length(self) -> int:
        """Get the current length of the dead-letter queue."""
        return cast(int, await cast(Any, self.client.llen(self.dlq_name)))

    async def health_check(self) -> bool:
        """Check if Redis connection is healthy."""
        try:
            await cast(Any, self.client.ping())
            return True
        except Exception:
            return False


# Global client instance
_redis_client: RedisClient | None = None


def get_redis_client() -> RedisClient:
    """Get the global Redis client instance."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client


@asynccontextmanager
async def redis_lifespan() -> AsyncGenerator[RedisClient, None]:
    """Context manager for Redis lifecycle in FastAPI."""
    client = get_redis_client()
    await client.connect()
    try:
        yield client
    finally:
        await client.disconnect()
