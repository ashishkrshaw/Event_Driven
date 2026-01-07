"""
Background worker for processing events from Redis queue.

This module implements the main consumer loop with:
- Blocking queue consumption (BRPOP)
- Graceful shutdown handling
- Retry logic with dead-letter queue
- Structured logging for observability
"""

import asyncio
import signal
import sys
from datetime import datetime
from typing import Any, NoReturn

import structlog

# Add parent directory to path for imports
sys.path.insert(0, str(__file__).rsplit("worker", 1)[0])

from app.config import get_settings
from app.models import Event
from app.services.redis_client import RedisClient
from worker.retry import RetryHandler

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


class NotificationProcessor:
    """Real notification processor that sends actual emails with rate limiting."""

    def __init__(self, redis_client: Any) -> None:
        """Initialize with email service and rate limiter."""
        from app.services.email_service import EmailService
        from app.services.rate_limiter import EmailRateLimiter

        self.email_service = EmailService()
        self.rate_limiter = EmailRateLimiter(redis_client)
        self.settings = get_settings()

    async def process(self, event: Event) -> None:
        """
        Process a notification event and send a REAL email.
        Checks daily rate limit before sending.
        """
        await logger.ainfo(
            "notification_processing",
            event_id=str(event.event_id),
            event_type=event.event_type.value,
            user_id=event.user_id,
            payload=event.payload,
        )

        # Extract email details from payload
        to_email = event.payload.get("to_email") or event.payload.get("email")
        message = event.payload.get("message", "You have a new notification!")
        subject = event.payload.get(
            "subject", f"Notification: {event.event_type.value}"
        )

        if not to_email:
            await logger.awarning(
                "no_email_in_payload",
                event_id=str(event.event_id),
                hint="Add 'to_email' or 'email' to payload to send real emails",
            )
            await logger.ainfo(
                "notification_logged_only",
                event_id=str(event.event_id),
                user_id=event.user_id,
                message=message,
            )
            return

        # Check if SMTP is configured
        if not self.settings.smtp_user or not self.settings.smtp_password:
            await logger.awarning(
                "smtp_not_configured",
                event_id=str(event.event_id),
                hint="Set SMTP_USER and SMTP_PASSWORD in .env to send real emails",
            )
            return

        # Check daily rate limit
        if not await self.rate_limiter.can_send_email():
            await logger.awarning(
                "daily_email_limit_reached",
                event_id=str(event.event_id),
                limit=self.settings.daily_email_limit,
                to_email=to_email,
            )
            # Send alert to admin (once per day)
            await self.rate_limiter.check_and_alert(self.email_service)
            # Don't fail the event, just skip email
            return

        # Build email body
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #333;">🔔 Notification</h2>
            <p><strong>User ID:</strong> {event.user_id}</p>
            <p><strong>Type:</strong> {event.event_type.value}</p>
            <p><strong>Message:</strong> {message}</p>
            <hr>
            <p style="color: #666; font-size: 12px;">
                Event ID: {event.event_id}<br>
                Sent at: {datetime.utcnow().isoformat()}
            </p>
        </body>
        </html>
        """

        # Send the REAL email!
        await self.email_service.send_email(
            to_email=to_email,
            subject=subject,
            body=f"Notification for {event.user_id}: {message}",
            html_body=html_body,
        )

        # Record email sent for rate limiting
        count = await self.rate_limiter.record_email_sent()

        await logger.ainfo(
            "notification_email_sent",
            event_id=str(event.event_id),
            user_id=event.user_id,
            to_email=to_email,
            daily_count=count,
            daily_limit=self.settings.daily_email_limit,
            sent_at=datetime.utcnow().isoformat(),
        )


class EventConsumer:
    """Background worker that consumes and processes events from Redis queue."""

    def __init__(self) -> None:
        """Initialize consumer with dependencies."""
        self.settings = get_settings()
        self.redis_client = RedisClient()
        self.retry_handler = RetryHandler()
        self.processor: Any = None  # initialized after redis connects
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start the consumer loop."""
        await self.redis_client.connect()
        self.processor = NotificationProcessor(self.redis_client)
        self._running = True

        await logger.ainfo(
            "worker_started",
            queue=self.settings.redis_queue_name,
            max_retries=self.settings.max_retries,
            daily_email_limit=self.settings.daily_email_limit,
        )

        try:
            await self._consume_loop()
        finally:
            await self.redis_client.disconnect()
            await logger.ainfo("worker_stopped")

    async def stop(self) -> None:
        """Signal the consumer to stop gracefully."""
        await logger.ainfo("worker_shutdown_requested")
        self._running = False
        self._shutdown_event.set()

    async def _consume_loop(self) -> None:
        """Main consumption loop."""
        while self._running:
            try:
                # Block for events with 1 second timeout to check shutdown
                event = await self.redis_client.dequeue_event(timeout=1)

                if event is None:
                    # Timeout, check if we should continue
                    continue

                await self._process_event(event)

            except asyncio.CancelledError:
                await logger.ainfo("worker_cancelled")
                break
            except Exception as e:
                await logger.aerror(
                    "worker_consume_error",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Brief pause before retrying consumption
                await asyncio.sleep(1)

    async def _process_event(self, event: Event) -> None:
        """Process a single event with error handling."""
        try:
            if self.processor:
                await self.processor.process(event)

            await logger.ainfo(
                "event_processed",
                event_id=str(event.event_id),
                event_type=event.event_type.value,
            )

        except Exception as e:
            await self._handle_failure(event, e)

    async def _handle_failure(self, event: Event, error: Exception) -> None:
        """Handle event processing failure with retry logic."""
        decision = self.retry_handler.should_retry(event, error)
        await self.retry_handler.log_retry_decision(event, decision, error)

        if decision.should_retry:
            # Requeue with incremented retry count
            await self.redis_client.requeue_event(event)
        else:
            # Move to dead-letter queue
            await self.redis_client.send_to_dlq(event, decision.reason)


def setup_signal_handlers(
    consumer: EventConsumer, loop: asyncio.AbstractEventLoop
) -> None:
    """Set up signal handlers for graceful shutdown."""

    def handle_signal(sig: signal.Signals) -> None:
        logger.info("signal_received", signal=sig.name)
        loop.create_task(consumer.stop())

    # Handle SIGINT (Ctrl+C) and SIGTERM
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            # Using a simplified handler for Windows CI/local
            pass


async def main() -> None:
    """Main entry point for the worker."""
    consumer = EventConsumer()

    # Set up signal handlers
    loop = asyncio.get_running_loop()

    # Note: On Windows, signal handlers work differently
    # We use a simple approach that works cross-platform
    try:
        loop.add_signal_handler(
            signal.SIGINT, lambda: asyncio.create_task(consumer.stop())
        )
        loop.add_signal_handler(
            signal.SIGTERM, lambda: asyncio.create_task(consumer.stop())
        )
    except NotImplementedError:
        # Windows fallback
        pass

    try:
        await consumer.start()
    except KeyboardInterrupt:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
