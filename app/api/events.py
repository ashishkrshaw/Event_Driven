"""Events API router."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.models import EventCreate, EventResponse
from app.services import EventPublisher, get_redis_client

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def get_event_publisher() -> EventPublisher:
    """Dependency to get EventPublisher instance."""
    return EventPublisher(get_redis_client())


@router.post(
    "",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Publish a new event",
    description="Create and queue a new notification event for async processing.",
    responses={
        201: {"description": "Event successfully queued"},
        422: {"description": "Validation error"},
        503: {"description": "Queue service unavailable"},
    },
)
async def create_event(
    event_create: EventCreate,
    publisher: Annotated[EventPublisher, Depends(get_event_publisher)],
) -> EventResponse:
    """
    Publish a new notification event.

    The event is validated and immediately queued for background processing.
    Returns the event ID and queued timestamp for tracking.
    """
    try:
        response = await publisher.publish(event_create)
        await logger.ainfo(
            "api_event_created",
            event_id=response.event_id,
            user_id=event_create.user_id,
        )
        return response
    except Exception as e:
        await logger.aerror(
            "api_event_creation_failed",
            error=str(e),
            user_id=event_create.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to queue event. Please try again.",
        ) from e
