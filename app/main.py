"""
main.py
-------
FastAPI application entry point.

Endpoints:
  POST /webhook/message  — receives inbound guest messages, returns AI-drafted reply
  GET  /health           — liveness check for ops / deployment monitoring

The pipeline for /webhook/message:
  1. Validate & deserialise the inbound payload (FastAPI does this via Pydantic)
  2. Normalise into UnifiedMessage (adds message_id, standardises field names)
  3. Classify the message into a QueryType
  4. Call Claude to generate a drafted reply
  5. Compute the final confidence score
  6. Determine the action (auto_send / agent_review / escalate)
  7. Return the WebhookResponse

Error handling:
  - Validation errors → 422 (FastAPI default)
  - Claude API errors → 502 (upstream failure, caller should retry)
  - Unexpected errors → 500 with detail logged server-side
"""

import logging
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.classifier import classify
from app.claude_service import compute_confidence, determine_action, get_drafted_reply
from app.models import InboundMessage, UnifiedMessage, WebhookResponse

# -- Logging ----------------------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("nistula")

# -- App --------------------------------------------------------------------------------------------------
app = FastAPI(
    title="Nistula Guest Message Handler",
    description="Webhook that receives guest messages, classifies them, and returns AI-drafted replies.",
    version="1.0.0",
)


# -- Global exception handler -----------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s", request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."},
    )


# -- Routes -----------------------------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health():
    """Simple liveness check."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/webhook/message", response_model=WebhookResponse, tags=["webhook"])
async def handle_message(payload: InboundMessage):
    """
    Main webhook endpoint.

    Accepts a raw guest message from any supported channel,
    runs it through the full pipeline, and returns a drafted reply
    with a confidence score and recommended action.
    """
    logger.info(
        "Received message | source=%s | guest=%s | property=%s",
        payload.source,
        payload.guest_name,
        payload.property_id,
    )

    # -- Step 1: Normalise into unified schema ----------------------------------------------------
    unified = UnifiedMessage(
        source=payload.source,
        guest_name=payload.guest_name,
        message_text=payload.message,
        timestamp=payload.timestamp,
        booking_ref=payload.booking_ref,
        property_id=payload.property_id,
    )

    # -- Step 2: Classify the message -------------------------------------------------------------
    query_type, classification_confidence = await classify(unified.message_text)
    unified.query_type = query_type

    logger.info(
        "Classified | message_id=%s | query_type=%s | classification_confidence=%.2f",
        unified.message_id,
        query_type,
        classification_confidence,
    )

    # -- Step 3: Get AI-drafted reply -------------------------------------------------------------
    try:
        drafted_reply, raw_ai_confidence = await get_drafted_reply(
            guest_name=unified.guest_name,
            message_text=unified.message_text,
            query_type=query_type,
            source=str(unified.source.value),
        )
    except httpx.HTTPStatusError as exc:
        logger.error("Claude API error: %s", exc.response.text)
        raise HTTPException(
            status_code=502,
            detail=f"AI service returned an error: {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        logger.error("Claude API connection error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Could not reach AI service. Please retry.",
        )

    # -- Step 4: Compute final confidence & action ------------------------------------------------
    confidence = compute_confidence(
        raw_ai_confidence=raw_ai_confidence,
        classification_confidence=classification_confidence,
        query_type=query_type,
    )
    action = determine_action(confidence, query_type)

    logger.info(
        "Reply drafted | message_id=%s | confidence=%.2f | action=%s",
        unified.message_id,
        confidence,
        action,
    )

    return WebhookResponse(
        message_id=unified.message_id,
        query_type=query_type,
        drafted_reply=drafted_reply,
        confidence_score=confidence,
        action=action,
    )
