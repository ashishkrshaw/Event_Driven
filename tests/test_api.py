"""Tests for the Events API."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app


class TestEventsAPI:
    """Tests for POST /api/v1/events endpoint."""

    @pytest.fixture(autouse=True)
    def setup_client(self) -> None:
        """Set up test client."""
        self.client = TestClient(app)

    @patch("app.api.events.get_redis_client")
    def test_create_event_success(
        self, mock_get_redis: Any, sample_event_data: dict[str, Any]
    ) -> None:
        """Test successful event creation."""
        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.enqueue_event = AsyncMock()
        mock_get_redis.return_value = mock_redis

        response = self.client.post("/api/v1/events", json=sample_event_data)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "event_id" in data
        assert data["status"] == "queued"
        assert "queued_at" in data

    def test_create_event_missing_user_id(self) -> None:
        """Test validation error for missing user_id."""
        response = self.client.post(
            "/api/v1/events",
            json={
                "event_type": "USER_NOTIFICATION",
                "payload": {},
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "user_id" in response.text.lower()

    def test_create_event_invalid_event_type(self) -> None:
        """Test validation error for invalid event_type."""
        response = self.client.post(
            "/api/v1/events",
            json={
                "user_id": "test-user",
                "event_type": "INVALID_TYPE",
                "payload": {},
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_event_empty_user_id(self) -> None:
        """Test validation error for empty user_id."""
        response = self.client.post(
            "/api/v1/events",
            json={
                "user_id": "",
                "event_type": "USER_NOTIFICATION",
                "payload": {},
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch("app.api.events.get_redis_client")
    def test_create_event_with_all_event_types(self, mock_get_redis: Any) -> None:
        """Test event creation with all valid event types."""
        mock_redis = AsyncMock()
        mock_redis.enqueue_event = AsyncMock()
        mock_get_redis.return_value = mock_redis

        event_types = [
            "USER_NOTIFICATION",
            "SYSTEM_ALERT",
            "EMAIL_NOTIFICATION",
            "SMS_NOTIFICATION",
        ]

        for event_type in event_types:
            response = self.client.post(
                "/api/v1/events",
                json={
                    "user_id": "test-user",
                    "event_type": event_type,
                    "payload": {"type": event_type},
                },
            )
            assert response.status_code == status.HTTP_201_CREATED


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    @pytest.fixture(autouse=True)
    def setup_client(self) -> None:
        """Set up test client."""
        self.client = TestClient(app)

    @patch("app.main.get_redis_client")
    def test_health_check_healthy(self, mock_get_redis: Any) -> None:
        """Test health check when Redis is healthy."""
        mock_redis = AsyncMock()
        mock_redis.health_check = AsyncMock(return_value=True)
        mock_get_redis.return_value = mock_redis

        response = self.client.get("/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "healthy"
        assert data["redis"] == "connected"

    @patch("app.main.get_redis_client")
    def test_health_check_degraded(self, mock_get_redis: Any) -> None:
        """Test health check when Redis is unhealthy."""
        mock_redis = AsyncMock()
        mock_redis.health_check = AsyncMock(return_value=False)
        mock_get_redis.return_value = mock_redis

        response = self.client.get("/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "degraded"
        assert data["redis"] == "disconnected"

    @patch("app.main.get_redis_client")
    def test_queue_stats(self, mock_get_redis: Any) -> None:
        """Test queue stats endpoint."""
        mock_redis = AsyncMock()
        mock_redis.get_queue_length = AsyncMock(return_value=5)
        mock_redis.get_dlq_length = AsyncMock(return_value=2)
        mock_get_redis.return_value = mock_redis

        response = self.client.get("/stats")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["queue_length"] == 5
        assert data["dlq_length"] == 2
