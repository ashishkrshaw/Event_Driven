"""Email notification service using SMTP."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from app.config import get_settings

logger = structlog.get_logger()


class EmailService:
    """Service for sending real emails via SMTP."""

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
    ) -> None:
        """Initialize email service with SMTP credentials."""
        settings = get_settings()
        self.smtp_host = smtp_host or settings.smtp_host
        self.smtp_port = smtp_port or settings.smtp_port
        self.smtp_user = smtp_user or settings.smtp_user
        self.smtp_password = smtp_password or settings.smtp_password
        self.from_email = settings.from_email

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> bool:
        """
        Send an email via SMTP.

        Args:
            to_email: Recipient email address
            subject: Email subject line
            body: Plain text body
            html_body: Optional HTML body

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = to_email

            # Attach plain text
            msg.attach(MIMEText(body, "plain"))

            # Attach HTML if provided
            if html_body:
                msg.attach(MIMEText(html_body, "html"))

            # Send via SMTP
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()  # Enable TLS
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_email, to_email, msg.as_string())

            await logger.ainfo(
                "email_sent_successfully",
                to=to_email,
                subject=subject,
            )
            return True

        except smtplib.SMTPAuthenticationError as e:
            await logger.aerror(
                "email_auth_failed",
                error=str(e),
                hint="Check SMTP credentials. For Gmail, use App Password.",
            )
            raise

        except smtplib.SMTPException as e:
            await logger.aerror(
                "email_send_failed",
                to=to_email,
                error=str(e),
            )
            raise

        except Exception as e:
            await logger.aerror(
                "email_unexpected_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise
