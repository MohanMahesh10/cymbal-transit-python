# Cymbal Bus Agentic App — MCP Toolbox Python SDK

<p align="center">
  <img src="https://github.com/user-attachments/assets/50aef5f8-4581-40f8-a379-a074c1f8b617" width="48%" alt="Screenshot 1"/>
  &nbsp;&nbsp;
  <img src="https://github.com/user-attachments/assets/aa6f3e0c-f6d2-45b8-882f-2b871caa832f" width="48%" alt="Screenshot 2"/>
</p>

---

## Overview

This is the Python version of the **Cymbal Bus Agent** demo — an AI-powered transit concierge that helps users search bus schedules, book tickets, and query transit policies via natural language.

It uses:

1. **AlloyDB** for structured schedule data, booking records, and vector-based policy search
2. **MCP Toolbox** deployed on Cloud Run for tool integration
3. **LangChain (Python)** for agent orchestration and intent routing in a Flask app

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Web Framework | Flask >= 2.3.0 |
| Agent Orchestration | LangChain Core >= 0.3.0 |
| Tool Integration | MCP Toolbox Python SDK (`toolbox-core`) |
| Database | AlloyDB PostgreSQL (with `vector` + `google_ml_integration` extensions) |
| Hosting | Google Cloud Run |

---

## Supported Routes

### 🇺🇸 US Routes
- New York ↔ Boston
- Philadelphia ↔ Washington DC
- Seattle ↔ Portland

### 🇮🇳 India Routes

**South India**
- Chennai ↔ Hyderabad, Bangalore, Delhi, Pune, Coimbatore, Madurai, Tiruchirappalli, Salem, Vijayawada, Visakhapatnam
- Hyderabad ↔ Bangalore, Mumbai, Vijayawada, Visakhapatnam, Tirupati, Warangal, Nagpur
- Bangalore ↔ Mysore, Coimbatore, Mangalore, Pune

**North / West / East India**
- Mumbai ↔ Delhi, Pune, Ahmedabad, Nashik, Surat
- Delhi ↔ Jaipur, Chandigarh, Lucknow
- Kolkata ↔ Bhubaneswar, Ranchi

All routes run **every 4 hours** for the **next 7 days**, seeded fresh on each database reset.

---

## AlloyDB Setup

### Install AlloyDB Cluster and Instance

Follow the setup codelab:
[https://codelabs.developers.google.com/quick-alloydb-setup](https://codelabs.developers.google.com/quick-alloydb-setup)

### Enable Extensions

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS google_ml_integration;
```

### Create Tables

```sql
-- Transit Policies (for semantic/RAG search)
CREATE TABLE transit_policies (
  policy_id SERIAL PRIMARY KEY,
  category VARCHAR(50),
  policy_text TEXT,
  policy_embedding vector(768)
);

-- Bus Schedules (structured, queryable)
CREATE TABLE bus_schedules (
  trip_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  origin_city VARCHAR(100),
  destination_city VARCHAR(100),
  departure_time TIMESTAMP,
  arrival_time TIMESTAMP,
  available_seats INT DEFAULT 50,
  ticket_price DECIMAL(6,2)
);

-- Bookings Ledger (transactional)
CREATE TABLE bookings (
  booking_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trip_id UUID REFERENCES bus_schedules(trip_id),
  passenger_id VARCHAR(100),
  status VARCHAR(20) DEFAULT 'CONFIRMED',
  booking_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Seed Transit Policies

```sql
INSERT INTO transit_policies (category, policy_text, policy_embedding)
VALUES
  ('Pets', 'Service animals are always welcome. Small pets (under 25 lbs) are allowed in secure carriers for a $25 fee. Large dogs are not permitted on standard coaches.',
   embedding('text-embedding-005', 'Service animals are always welcome. Small pets (under 25 lbs) are allowed in secure carriers for a $25 fee. Large dogs are not permitted on standard coaches.')),
  ('Luggage', 'Each passenger is allowed one carry-on (up to 15 lbs) and two stowed bags (up to 50 lbs each) free of charge. Additional bags cost $15 each.',
   embedding('text-embedding-005', 'Each passenger is allowed one carry-on (up to 15 lbs) and two stowed bags (up to 50 lbs each) free of charge. Additional bags cost $15 each.')),
  ('Refunds', 'Tickets are fully refundable up to 24 hours before departure. Within 24 hours, tickets can be exchanged for travel credit only.',
   embedding('text-embedding-005', 'Tickets are fully refundable up to 24 hours before departure. Within 24 hours, tickets can be exchanged for travel credit only.'));
```

### Seed Bus Schedules (US + India Routes)

> **Important:** Always truncate with `CASCADE` first to avoid foreign key conflicts with the `bookings` table.

```sql
-- Step 1: Clear existing data (CASCADE handles bookings FK)
TRUNCATE bus_schedules CASCADE;

-- Step 2: Re-insert schedules for next 7 days, every 4 hours
INSERT INTO bus_schedules (
    origin_city, destination_city, departure_time, arrival_time, ticket_price, available_seats
)
SELECT
    r.origin_city,
    r.destination_city,
    dep.dep_time,
    dep.dep_time + make_interval(mins => r.duration_minutes) AS arrival_time,
    ROUND((random() * (r.max_price - r.min_price) + r.min_price)::numeric, 2) AS ticket_price,
    FLOOR(random() * 50 + 1)::int AS available_seats
FROM (
    VALUES
        -- US routes
        ('New York', 'Boston', 270, 25, 55),
        ('Boston', 'New York', 270, 25, 55),
        ('Philadelphia', 'Washington DC', 180, 20, 50),
        ('Washington DC', 'Philadelphia', 180, 20, 50),
        ('Seattle', 'Portland', 270, 25, 55),
        ('Portland', 'Seattle', 270, 25, 55),
        -- South India
        ('Chennai', 'Hyderabad', 630, 500, 1700),
        ('Hyderabad', 'Chennai', 630, 500, 1700),
        ('Chennai', 'Bangalore', 420, 350, 1200),
        ('Bangalore', 'Chennai', 420, 350, 1200),
        ('Bangalore', 'Hyderabad', 540, 450, 1500),
        ('Hyderabad', 'Bangalore', 540, 450, 1500),
        ('Mumbai', 'Hyderabad', 780, 700, 2200),
        ('Hyderabad', 'Mumbai', 780, 700, 2200),
        ('Mumbai', 'Delhi', 1500, 1000, 2800),
        ('Delhi', 'Mumbai', 1500, 1000, 2800),
        ('Chennai', 'Delhi', 2100, 1200, 3200),
        ('Delhi', 'Chennai', 2100, 1200, 3200),
        ('Pune', 'Mumbai', 240, 250, 900),
        ('Mumbai', 'Pune', 240, 250, 900),
        ('Ahmedabad', 'Mumbai', 510, 450, 1500),
        ('Mumbai', 'Ahmedabad', 510, 450, 1500),
        ('Chennai', 'Pune', 900, 800, 2400),
        ('Pune', 'Chennai', 900, 800, 2400),
        ('Chennai', 'Coimbatore', 510, 400, 1400),
        ('Coimbatore', 'Chennai', 510, 400, 1400),
        ('Chennai', 'Madurai', 510, 450, 1500),
        ('Madurai', 'Chennai', 510, 450, 1500),
        ('Chennai', 'Tiruchirappalli', 420, 350, 1200),
        ('Tiruchirappalli', 'Chennai', 420, 350, 1200),
        ('Chennai', 'Salem', 300, 300, 1000),
        ('Salem', 'Chennai', 300, 300, 1000),
        ('Chennai', 'Vijayawada', 450, 450, 1400),
        ('Vijayawada', 'Chennai', 450, 450, 1400),
        ('Chennai', 'Visakhapatnam', 840, 800, 2200),
        ('Visakhapatnam', 'Chennai', 840, 800, 2200),
        ('Hyderabad', 'Vijayawada', 330, 300, 1000),
        ('Vijayawada', 'Hyderabad', 330, 300, 1000),
        ('Hyderabad', 'Visakhapatnam', 720, 700, 2000),
        ('Visakhapatnam', 'Hyderabad', 720, 700, 2000),
        ('Hyderabad', 'Tirupati', 720, 600, 1800),
        ('Tirupati', 'Hyderabad', 720, 600, 1800),
        ('Hyderabad', 'Warangal', 180, 200, 700),
        ('Warangal', 'Hyderabad', 180, 200, 700),
        ('Hyderabad', 'Nagpur', 600, 600, 1800),
        ('Nagpur', 'Hyderabad', 600, 600, 1800),
        ('Bangalore', 'Mysore', 180, 200, 700),
        ('Mysore', 'Bangalore', 180, 200, 700),
        ('Bangalore', 'Coimbatore', 420, 350, 1200),
        ('Coimbatore', 'Bangalore', 420, 350, 1200),
        ('Bangalore', 'Mangalore', 420, 400, 1400),
        ('Mangalore', 'Bangalore', 420, 400, 1400),
        ('Bangalore', 'Pune', 840, 700, 2200),
        ('Pune', 'Bangalore', 840, 700, 2200),
        -- North / West / East India
        ('Delhi', 'Jaipur', 300, 300, 1000),
        ('Jaipur', 'Delhi', 300, 300, 1000),
        ('Delhi', 'Chandigarh', 300, 300, 1000),
        ('Chandigarh', 'Delhi', 300, 300, 1000),
        ('Delhi', 'Lucknow', 600, 500, 1700),
        ('Lucknow', 'Delhi', 600, 500, 1700),
        ('Mumbai', 'Nashik', 240, 250, 900),
        ('Nashik', 'Mumbai', 240, 250, 900),
        ('Mumbai', 'Surat', 300, 300, 1000),
        ('Surat', 'Mumbai', 300, 300, 1000),
        ('Kolkata', 'Bhubaneswar', 420, 350, 1200),
        ('Bhubaneswar', 'Kolkata', 420, 350, 1200),
        ('Kolkata', 'Ranchi', 420, 350, 1200),
        ('Ranchi', 'Kolkata', 420, 350, 1200)
) AS r(origin_city, destination_city, duration_minutes, min_price, max_price)
CROSS JOIN LATERAL (
    SELECT generate_series(
        date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'UTC') + interval '1 day',
        date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'UTC') + interval '7 days' + interval '20 hours',
        interval '4 hours'
    ) AS dep_time
) AS dep;
```

---

## tools.yaml Configuration

Use the `tools.yaml` file in this repository. Replace all placeholders with your actual values or use environment variable expansion.

> **Do not commit real secrets** — use environment variable references like `${YOUR_VAR}`.

---

## Install MCP Toolbox

```bash
export VERSION=0.27.0
curl -L -o toolbox https://storage.googleapis.com/genai-toolbox/v$VERSION/linux/amd64/toolbox
chmod +x toolbox
```

## Deploy Toolbox to Cloud Run

Follow the official documentation:
[https://googleapis.github.io/genai-toolbox/how-to/deploy_toolbox/](https://googleapis.github.io/genai-toolbox/how-to/deploy_toolbox/)

---

## Run the Python App Locally

```bash
git clone https://github.com/MohanMahesh10/cymbal-transit-python.git
cd cymbal-transit-python
python -m venv .venv
source .venv/bin/activate       # Linux / macOS
# .venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -r requirements.txt
python app.py
```

App URL: [http://localhost:8080](http://localhost:8080)

---

## Deploy to Cloud Run

> **Note:** Do NOT include `PORT=8080` in `--set-env-vars`. Cloud Run sets `PORT` automatically — passing it manually causes a deployment error.

```bash
gcloud run deploy cymbal-transit-python \
  --source . \
  --region us-central1 \
  --set-env-vars GCP_PROJECT_ID=<YOUR_PROJECT_ID>,GCP_REGION=us-central1,GEMINI_MODEL_NAME=gemini-2.5-flash,MCP_TOOLBOX_URL=<YOUR_MCP_TOOLBOX_URL> \
  --allow-unauthenticated
```

Replace `<YOUR_PROJECT_ID>` and `<YOUR_MCP_TOOLBOX_URL>` with your values.

---

## Dockerfile Notes

The `Dockerfile` uses **Python 3.11-slim** (required for `X | Y` union type hints used in `app.py`). The `ENV PORT` line is intentionally omitted — Cloud Run injects it automatically.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["python", "app.py"]
```

---

## App Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Chat UI |
| GET | `/health` | Health check |
| POST | `/chat` | SSE streaming chat |
| POST | `/api/agent/chat` | Plain text chat |
| POST | `/api/agent/chat/stream` | Token-streaming chat |
| POST | `/api/agent/book` | Direct booking API |
| POST | `/api/book` | Alias for booking |

---

## Example Queries

```
i need a bus from chennai to salem
i need a bus from hyderabad to bangalore tomorrow
i need a bus from mumbai to delhi
book a ticket
how many seats are available?
what is the refund policy?
```

---

## Notes

- This is the Python adaptation of [cymbal-transit (Java)](https://github.com/AbiramiSukumaran/cymbal-transit).
- The app uses `tools.yaml` for MCP tool configuration.
- Schedules use UTC timestamps. The `query-schedules` tool uses `::date` casting to avoid timezone mismatch issues when filtering by date.
- Indian city aliases are supported: `bengaluru` → Bangalore, `bombay` → Mumbai, `hyd` → Hyderabad, etc.

## Codelab

[https://codelabs.developers.google.com/cymbal-bus-agent-mcp-toolbox-java](https://codelabs.developers.google.com/cymbal-bus-agent-mcp-toolbox-java)
