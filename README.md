# Demo App for MCP Toolbox (Python)

## Cymbal Bus Agent

This repository contains a Python version of the Cymbal Transit demo app that uses:

1. AlloyDB + MCP Toolbox for tool integration
2. Cloud Run for Toolbox and app deployment
3. Flask + optional LangChain intent parsing for agent behavior

## Architecture

- **App**: Flask web app (`app.py`) with chat UI (`templates/index.html`)
- **Tooling**: MCP Toolbox endpoint called over JSON-RPC (`tools/call`)
- **Data**:
  - `transit_policies` for RAG-style policy lookup
  - `bus_schedules` for route/timing/seat availability
  - `bookings` for ticket transactions

## Prerequisites

- Python 3.10+
- Google Cloud project with billing enabled
- AlloyDB cluster/instance
- MCP Toolbox deployed and reachable (Cloud Run recommended)

## 1. AlloyDB Setup

Use the quick setup codelab:

- https://codelabs.developers.google.com/quick-alloydb-setup

### Enable Extensions

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS google_ml_integration;
```

### Create Tables

```sql
-- Table 1: Transit Policies (Unstructured Data for RAG)
CREATE TABLE transit_policies (
    policy_id SERIAL PRIMARY KEY,
    category VARCHAR(50),
    policy_text TEXT,
    policy_embedding vector(768)
);

-- Table 2: Intercity Bus Schedules (Structured Data)
CREATE TABLE bus_schedules (
    trip_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    origin_city VARCHAR(100),
    destination_city VARCHAR(100),
    departure_time TIMESTAMP,
    arrival_time TIMESTAMP,
    available_seats INT DEFAULT 50,
    ticket_price DECIMAL(6,2)
);

-- Table 3: Booking Ledger (Transactional Action Data)
CREATE TABLE bookings (
    booking_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id UUID REFERENCES bus_schedules(trip_id),
    passenger_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'CONFIRMED',
    booking_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Ingest Data

```sql
-- 1) Insert policy text and native AlloyDB embeddings
INSERT INTO transit_policies (category, policy_text, policy_embedding)
VALUES
('Pets', 'Service animals are always welcome. Small pets (under 25 lbs) are allowed in secure carriers for a $25 fee. Large dogs are not permitted on standard coaches.', embedding('text-embedding-005', 'Service animals are always welcome. Small pets (under 25 lbs) are allowed in secure carriers for a $25 fee. Large dogs are not permitted on standard coaches.')),
('Luggage', 'Each passenger is allowed one carry-on (up to 15 lbs) and two stowed bags (up to 50 lbs each) free of charge. Additional bags cost $15 each.', embedding('text-embedding-005', 'Each passenger is allowed one carry-on (up to 15 lbs) and two stowed bags (up to 50 lbs each) free of charge. Additional bags cost $15 each.')),
('Refunds', 'Tickets are fully refundable up to 24 hours before departure. Within 24 hours, tickets can be exchanged for travel credit only.', embedding('text-embedding-005', 'Tickets are fully refundable up to 24 hours before departure. Within 24 hours, tickets can be exchanged for travel credit only.'));

-- 2) Insert 200+ realistic schedules
INSERT INTO bus_schedules (origin_city, destination_city, departure_time, arrival_time, ticket_price, available_seats)
SELECT
    origin,
    destination,
    (CURRENT_DATE + 1) + (interval '4 hours' * seq) AS dep_time,
    (CURRENT_DATE + 1) + (interval '4 hours' * seq) + interval '4.5 hours' AS arr_time,
    ROUND((RANDOM() * 30 + 25)::numeric, 2) AS price,
    FLOOR(RANDOM() * 50 + 1) AS seats
FROM
    (VALUES
        ('New York', 'Boston'), ('Boston', 'New York'),
        ('Philadelphia', 'Washington DC'), ('Washington DC', 'Philadelphia'),
        ('Seattle', 'Portland'), ('Portland', 'Seattle')
    ) AS routes(origin, destination)
CROSS JOIN generate_series(1, 40) AS seq;
```

## 2. MCP Toolbox Configuration

Create/update your `tools.yaml` for AlloyDB tools and replace all placeholders with your values.

You can keep values hardcoded or parameterize through environment variables.

If you are using the Java demo repo side-by-side, you can reuse the same `tools.yaml` design.

### Install Toolbox Binary

```bash
VERSION=0.27.0
curl -L -o toolbox https://storage.googleapis.com/genai-toolbox/v$VERSION/linux/amd64/toolbox
chmod +x toolbox
```

### Deploy Toolbox to Cloud Run

Follow the full guide, especially authentication/IAM setup:

- https://googleapis.github.io/genai-toolbox/how-to/deploy_toolbox/

## 3. Run This Python App Locally

### Create environment variables

Create a `.env` file in this folder:

```env
FLASK_SECRET_KEY=replace-with-random-secret
MCP_TOOLBOX_URL=https://YOUR_TOOLBOX_CLOUD_RUN_URL/mcp
MCP_TOOLBOX_API_KEY=
PORT=8080
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Start the app

```bash
python app.py
```

Open:

- http://localhost:8080

Health check:

- http://localhost:8080/health

## 4. Deploy App to Cloud Run

```bash
gcloud run deploy cymbal-transit-python \
  --source . \
  --set-env-vars MCP_TOOLBOX_URL=YOUR_MCP_TOOLBOX_URL,PORT=8080 \
  --allow-unauthenticated
```

Optional env vars:

- `FLASK_SECRET_KEY`
- `MCP_TOOLBOX_API_KEY`

## API Endpoints

- `POST /api/agent/chat` - plain text chat input
- `POST /chat` - SSE response endpoint
- `POST /api/book` - direct booking endpoint
- `GET /health` - app + toolbox status

## Notes

- This app talks directly to MCP Toolbox via JSON-RPC and does not require the old `mcp-toolbox-sdk-python` package.
- LangChain is used for optional intent parsing if installed (`langchain-core`).
- Keep `.env` out of source control.
