# Architecture Documentation

This document explains the design decisions, trade-offs, and operational characteristics of the Event-Driven Notification Service.

## 1. System Overview

### Purpose

This service provides an **asynchronous event processing pipeline** that:
1. Accepts notification events via REST API
2. Queues events for background processing
3. Processes events with retry semantics
4. Handles failures gracefully with dead-letter queue

### Why Event-Driven?

| Concern | Synchronous Approach | Event-Driven Approach |
|---------|---------------------|----------------------|
| **API Latency** | Blocked by notification delivery | Returns immediately after queuing |
| **Fault Isolation** | API fails if SMTP is down | API unaffected; worker retries |
| **Scalability** | Limited by API capacity | Workers scale independently |
| **Resilience** | No retry mechanism | Built-in retry with DLQ |

## 2. Component Design

### 2.1 API Layer (FastAPI)

**Responsibilities:**
- Request validation (Pydantic)
- Event creation and queuing
- Health checks and metrics

**Design Decisions:**
- Stateless handlers (no session state)
- Dependency injection for testability
- Structured logging with request context

**Not Responsible For:**
- Notification delivery
- Retry logic
- Event processing

### 2.2 Queue (Redis)

**Why Redis?**
- Simple setup for local development
- Atomic list operations (LPUSH/BRPOP)
- Sufficient for intern-level scope

**Queue Semantics:**
- FIFO ordering via `LPUSH` (producer) + `BRPOP` (consumer)
- At-least-once delivery
- No acknowledgment mechanism (simplified)

**Alternative Considered:**
- RabbitMQ: More features, but adds operational complexity
- Kafka: Overkill for single-consumer workload

### 2.3 Background Worker

**Responsibilities:**
- Blocking event consumption
- Notification processing (simulated)
- Failure handling and retry
- Graceful shutdown

**Processing Loop:**
```
while running:
    event = BRPOP(queue, timeout=1)
    if event:
        try:
            process(event)
        except Exception as e:
            if should_retry(event, e):
                requeue(event)
            else:
                send_to_dlq(event)
```

## 3. Event Lifecycle

```
┌──────────────────────────────────────────────────────────────────┐
│                        EVENT LIFECYCLE                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   [1] API receives POST /api/v1/events                           │
│        │                                                          │
│        ▼                                                          │
│   [2] Validate input (Pydantic)                                  │
│        │                                                          │
│        ▼                                                          │
│   [3] Create Event with UUID, timestamp                          │
│        │                                                          │
│        ▼                                                          │
│   [4] LPUSH to Redis queue                                       │
│        │                                                          │
│        ▼                                                          │
│   [5] Return 201 Created to client                               │
│                                                                   │
│   ─────────────────────────────────────────────────────────────  │
│                                                                   │
│   [6] Worker BRPOP from queue                                    │
│        │                                                          │
│        ▼                                                          │
│   [7] Deserialize and process                                    │
│        │                                                          │
│        ├──── SUCCESS ────▶ [8] Log completion                    │
│        │                                                          │
│        └──── FAILURE ────▶ [9] Classify error                    │
│                                   │                               │
│                    ┌──────────────┴──────────────┐                │
│                    ▼                             ▼                │
│              TRANSIENT                      PERMANENT             │
│              (retry < max)                  (or max reached)      │
│                    │                             │                │
│                    ▼                             ▼                │
│              [10] Requeue                  [11] Send to DLQ       │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

## 4. Failure Handling

### Failure Classification

| Type | Examples | Action |
|------|----------|--------|
| **Transient** | Timeout, network error, 503 | Retry |
| **Permanent** | Validation error, 404, bad data | Dead-letter |
| **Unknown** | Unclassified exceptions | Retry cautiously |

### Retry Strategy

- **Fixed count**: 3 retries maximum
- **Immediate retry**: No backoff (simplified)
- **Dead-letter queue**: Preserves failed events for investigation

**Trade-off:** Immediate retry is simpler but may hammer a failing service. Production systems should use exponential backoff.

## 5. Reliability Guarantees

| Property | Guarantee | Caveat |
|----------|-----------|--------|
| **Delivery** | At-least-once | Duplicates possible |
| **Ordering** | FIFO per queue | Single consumer only |
| **Durability** | None (Redis memory) | Lost on restart |
| **Idempotency** | Consumer responsibility | Not enforced |

### At-Least-Once Semantics

Events are removed from queue before processing completes. If worker crashes mid-processing:
- Event is lost (no redelivery)
- Could improve with BRPOPLPUSH + acknowledgment

**Why accepted:** Simplified implementation for portfolio. Documented as known limitation.

## 6. Observability

### Structured Logging

All logs are JSON-formatted with consistent fields:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "info",
  "event": "event_processed",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user-123",
  "retry_count": 0
}
```

### Key Log Events

| Event | Level | Indicates |
|-------|-------|-----------|
| `event_enqueued` | INFO | Event accepted by API |
| `event_dequeued` | INFO | Worker picked up event |
| `event_processed` | INFO | Successful processing |
| `retry_scheduled` | INFO | Event will be retried |
| `event_dead_lettered` | WARN | Event moved to DLQ |

## 7. Scaling Discussion

### Current: Single Worker

- Processes events sequentially
- Simple and predictable
- Limited throughput

### Horizontal Scaling (Conceptual)

To scale beyond single worker:

1. **Multiple Workers**: Each calls BRPOP on same queue
   - Redis handles atomic distribution
   - No ordering guarantee across workers

2. **Partitioned Queues**: Separate queues per event type
   - Dedicated workers per queue
   - Better isolation

3. **Consumer Groups (Redis Streams)**: Built-in consumer groups
   - Acknowledgment mechanism
   - Pending message tracking

**Not implemented** because single worker meets portfolio scope.

## 8. Security Considerations

| Aspect | Implementation |
|--------|----------------|
| Input Validation | Pydantic schemas with constraints |
| Error Messages | Generic errors to clients (no stack traces) |
| Logging | Sensitive data not logged |
| Network | Internal Redis (not exposed) |

## 9. Testing Strategy

| Layer | Test Type | Tools |
|-------|-----------|-------|
| Models | Unit | pytest |
| API | Integration | TestClient, mocked Redis |
| Worker | Unit | pytest, mocked Redis |
| E2E | Manual | docker-compose + curl |

## 10. Deployment

### Local (Docker Compose)

```yaml
services:
  redis:    # Queue backend
  api:      # FastAPI on port 8000
  worker:   # Background consumer
```

### Production (Conceptual)

For AWS deployment:
- **EC2** or **ECS Fargate** for containers
- **ElastiCache Redis** for managed queue
- **CloudWatch** for logs
- **ALB** for API load balancing

---

*This architecture prioritizes simplicity and learnability over production-scale features, appropriate for a portfolio demonstration.*
