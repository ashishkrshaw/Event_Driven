"""Tests for the background worker components."""

import pytest

from app.models import Event, EventType
from worker.retry import FailureType, RetryHandler


class TestRetryHandler:
    """Tests for RetryHandler logic."""

    @pytest.fixture
    def handler(self) -> RetryHandler:
        """Create handler with 3 max retries."""
        return RetryHandler(max_retries=3)

    @pytest.fixture
    def event(self) -> Event:
        """Create a sample event."""
        return Event(
            event_type=EventType.USER_NOTIFICATION,
            user_id="test-user",
            retry_count=0,
        )

    def test_classify_transient_timeout(self, handler: RetryHandler) -> None:
        """Test classification of timeout errors as transient."""
        error = ConnectionError("Connection timeout occurred")
        assert handler.classify_failure(error) == FailureType.TRANSIENT

    def test_classify_transient_network(self, handler: RetryHandler) -> None:
        """Test classification of network errors as transient."""
        error = OSError("Network unreachable")
        assert handler.classify_failure(error) == FailureType.TRANSIENT

    def test_classify_permanent_validation(self, handler: RetryHandler) -> None:
        """Test classification of validation errors as permanent."""
        error = ValueError("Invalid payload format")
        assert handler.classify_failure(error) == FailureType.PERMANENT

    def test_classify_permanent_not_found(self, handler: RetryHandler) -> None:
        """Test classification of not found errors as permanent."""
        error = Exception("User not found")
        assert handler.classify_failure(error) == FailureType.PERMANENT

    def test_classify_unknown(self, handler: RetryHandler) -> None:
        """Test classification of unrecognized errors as unknown."""
        error = Exception("Something unexpected happened")
        assert handler.classify_failure(error) == FailureType.UNKNOWN

    def test_should_retry_transient_first_attempt(
        self, handler: RetryHandler, event: Event
    ) -> None:
        """Test that transient errors on first attempt should retry."""
        error = ConnectionError("timeout")

        decision = handler.should_retry(event, error)

        assert decision.should_retry is True
        assert "retry 1/3" in decision.reason

    def test_should_retry_transient_max_retries_exceeded(
        self, handler: RetryHandler
    ) -> None:
        """Test that transient errors at max retries should not retry."""
        event = Event(
            event_type=EventType.USER_NOTIFICATION,
            user_id="test-user",
            retry_count=3,  # Already at max
        )
        error = ConnectionError("timeout")

        decision = handler.should_retry(event, error)

        assert decision.should_retry is False
        assert "Max retries" in decision.reason

    def test_should_retry_permanent_immediately_fails(
        self, handler: RetryHandler, event: Event
    ) -> None:
        """Test that permanent errors should not retry."""
        error = ValueError("invalid data")

        decision = handler.should_retry(event, error)

        assert decision.should_retry is False
        assert "Permanent failure" in decision.reason

    def test_should_retry_unknown_error_retries(
        self, handler: RetryHandler, event: Event
    ) -> None:
        """Test that unknown errors should retry cautiously."""
        error = Exception("unexpected error")

        decision = handler.should_retry(event, error)

        assert decision.should_retry is True


class TestEventIncrement:
    """Tests for event retry increment."""

    def test_increment_creates_new_event(self) -> None:
        """Test that increment_retry creates a new event instance."""
        original = Event(
            event_type=EventType.USER_NOTIFICATION,
            user_id="test-user",
            retry_count=0,
        )

        updated = original.increment_retry()

        # Should be different instances
        assert original is not updated
        # Original unchanged
        assert original.retry_count == 0
        # Updated has incremented count
        assert updated.retry_count == 1

    def test_increment_preserves_other_fields(self) -> None:
        """Test that increment_retry preserves all other fields."""
        original = Event(
            event_type=EventType.SYSTEM_ALERT,
            user_id="user-456",
            payload={"key": "value"},
            retry_count=2,
        )

        updated = original.increment_retry()

        assert updated.event_id == original.event_id
        assert updated.event_type == original.event_type
        assert updated.user_id == original.user_id
        assert updated.payload == original.payload
        assert updated.created_at == original.created_at
        assert updated.retry_count == 3
