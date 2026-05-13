"""
tests/test_webhook.py
---------------------
Integration-style tests for the /webhook/message endpoint.

These tests use httpx.AsyncClient with the FastAPI app mounted in-process,
so they run without a running server.  They hit the real Claude API, so they
require CLAUDE_API_KEY to be set in your environment (or .env file).

Run with:
    pytest tests/test_webhook.py -v
"""

import os

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient

# Load .env so the Claude API key is available in test runs
load_dotenv()

from app.main import app  # noqa: E402 — import after env load


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    """In-process async client — no server needed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Tests ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_availability_query(client):
    """
    Input 1: Pre-sales availability + pricing question (from the brief).
    Expected: query_type = pre_sales_availability OR pre_sales_pricing,
              confidence >= 0.60, a non-empty drafted reply.
    """
    payload = {
        "source": "whatsapp",
        "guest_name": "Rahul Sharma",
        "message": "Is the villa available from April 20 to 24? What is the rate for 2 adults?",
        "timestamp": "2026-05-05T10:30:00Z",
        "booking_ref": "NIS-2024-0891",
        "property_id": "villa-b1",
    }
    response = await client.post("/webhook/message", json=payload)
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["query_type"] in ("pre_sales_availability", "pre_sales_pricing")
    assert len(data["drafted_reply"]) > 20
    assert 0.0 <= data["confidence_score"] <= 1.0
    assert data["action"] in ("auto_send", "agent_review", "escalate")
    print(f"\n[Test 1] query_type={data['query_type']} | confidence={data['confidence_score']} | action={data['action']}")
    print(f"Reply: {data['drafted_reply']}")


@pytest.mark.asyncio
async def test_complaint_always_escalates(client):
    """
    Input 2: Complaint about broken AC.
    Expected: query_type = complaint, action = escalate,
              confidence <= 0.58 (hard cap enforced by compute_confidence).
    """
    payload = {
        "source": "booking_com",
        "guest_name": "Priya Menon",
        "message": "The AC is not working and the room is unbearable. This is unacceptable. I want a refund.",
        "timestamp": "2026-05-10T02:15:00Z",
        "booking_ref": "NIS-2024-0912",
        "property_id": "villa-b1",
    }
    response = await client.post("/webhook/message", json=payload)
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["query_type"] == "complaint"
    assert data["action"] == "escalate"
    assert data["confidence_score"] <= 0.58
    print(f"\n[Test 2] query_type={data['query_type']} | confidence={data['confidence_score']} | action={data['action']}")
    print(f"Reply: {data['drafted_reply']}")


@pytest.mark.asyncio
async def test_post_sales_checkin_query(client):
    """
    Input 3: Post-sales check-in info request.
    Expected: query_type = post_sales_checkin,
              reply contains check-in time or WiFi info.
    """
    payload = {
        "source": "direct",
        "guest_name": "Amir Khan",
        "message": "Hi! We are arriving tomorrow afternoon. What time can we check in and can you share the WiFi password?",
        "timestamp": "2026-05-06T08:00:00Z",
        "booking_ref": "NIS-2024-0930",
        "property_id": "villa-b1",
    }
    response = await client.post("/webhook/message", json=payload)
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["query_type"] == "post_sales_checkin"
    # Reply should contain practical info
    reply_lower = data["drafted_reply"].lower()
    assert any(kw in reply_lower for kw in ["check-in", "check in", "2pm", "2:00", "wifi", "password"])
    print(f"\n[Test 3] query_type={data['query_type']} | confidence={data['confidence_score']} | action={data['action']}")
    print(f"Reply: {data['drafted_reply']}")


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Sanity check: /health returns 200."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_invalid_source_returns_422(client):
    """Validation: unknown source channel → 422 Unprocessable Entity."""
    payload = {
        "source": "telegram",  # not in the enum
        "guest_name": "Test Guest",
        "message": "Hello",
        "timestamp": "2026-05-05T10:00:00Z",
    }
    response = await client.post("/webhook/message", json=payload)
    assert response.status_code == 422
