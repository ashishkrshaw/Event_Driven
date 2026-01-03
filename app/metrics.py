"""Prometheus metrics for observability."""

from prometheus_client import Counter, Gauge, Histogram, Info

# Application info
APP_INFO = Info("app", "Application information")
APP_INFO.info({
    "name": "event-notification-service",
    "version": "1.0.0",
})

# API Metrics
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Event Metrics
EVENTS_PUBLISHED_TOTAL = Counter(
    "events_published_total",
    "Total events published to queue",
    ["event_type"],
)

EVENTS_PROCESSED_TOTAL = Counter(
    "events_processed_total",
    "Total events processed by worker",
    ["event_type", "status"],  # status: success, retry, dead_lettered
)

EVENTS_PROCESSING_DURATION_SECONDS = Histogram(
    "events_processing_duration_seconds",
    "Event processing duration in seconds",
    ["event_type"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# Queue Metrics
QUEUE_LENGTH = Gauge(
    "queue_length",
    "Current length of the event queue",
    ["queue_name"],
)

DLQ_LENGTH = Gauge(
    "dlq_length",
    "Current length of the dead-letter queue",
)

# Email Metrics
EMAILS_SENT_TOTAL = Counter(
    "emails_sent_total",
    "Total emails sent",
    ["status"],  # success, failed
)

EMAIL_SEND_DURATION_SECONDS = Histogram(
    "email_send_duration_seconds",
    "Email sending duration in seconds",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Worker Metrics
WORKER_UP = Gauge(
    "worker_up",
    "Whether the worker is running (1) or not (0)",
)

RETRY_COUNT = Counter(
    "retry_count_total",
    "Total retry attempts",
    ["event_type"],
)
