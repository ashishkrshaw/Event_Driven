"""Event publisher service."""

import structlog

from app.metrics import EVENTS_PUBLISHED_TOTAL
from app.models import Event, EventCreate, EventResponse
from app.services.redis_client import RedisClient

logger = structlog.get_logger()


class EventPublisher:
    """Service for publishing events to the queue."""

    def __init__(self, redis_client: RedisClient) -> None:
        """Initialize with Redis client dependency."""
        self.redis_client = redis_client

    async def publish(self, event_create: EventCreate) -> EventResponse:
        """
        Create and publish an event to the processing queue.

        Args:
            event_create: Validated event creation request.

        Returns:
            EventResponse with event ID and status.
        """
        # Create internal event model
        event = Event(
            event_type=event_create.event_type,
            user_id=event_create.user_id,
            payload=event_create.payload,
        )

        # Enqueue for processing
        await self.redis_client.enqueue_event(event)

        # Record Prometheus metric
        EVENTS_PUBLISHED_TOTAL.labels(event_type=event.event_type.value).inc()

        await logger.ainfo(
            "event_published",
            event_id=str(event.event_id),
            user_id=event.user_id,
            event_type=event.event_type.value,
        )

        return event.to_response()
