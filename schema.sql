-- =============================================================
-- Nistula Database Schema Submission 
-- =============================================================
-- My main goals for this design:
--   1. Make sure one real human = one guest profile, no matter how they contact us.
--   2. Dump all messages into one central table so we aren't querying 5 different tables.
--   3. Group messages into conversations linked to specific reservations.
--   4. Keep a strict audit trail of who sent what (AI vs Human).
-- =============================================================


-- ── Extensions ────────────────────────────────────────────────
-- Using pgcrypto so I can generate UUIDs natively.
-- I went with UUIDs instead of standard auto-incrementing integers 
-- to prevent ID collisions if the system scales up across microservices.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- =============================================================
-- 1. PROPERTIES
-- =============================================================
-- I decided to put property details in the database rather than hardcoding 
-- them in the app. This way, if Nistula changes a base rate or check-in time, 
-- they just update the DB and the AI immediately gets the new context 
-- without needing a code deploy.

CREATE TABLE properties (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_code   VARCHAR(50) UNIQUE NOT NULL,  -- e.g. "villa-b1"
    display_name    TEXT NOT NULL,
    location        TEXT,
    bedrooms        INTEGER,
    max_guests      INTEGER,
    base_rate_inr   NUMERIC(10,2),
    extra_guest_fee NUMERIC(10,2),
    check_in_time   TIME,
    check_out_time  TIME,
    wifi_password   TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE properties IS
    'Stores dynamic property info to inject into the Claude system prompt.';

COMMENT ON COLUMN properties.property_code IS
    'Matches the property_id string we get from the incoming webhook.';


-- =============================================================
-- 2. GUEST PROFILES
-- =============================================================
-- This is the canonical profile for a real human being. 
-- I didn't put WhatsApp numbers or Airbnb IDs directly in this table 
-- because one person might use multiple channels, and we don't want 
-- to accidentally create 3 separate profiles for the same guest.

CREATE TABLE guest_profiles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name    TEXT NOT NULL,
    email           TEXT,                 -- optional; not always available
    phone           TEXT,                 -- E.164 format when available
    notes           TEXT,                 -- internal agent notes
    vip             BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE guest_profiles IS
    'The core human guest. Actual channel IDs are stored in channel_identities.';

-- Only enforce unique emails if the email actually exists
CREATE UNIQUE INDEX IF NOT EXISTS uix_guest_profiles_email
    ON guest_profiles (email)
    WHERE email IS NOT NULL;


-- =============================================================
-- 3. CHANNEL IDENTITIES
-- =============================================================
-- This was my hardest design decision! It acts as a bridge. 
-- If Rahul texts on WhatsApp and later emails us, both those external IDs 
-- live here and link back to his single guest_profile_id. 

CREATE TYPE channel_source AS ENUM (
    'whatsapp',
    'booking_com',
    'airbnb',
    'instagram',
    'direct'
);

CREATE TABLE channel_identities (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guest_profile_id UUID NOT NULL REFERENCES guest_profiles(id) ON DELETE CASCADE,
    source           channel_source NOT NULL,
    external_id      TEXT NOT NULL,        -- e.g. WhatsApp number, Booking.com guest ID
    display_name     TEXT,                 -- what they call themselves on this specific app
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (source, external_id)          -- prevents saving the same WhatsApp number twice
);

COMMENT ON TABLE channel_identities IS
    'Resolves a specific app ID (like a phone number) to a master guest profile.';


-- =============================================================
-- 4. RESERVATIONS
-- =============================================================
-- Standard booking info.

CREATE TYPE reservation_status AS ENUM (
    'enquiry',       -- not yet confirmed
    'confirmed',
    'checked_in',
    'checked_out',
    'cancelled'
);

CREATE TABLE reservations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_ref      VARCHAR(50) UNIQUE NOT NULL,  -- e.g. "NIS-2024-0891"
    guest_profile_id UUID NOT NULL REFERENCES guest_profiles(id),
    property_id      UUID NOT NULL REFERENCES properties(id),
    status           reservation_status NOT NULL DEFAULT 'enquiry',
    check_in_date    DATE,
    check_out_date   DATE,
    guest_count      INTEGER,
    -- I let Postgres calculate total_nights automatically so the backend doesn't have to
    total_nights     INTEGER GENERATED ALWAYS AS 
                         (check_out_date - check_in_date) STORED,
    total_amount_inr NUMERIC(12,2),
    channel_source   channel_source,       
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE reservations IS
    'Tracks stays. The booking_ref ties back to the webhook payload.';


-- =============================================================
-- 5. CONVERSATIONS
-- =============================================================
-- I added this to group messages into logical threads (like a ticketing system).
-- A pre-booking chat won't have a reservation yet, so reservation_id is nullable.

CREATE TABLE conversations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guest_profile_id UUID NOT NULL REFERENCES guest_profiles(id),
    reservation_id   UUID REFERENCES reservations(id),  
    property_id      UUID REFERENCES properties(id),
    source           channel_source NOT NULL,
    subject          TEXT,                               -- e.g. "WiFi issue — May 2026"
    status           VARCHAR(30) NOT NULL DEFAULT 'open',  -- open / resolved / escalated
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_conversations_guest ON conversations (guest_profile_id);
CREATE INDEX ix_conversations_reservation ON conversations (reservation_id);


-- =============================================================
-- 6. MESSAGES
-- =============================================================
-- The main event. Every single message lives here.

CREATE TYPE query_type AS ENUM (
    'pre_sales_availability',
    'pre_sales_pricing',
    'post_sales_checkin',
    'special_request',
    'complaint',
    'general_enquiry'
);

CREATE TYPE message_direction AS ENUM ('inbound', 'outbound');

CREATE TYPE send_status AS ENUM (
    'ai_drafted',      -- AI wrote it, waiting for human
    'agent_edited',    -- Human tweaked the AI draft
    'agent_composed',  -- Human wrote it from scratch
    'auto_sent',       -- AI was confident enough to send it alone
    'agent_sent',      
    'failed'           
);

CREATE TABLE messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    direction        message_direction NOT NULL,
    source           channel_source NOT NULL,

    -- Content
    body             TEXT NOT NULL,
    -- If a human edits the AI draft, we save the AI's original thought here for auditing
    original_body    TEXT,               

    -- AI Classification info
    query_type       query_type,
    ai_confidence    NUMERIC(4,3),       -- Outbound messages will just leave this null
    action_taken     VARCHAR(30),        

    -- Send tracking 
    send_status      send_status,
    sent_at          TIMESTAMPTZ,
    sent_by_agent_id UUID,               

    -- Webhook Metadata
    external_msg_id  TEXT,               -- The ID given by WhatsApp/Airbnb etc.
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE messages IS
    'Holds all chat history. We store the AI confidence here so we can analyze its performance over time.';

-- Idempotency check: If a webhook fails and retries, this index stops us 
-- from processing the exact same WhatsApp message twice.
CREATE UNIQUE INDEX IF NOT EXISTS uix_messages_external_id
    ON messages (source, external_msg_id)
    WHERE external_msg_id IS NOT NULL;

CREATE INDEX ix_messages_conversation ON messages (conversation_id, created_at DESC);
CREATE INDEX ix_messages_query_type   ON messages (query_type);
CREATE INDEX ix_messages_confidence   ON messages (ai_confidence);


-- =============================================================
-- 7. AGENT_ACTIONS AUDIT LOG
-- =============================================================
-- Basically an append-only log. If a human touches a message, it gets tracked here.
-- Super important for figuring out why an agent overrode the AI, or just for general QA.

CREATE TABLE agent_actions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id       UUID NOT NULL REFERENCES messages(id),
    agent_id         UUID,               
    action           VARCHAR(50) NOT NULL, -- e.g., 'edit_draft', 'escalate'
    note             TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE agent_actions IS
    'Immutable audit trail. Rows here should never be updated or deleted.';


-- =============================================================
-- DESIGN DECISION: HARDEST CHOICE
-- =============================================================
-- See thinking.md for the full write-up.
-- TL;DR: Separating channel_identities from guest_profiles was
-- the hardest decision.  The alternative (one row in guest_profiles
-- per channel identity) would be simpler but would fragment guest
-- history and make cross-channel analytics impossible.
-- =============================================================
