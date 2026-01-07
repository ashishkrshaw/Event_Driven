# EventFlow

A simple project I built to try out event-driven architecture and background processing.

## What it is

This is a basic notification service that takes events via an API and puts them in a queue. A separate worker then picks them up and tries to send them. I built this to see how to move slow tasks (like sending emails) out of the main API response.

It's a straightforward setup:
- **FastAPI:** Receives the data.
- **Redis:** Acts as a simple shelf for events.
- **Worker:** Processes the events one by one.
- **Retry Logic:** My attempt at handling transient errors (like a busy SMTP server) by moving them to a "Dead Letter" list if they keep failing.

## Why I made this

I wanted to see how message queues actually work in code. Reading about them is one thing, but setting up the logic to handle failures and retries made things much clearer for me. It’s not a perfect system, but it was a great way for me to learn the fundamentals of async work.

## How to run it

I've tried to make it easy to start up.

### Using Docker (Simplest)
If you have Docker, you can start everything (API, Worker, Redis) with one command:
```bash
docker-compose up --build
```

### Manual Setup
1. **Redis:** `docker run -d -p 6379:6379 redis:7-alpine`
2. **Environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```
3. **App:** Run `uvicorn app.main:app` in one terminal and `python -m worker.consumer` in another.

## Testing it

Once it's running, you can send an event to see it in action:

```bash
curl -X POST http://localhost:8000/api/v1/events \
     -H "Content-Type: application/json" \
     -d '{
       "user_id": "user-123",
       "event_type": "USER_NOTIFICATION",
       "payload": {
         "to_email": "test@example.com",
         "message": "Testing my first event-driven app!"
       }
     }'
```

You can also check:
- **Basic Stats:** `http://localhost:8000/stats`
- **Health Check:** `http://localhost:8000/health`
- **Metrics (Prometheus):** `http://localhost:8000/metrics`

## Things I learned (and struggled with)

- **Blocking Reads:** Figuring out how to make the worker wait for data (`BRPOP`) without spinning the CPU was interesting.
- **Error Types:** Dealing with why a task might fail—and whether it’s worth trying again or giving up—was a big part of the logic.
- **Rate Limiting:** I added a basic limit (20 emails/day) using Redis to make sure I don't accidentally spam anything during testing.
- **Observability:** Getting basic metrics into Prometheus to see if the system is "alive" was a new experience for me.

## Realistic Limitations

- **At-least-once:** The system is simple and doesn't handle deduplication perfectly.
- **Persistence:** If Redis restarts, any events not yet moved to a persistent store might be lost.
- **Scaling:** It's designed for a single worker; a larger system would need more complex locking.

This was a learning exercise, and there's definitely more that could be improved for a real production environment.

---
Built by Ashish as a personal learning project.

