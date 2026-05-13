"""
classifier.py
-------------
Classifies an inbound message into one of six QueryType values.

Strategy: keyword matching first (fast, zero cost), falling back to
a short Claude call if the message is ambiguous.

The keyword approach handles the vast majority of real guest messages.
The AI fallback catches edge cases like "we can't get warm" (complaint
about hot water, not a checkin question).

Returns (QueryType, confidence: float)
  — keyword match   → 0.90
  — AI classified   → 0.75  (AI is right but we're less certain)
  — fallback        → general_enquiry, 0.50
"""

import re
from typing import Tuple

from app.models import QueryType


# -- Keyword rule table ---------------------------------------------
# Each rule is (QueryType, list-of-regex-patterns).
# Patterns are checked in order; first match wins.

_RULES: list[Tuple[QueryType, list[str]]] = [
    (
        QueryType.complaint,
        [
            r"\b(not working|broken|doesn.t work|issue|problem|unacceptable|refund"
            r"|unhappy|terrible|disgusting|no hot water|no water|no electricity"
            r"|no wifi|no power|leaking|flood|cockroach|dirty|smell|stink)\b",
            r"\b(i (am|want|need|demand)|this is)\b.{0,40}\b(unacceptable|awful|wrong|disgrace)\b",
        ],
    ),
    (
        QueryType.pre_sales_availability,
        [
            r"\b(available|availability|free|vacancy|open|book|dates?)\b",
            r"\b(april|may|june|july|august|september|october|november|december"
            r"|january|february|march)\b.{0,30}\b(to|till|until|-)\b",
        ],
    ),
    (
        QueryType.pre_sales_pricing,
        [
            r"\b(rate|price|cost|charge|fee|tariff|how much|per night|per person"
            r"|for \d+ (adult|guest|night|person))\b",
        ],
    ),
    (
        QueryType.post_sales_checkin,
        [
            r"\b(check.?in|check.?out|arrival|depart|wifi|wi-fi|password"
            r"|access code|gate code|directions?|how to (get|reach|find)"
            r"|address|pin location|google maps)\b",
        ],
    ),
    (
        QueryType.special_request,
        [
            r"\b(early check.?in|late check.?out|airport (transfer|pickup|drop)"
            r"|extra bed|baby cot|crib|wheelchair|allerg|vegan|diet"
            r"|birthday|anniversary|surprise|decoration|flowers)\b",
        ],
    ),
    (
        QueryType.general_enquiry,
        [
            r"\b(pet|dog|cat|animal|park|pool|chef|cook|staff|caretaker"
            r"|gym|spa|bbq|barbeque|barbecue|beach|distance|nearby|facilities)\b",
        ],
    ),
]

_FLAGS = re.IGNORECASE | re.DOTALL


def classify_by_keyword(text: str) -> Tuple[QueryType, float] | None:
    """Return (QueryType, confidence) if a keyword rule fires, else None."""
    for query_type, patterns in _RULES:
        for pattern in patterns:
            if re.search(pattern, text, _FLAGS):
                return query_type, 0.90
    return None


async def classify_by_ai(text: str) -> Tuple[QueryType, float]:
    """
    Ask Claude to classify the message.
    Only called when keyword matching finds nothing.
    Returns (QueryType, 0.75).
    """
    import httpx
    from app.config import settings

    system = (
        "You are a message classifier for a luxury villa rental platform. "
        "Classify the guest message into EXACTLY ONE of these categories:\n"
        "pre_sales_availability, pre_sales_pricing, post_sales_checkin, "
        "special_request, complaint, general_enquiry\n\n"
        "Respond with only the category name, nothing else."
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.claude_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.claude_model,
                "max_tokens": 20,
                "system": system,
                "messages": [{"role": "user", "content": text}],
            },
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip().lower()

    # Map AI response back to enum; fall back to general_enquiry
    try:
        return QueryType(raw), 0.75
    except ValueError:
        return QueryType.general_enquiry, 0.50


async def classify(text: str) -> Tuple[QueryType, float]:
    """Public entry point — keyword first, AI fallback."""
    result = classify_by_keyword(text)
    if result:
        return result
    return await classify_by_ai(text)
