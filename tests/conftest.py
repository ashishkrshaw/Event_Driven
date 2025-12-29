"""Pytest configuration and shared fixtures."""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app
from app.models import Event, EventType
from app.services.redis_client import RedisClient


@pytest.fixture
def test_client() -> TestClient:
    """Create a synchronous test client for FastAPI."""
    return TestClient(app)


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client for FastAPI."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_redis_client() -> MagicMock:
    """Create a mock Redis client."""
    mock = MagicMock(spec=RedisClient)
    mock.enqueue_event = AsyncMock()
    mock.dequeue_event = AsyncMock()
    mock.send_to_dlq = AsyncMock()
    mock.requeue_event = AsyncMock()
    mock.get_queue_length = AsyncMock(return_value=0)
    mock.get_dlq_length = AsyncMock(return_value=0)
    mock.health_check = AsyncMock(return_value=True)
    mock.connect = AsyncMock()
    mock.disconnect = AsyncMock()
    return mock


@pytest.fixture
def sample_event_data() -> dict[str, Any]:
    """Valid event creation payload."""
    return {
        "user_id": "test-user-123",
        "event_type": "USER_NOTIFICATION",
        "payload": {"message": "Hello, World!", "priority": "high"},
    }


@pytest.fixture
def sample_event() -> Event:
    """Create a sample Event instance."""
    return Event(
        event_type=EventType.USER_NOTIFICATION,
        user_id="test-user-123",
        payload={"message": "Test notification"},
    )
