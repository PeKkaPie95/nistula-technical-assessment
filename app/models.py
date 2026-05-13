"""
models.py
---------
All Pydantic models used across the app.

InboundMessage   — the raw webhook payload we receive from any channel
UnifiedMessage   — the normalised internal schema (always consistent)
WebhookResponse  — what we return to the caller
"""

from datetime import datetime
from enum import Enum
from typing import Optional
import uuid

from pydantic import BaseModel, Field


# -- Enums -------------------------------------------------------------------

class SourceChannel(str, Enum):
    whatsapp    = "whatsapp"
    booking_com = "booking_com"
    airbnb      = "airbnb"
    instagram   = "instagram"
    direct      = "direct"


class QueryType(str, Enum):
    pre_sales_availability = "pre_sales_availability"
    pre_sales_pricing      = "pre_sales_pricing"
    post_sales_checkin     = "post_sales_checkin"
    special_request        = "special_request"
    complaint              = "complaint"
    general_enquiry        = "general_enquiry"


class ActionType(str, Enum):
    auto_send     = "auto_send"       # confidence >= 0.85
    agent_review  = "agent_review"    # confidence 0.60 – 0.84
    escalate      = "escalate"        # confidence < 0.60 OR complaint


# -- Inbound payload ---------------------------------------------------------

class InboundMessage(BaseModel):
    """
    The raw payload posted to /webhook/message.
    source, booking_ref and property_id are optional because
    some channels (e.g. instagram DM) may not carry them.
    """
    source:       SourceChannel
    guest_name:   str
    message:      str
    timestamp:    datetime
    booking_ref:  Optional[str] = None
    property_id:  Optional[str] = None


# -- Unified internal schema -------------------------------------------------

class UnifiedMessage(BaseModel):
    """
    Every inbound message is normalised into this shape before
    being handed to the AI layer.  message_id is generated here
    so it travels through the whole pipeline consistently.
    """
    message_id:   str = Field(default_factory=lambda: str(uuid.uuid4()))
    source:       SourceChannel
    guest_name:   str
    message_text: str
    timestamp:    datetime
    booking_ref:  Optional[str] = None
    property_id:  Optional[str] = None
    query_type:   Optional[QueryType] = None   # filled by classifier


# -- API response ------------------------------------------------------------

class WebhookResponse(BaseModel):
    message_id:       str
    query_type:       QueryType
    drafted_reply:    str
    confidence_score: float
    action:           ActionType
