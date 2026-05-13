"""
claude_service.py
-----------------
Handles everything related to calling the Claude API.

PROPERTY_CONTEXT  — mock property data injected into the system prompt
build_system_prompt() — assembles the full system prompt from context
get_drafted_reply()   — sends the message to Claude, returns (reply, raw_confidence)
compute_confidence()  — turns the raw score + query type into a final 0-1 value
determine_action()    — maps confidence + query type to auto_send / agent_review / escalate
"""

import httpx
import re

from app.config import settings
from app.models import ActionType, QueryType


# -- Mock property context ----------------------------------------------------------
# In a real system this would be fetched from a database using property_id.

PROPERTY_CONTEXT = """
PROPERTY: Villa B1, Assagao, North Goa
Bedrooms: 3  |  Max guests: 6  |  Private pool: Yes
Check-in: 2:00 PM  |  Check-out: 11:00 AM
Base rate: INR 18,000 per night (up to 4 guests)
Extra guest surcharge: INR 2,000 per night per person
WiFi password: Nistula@2024
Caretaker: Available 8am – 10pm
Chef on call: Yes (pre-booking required 24 hours in advance)
Availability April 20–24: Available
Cancellation policy: Free cancellation up to 7 days before check-in
"""

TONE_GUIDE = """
TONE & STYLE RULES:
- Warm, personal, and professional. Never robotic.
- Address the guest by first name.
- Be concise — guests read on mobile. Aim for 3–5 sentences max.
- If it's a complaint, lead with empathy before logistics.
- Never promise a refund; say "we will look into this right away".
- End with a clear next step or offer to help further.
"""


def build_system_prompt(query_type: QueryType) -> str:
    """
    Combines property context and tone guide into a system prompt.
    The query_type hint nudges Claude to focus on the right information.
    """
    focus_hints = {
        QueryType.pre_sales_availability: "Focus on availability and booking next steps.",
        QueryType.pre_sales_pricing:      "Provide the exact nightly rate and any extras clearly.",
        QueryType.post_sales_checkin:     "Give practical arrival info — directions, codes, contacts.",
        QueryType.special_request:        "Acknowledge the request and confirm what can be arranged.",
        QueryType.complaint:              "Lead with empathy. Acknowledge the issue. Escalate urgency.",
        QueryType.general_enquiry:        "Answer the question helpfully and invite follow-up.",
    }

    return (
        "You are a guest relations assistant for Nistula, a luxury villa rental company in Goa, India. "
        "Draft a reply to the guest message below using the property information provided.\n\n"
        f"PROPERTY INFORMATION:\n{PROPERTY_CONTEXT}\n\n"
        f"{TONE_GUIDE}\n\n"
        f"FOCUS FOR THIS MESSAGE: {focus_hints.get(query_type, '')}"
    )


async def get_drafted_reply(
    guest_name: str,
    message_text: str,
    query_type: QueryType,
    source: str,
) -> tuple[str, float]:

    system_prompt = build_system_prompt(query_type)

    user_content = (
        f"Guest name: {guest_name}\n"
        f"Source channel: {source}\n"
        f"Guest message: {message_text}\n\n"
        "Draft a reply. At the very end, on a new line, append your confidence that "
        "this reply fully and accurately answers the guest's question, "
        "formatted exactly as: [CONFIDENCE:0.XX]"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.claude_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.claude_model,
                "max_tokens": 500,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}],
            },
        )
        response.raise_for_status()

        # Everything stays inside the block so variables are always assigned
        raw_json = response.json()
        full_text = raw_json["content"][0]["text"].strip()

    # Parse confidence tag
    raw_confidence = 0.70
    match = re.search(r"\[CONFIDENCE:(0\.\d+)\]", full_text)
    if match:
        raw_confidence = float(match.group(1))
        full_text = full_text[: match.start()].strip()

    return full_text, raw_confidence


def compute_confidence(
    raw_ai_confidence: float,
    classification_confidence: float,
    query_type: QueryType,
) -> float:
    """
    Final confidence = weighted blend of:
      - raw_ai_confidence      (60%) — how sure Claude is about its own reply
      - classification_confidence (40%) — how sure the classifier is about query type

    Then adjusted by business rules:
      - Complaints are always capped at 0.58 so they always escalate.
      - Perfect 1.0 is never emitted (we don't want false certainty).

    Why this weighting?
    The AI reply quality matters most, but a misclassification can send
    the wrong reply — so classification certainty also carries weight.
    """
    score = (raw_ai_confidence * 0.60) + (classification_confidence * 0.40)

    # Hard rule: complaints must always escalate regardless of AI confidence
    if query_type == QueryType.complaint:
        score = min(score, 0.58)

    # Cap at 0.98 — we never claim perfect certainty
    score = min(score, 0.98)

    return round(score, 2)


def determine_action(confidence: float, query_type: QueryType) -> ActionType:
    """
    Maps a final confidence score to an action:
      auto_send    → >= 0.85 (high confidence, low-risk query)
      agent_review → 0.60 – 0.84
      escalate     → < 0.60 OR complaint (always needs human)
    """
    if query_type == QueryType.complaint:
        return ActionType.escalate
    if confidence >= 0.85:
        return ActionType.auto_send
    if confidence >= 0.60:
        return ActionType.agent_review
    return ActionType.escalate
