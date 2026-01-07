"""Email rate limiter using Redis for daily tracking."""

from datetime import date
from typing import Any

import structlog

from app.config import get_settings

logger = structlog.get_logger()


class EmailRateLimiter:
    """Track and limit daily email sends using Redis."""

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client
        self.settings = get_settings()
        self._alert_sent_today = False

    def _get_today_key(self) -> str:
        """Get Redis key for today's email count."""
        today = date.today().isoformat()
        return f"email:count:{today}"

    async def get_today_count(self) -> int:
        """Get number of emails sent today."""
        key = self._get_today_key()
        count = await self.redis.client.get(key)
        return int(count) if count else 0

    async def increment_count(self) -> int:
        """Increment and return today's email count."""
        key = self._get_today_key()
        # increment and set expiry to 48 hours (cleanup old keys)
        count = await self.redis.client.incr(key)
        await self.redis.client.expire(key, 60 * 60 * 48)
        return int(count) if count else 0

    async def can_send_email(self) -> bool:
        """Check if we're under the daily limit."""
        count = await self.get_today_count()
        return count < self.settings.daily_email_limit

    async def check_and_alert(self, email_service: Any) -> None:
        """Send alert email if limit reached (once per day)."""
        if self._alert_sent_today:
            return

        count = await self.get_today_count()
        if count >= self.settings.daily_email_limit:
            alert_email = self.settings.alert_email
            if alert_email:
                try:
                    await email_service.send_email(
                        to_email=alert_email,
                        subject="[EventFlow] Daily Email Limit Reached",
                        body=f"Daily email limit of {self.settings.daily_email_limit} has been reached.\n\n"
                        f"Emails sent today: {count}\n"
                        f"New email requests will be queued but not sent until tomorrow.",
                    )
                    self._alert_sent_today = True
                    await logger.awarning(
                        "email_limit_alert_sent",
                        limit=self.settings.daily_email_limit,
                        count=count,
                        alert_email=alert_email,
                    )
                except Exception as e:
                    await logger.aerror("failed_to_send_limit_alert", error=str(e))

    async def record_email_sent(self) -> int:
        """Record that an email was sent. Returns new count."""
        return await self.increment_count()
