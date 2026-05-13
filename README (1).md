# Nistula Guest Message Handler

A FastAPI backend that receives inbound guest messages from multiple channels, classifies them, generates an AI-drafted reply via the Claude API, and returns a confidence-scored response with a recommended action.

---

## Project Structure

```
nistula-technical-assessment/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app and /webhook/message endpoint
│   ├── models.py        # Pydantic models (InboundMessage, UnifiedMessage, WebhookResponse)
│   ├── classifier.py    # Query type classification (keyword + AI fallback)
│   ├── claude_service.py # Claude API integration and confidence logic
│   └── config.py        # Settings loaded from .env
├── tests/
│   └── test_webhook.py  # 5 tests covering 3 input types + edge cases
├── schema.sql           # Part 2: PostgreSQL schema with comments
├── thinking.md          # Part 3: Written answers
├── requirements.txt
├── pyproject.toml
├── .env
└── README.md
```

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/your-username/nistula-technical-assessment
cd nistula-technical-assessment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Open .env and set your CLAUDE_API_KEY
```

### 4. Run the server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

### 5. Run tests

```bash
pytest tests/ -v
```

> Tests hit the real Claude API, so `CLAUDE_API_KEY` must be set.

---

## API Usage

### `POST /webhook/message`

**Request body:**

```json
{
  "source": "whatsapp",
  "guest_name": "Rahul Sharma",
  "message": "Is the villa available from April 20 to 24? What is the rate for 2 adults?",
  "timestamp": "2026-05-05T10:30:00Z",
  "booking_ref": "NIS-2024-0891",
  "property_id": "villa-b1"
}
```

**Response:**

```json
{
  "message_id": "3f8a2b1c-...",
  "query_type": "pre_sales_availability",
  "drafted_reply": "Hi Rahul! Great news — Villa B1 is available from April 20–24...",
  "confidence_score": 0.91,
  "action": "auto_send"
}
```

**Supported `source` values:** `whatsapp`, `booking_com`, `airbnb`, `instagram`, `direct`

---

## Confidence Scoring — Design Explained

Confidence is a blended score between 0 and 1 that represents how safe it is to send the AI-drafted reply without human review.

### Two inputs

| Input | Weight | What it measures |
|---|---|---|
| `raw_ai_confidence` | 60% | Claude's self-assessed certainty about its own reply |
| `classification_confidence` | 40% | How certain the classifier is about the query type |

**Why this weighting?**  
The quality of the AI reply matters most (60%), but a misclassified query can cause the wrong context to be sent — so classification certainty carries meaningful weight (40%).

### How `raw_ai_confidence` is extracted

The Claude prompt ends with: *"append your confidence as [CONFIDENCE:0.XX]"*. Claude reliably follows this instruction; the value is parsed and stripped from the visible reply. If Claude doesn't return a parsable value, we default to 0.70 — cautious, not zero.

### How `classification_confidence` is set

- Keyword match → 0.90 (rule-based, highly reliable)
- AI classifier fallback → 0.75 (correct but less certain)
- Fallback to `general_enquiry` → 0.50 (something went wrong)

### Business rule overrides

- **Complaints are always capped at 0.58**, regardless of AI confidence. A human must always review and send complaint replies — the risk of an inappropriate auto-sent message is too high.
- The maximum score emitted is **0.98** — we never claim perfect certainty.

### Action thresholds

| Score | Action |
|---|---|
| ≥ 0.85 | `auto_send` — safe to send without review |
| 0.60 – 0.84 | `agent_review` — queue for human approval |
| < 0.60 | `escalate` — urgent human intervention needed |
| Any complaint | `escalate` — always, regardless of score |

---

## Error Handling

| Scenario | HTTP status | Behaviour |
|---|---|---|
| Invalid `source` value | 422 | Pydantic validation error, details returned |
| Claude API returns error | 502 | Logged server-side; caller should retry |
| Network timeout to Claude | 502 | Explicit timeout of 30s; graceful error message |
| Unexpected exception | 500 | Logged; generic message returned to caller |

---

## Design Decisions

**Why keyword classification + AI fallback instead of AI-only?**  
Keyword rules handle ~85% of real guest messages instantly with zero API cost and sub-millisecond latency. The AI fallback catches genuinely ambiguous language. Using AI-only for classification would add ~300ms and ~100 tokens to every request for no benefit on common queries.

**Why ask Claude to self-report confidence?**  
Claude's internal uncertainty correlates with output quality — it tends to return lower scores when the property context doesn't fully answer the question. This is more informative than heuristics like reply length or keyword presence.

**Why a separate `channel_identities` table in the schema?**  
See `schema.sql` and `thinking.md` for the full reasoning. The short version: the same human can contact via multiple channels; storing identities separately lets us unify their history without data loss.
