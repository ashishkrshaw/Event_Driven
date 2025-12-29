"""Unit tests for Event models."""

import pytest
from pydantic import ValidationError

from app.models import Event, EventCreate, EventStatus, EventType


class TestEventCreate:
    """Tests for EventCreate validation."""

    def test_valid_event_create(self) -> None:
        """Test creating a valid event."""
        event = EventCreate(
            user_id="user-123",
            event_type=EventType.USER_NOTIFICATION,
            payload={"message": "Hello"},
        )
        assert event.user_id == "user-123"
        assert event.event_type == EventType.USER_NOTIFICATION
        assert event.payload == {"message": "Hello"}

    def test_event_create_minimal(self) -> None:
        """Test creating event with minimal fields."""
        event = EventCreate(
            user_id="user-123",
            event_type=EventType.SYSTEM_ALERT,
        )
        assert event.payload == {}

    def test_event_create_empty_user_id_fails(self) -> None:
        """Test that empty user_id fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            EventCreate(
                user_id="",
                event_type=EventType.USER_NOTIFICATION,
            )
        assert "user_id" in str(exc_info.value)

    def test_event_create_invalid_event_type_fails(self) -> None:
        """Test that invalid event_type fails validation."""
        with pytest.raises(ValidationError):
            EventCreate(
                user_id="user-123",
                event_type="INVALID_TYPE",  # type: ignore
            )

    def test_event_create_long_user_id_fails(self) -> None:
        """Test that user_id exceeding max length fails."""
        with pytest.raises(ValidationError):
            EventCreate(
                user_id="x" * 200,  # Exceeds 128 char limit
                event_type=EventType.USER_NOTIFICATION,
            )


class TestEvent:
    """Tests for internal Event model."""

    def test_event_defaults(self) -> None:
        """Test Event default values."""
        event = Event(
            event_type=EventType.USER_NOTIFICATION,
            user_id="test-user",
        )
        assert event.event_id is not None
        assert event.retry_count == 0
        assert event.version == "1.0"
        assert event.payload == {}
        assert event.created_at is not None

    def test_event_increment_retry(self) -> None:
        """Test retry count increment."""
        event = Event(
            event_type=EventType.USER_NOTIFICATION,
            user_id="test-user",
            retry_count=2,
        )
        updated = event.increment_retry()

        # Original unchanged
        assert event.retry_count == 2
        # New copy has incremented count
        assert updated.retry_count == 3
        # Same event_id
        assert updated.event_id == event.event_id

    def test_event_to_response(self) -> None:
        """Test conversion to API response."""
        event = Event(
            event_type=EventType.USER_NOTIFICATION,
            user_id="test-user",
        )
        response = event.to_response()

        assert response.event_id == str(event.event_id)
        assert response.status == EventStatus.QUEUED
        assert response.queued_at == event.created_at


class TestEventType:
    """Tests for EventType enum."""

    def test_all_event_types_exist(self) -> None:
        """Verify all expected event types are defined."""
        expected_types = [
            "USER_NOTIFICATION",
            "SYSTEM_ALERT",
            "EMAIL_NOTIFICATION",
            "SMS_NOTIFICATION",
        ]
        actual_types = [e.value for e in EventType]
        assert sorted(actual_types) == sorted(expected_types)

    def test_event_type_is_string_enum(self) -> None:
        """Test that EventType values are strings."""
        for event_type in EventType:
            assert isinstance(event_type.value, str)
