"""Event models and schemas using Pydantic."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Supported event types for the notification service."""

    USER_NOTIFICATION = "USER_NOTIFICATION"
    SYSTEM_ALERT = "SYSTEM_ALERT"
    EMAIL_NOTIFICATION = "EMAIL_NOTIFICATION"
    SMS_NOTIFICATION = "SMS_NOTIFICATION"


class EventStatus(str, Enum):
    """Status of an event in the processing pipeline."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


class EventCreate(BaseModel):
    """Schema for creating a new event via API."""

    user_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Unique identifier of the target user",
        examples=["user-123", "abc-def-456"],
    )
    event_type: EventType = Field(
        ...,
        description="Type of notification event",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific payload data",
        examples=[{"message": "Hello, World!", "priority": "high"}],
    )


class EventResponse(BaseModel):
    """Schema for API response after event creation."""

    event_id: str = Field(
        ...,
        description="Unique identifier for the created event",
    )
    status: EventStatus = Field(
        default=EventStatus.QUEUED,
        description="Current status of the event",
    )
    queued_at: datetime = Field(
        ...,
        description="Timestamp when the event was queued",
    )


class Event(BaseModel):
    """Internal event model for queue processing."""

    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    user_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int = Field(default=0, ge=0)
    version: str = Field(default="1.0", description="Event schema version")

    def to_response(self) -> EventResponse:
        """Convert to API response model."""
        return EventResponse(
            event_id=str(self.event_id),
            status=EventStatus.QUEUED,
            queued_at=self.created_at,
        )

    def increment_retry(self) -> "Event":
        """Return a new Event with incremented retry count."""
        return self.model_copy(update={"retry_count": self.retry_count + 1})
