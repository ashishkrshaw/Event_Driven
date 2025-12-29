"""Retry logic and failure classification for event processing."""

from enum import Enum
from typing import NamedTuple

import structlog

from app.config import get_settings
from app.models import Event

logger = structlog.get_logger()


class FailureType(str, Enum):
    """Classification of processing failures."""

    TRANSIENT = "transient"  # Network issues, timeouts - should retry
    PERMANENT = "permanent"  # Validation errors, bad data - don't retry
    UNKNOWN = "unknown"  # Unclassified errors - retry with caution


class RetryDecision(NamedTuple):
    """Decision on whether to retry an event."""

    should_retry: bool
    reason: str


class RetryHandler:
    """Handler for retry logic and failure classification."""

    def __init__(self, max_retries: int | None = None) -> None:
        """Initialize with max retry count."""
        settings = get_settings()
        self.max_retries = max_retries or settings.max_retries

    def classify_failure(self, error: Exception) -> FailureType:
        """
        Classify an exception into a failure type.

        This determines whether the error is transient (worth retrying)
        or permanent (should go to DLQ immediately).
        """
        error_type = type(error).__name__
        error_message = str(error).lower()

        # Transient errors - network issues, timeouts
        transient_indicators = [
            "timeout",
            "connection",
            "temporary",
            "unavailable",
            "retry",
            "network",
        ]

        if any(indicator in error_message for indicator in transient_indicators):
            return FailureType.TRANSIENT

        # Permanent errors - validation, data issues
        permanent_indicators = [
            "validation",
            "invalid",
            "malformed",
            "not found",
            "unauthorized",
            "forbidden",
        ]

        if any(indicator in error_message for indicator in permanent_indicators):
            return FailureType.PERMANENT

        # Check exception type
        if error_type in ("ConnectionError", "TimeoutError", "OSError"):
            return FailureType.TRANSIENT

        if error_type in ("ValueError", "KeyError", "TypeError"):
            return FailureType.PERMANENT

        return FailureType.UNKNOWN

    def should_retry(self, event: Event, error: Exception) -> RetryDecision:
        """
        Determine if an event should be retried.

        Args:
            event: The event that failed processing.
            error: The exception that occurred.

        Returns:
            RetryDecision with should_retry flag and reason.
        """
        failure_type = self.classify_failure(error)

        # Permanent failures go straight to DLQ
        if failure_type == FailureType.PERMANENT:
            return RetryDecision(
                should_retry=False,
                reason=f"Permanent failure: {type(error).__name__}: {error}",
            )

        # Check retry count
        if event.retry_count >= self.max_retries:
            return RetryDecision(
                should_retry=False,
                reason=f"Max retries ({self.max_retries}) exceeded",
            )

        # Transient or unknown errors should retry
        return RetryDecision(
            should_retry=True,
            reason=f"{failure_type.value} failure, retry {event.retry_count + 1}/{self.max_retries}",
        )

    async def log_retry_decision(
        self, event: Event, decision: RetryDecision, error: Exception
    ) -> None:
        """Log the retry decision for observability."""
        if decision.should_retry:
            await logger.ainfo(
                "retry_scheduled",
                event_id=str(event.event_id),
                retry_count=event.retry_count + 1,
                max_retries=self.max_retries,
                reason=decision.reason,
            )
        else:
            await logger.awarning(
                "retry_exhausted",
                event_id=str(event.event_id),
                retry_count=event.retry_count,
                reason=decision.reason,
                error_type=type(error).__name__,
            )
