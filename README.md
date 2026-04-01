# Demo App for MCP Toolbox Python SDK

## Cymbal Bus Agent (Python Version)

This project is the Python version of the Cymbal Bus Agent demo.

It uses:

1. AlloyDB database and MCP Toolbox for tools integration.
2. Cloud Run for Toolbox deployment and application deployment.
3. LangChain (Python) for agent orchestration and LLM workflow in a Flask app.

## Tech Stack

- Python 3.10+
- Flask
- LangChain Core
- MCP Toolbox Python SDK (`toolbox-core`)
- AlloyDB PostgreSQL (`vector` + `google_ml_integration` extensions)

## AlloyDB Setup

### Install AlloyDB Cluster and Instance

Use the setup codelab:

https://codelabs.developers.google.com/quick-alloydb-setup

### Extensions

```sql
-- Enable necessary extensions for AI semantic search and embedding generation
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS google_ml_integration;
```

### Create Table DDL

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

### Data Ingestion

```sql
-- 1. Insert unstructured policies and generate real embeddings natively in AlloyDB
INSERT INTO transit_policies (category, policy_text, policy_embedding)
VALUES
('Pets', 'Service animals are always welcome. Small pets (under 25 lbs) are allowed in secure carriers for a $25 fee. Large dogs are not permitted on standard coaches.', embedding('text-embedding-005', 'Service animals are always welcome. Small pets (under 25 lbs) are allowed in secure carriers for a $25 fee. Large dogs are not permitted on standard coaches.')),
('Luggage', 'Each passenger is allowed one carry-on (up to 15 lbs) and two stowed bags (up to 50 lbs each) free of charge. Additional bags cost $15 each.', embedding('text-embedding-005', 'Each passenger is allowed one carry-on (up to 15 lbs) and two stowed bags (up to 50 lbs each) free of charge. Additional bags cost $15 each.')),
('Refunds', 'Tickets are fully refundable up to 24 hours before departure. Within 24 hours, tickets can be exchanged for travel credit only.', embedding('text-embedding-005', 'Tickets are fully refundable up to 24 hours before departure. Within 24 hours, tickets can be exchanged for travel credit only.'));

-- 2. Generate 200+ realistic schedules for the next days using generate_series
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

## tools.yaml Configuration

Use the `tools.yaml` file in this repository.

Replace all placeholders (for project, cluster, instance, credentials, and MCP endpoint URL) with your values.
You can also parameterize them via environment variables.

## Install Toolbox

```bash
# See releases page for other versions
export VERSION=0.27.0
curl -L -o toolbox https://storage.googleapis.com/genai-toolbox/v$VERSION/linux/amd64/toolbox
chmod +x toolbox
```

## Deploy Toolbox to Cloud Run

Follow the official documentation, including authentication setup:

https://googleapis.github.io/genai-toolbox/how-to/deploy_toolbox/

## Clone and Run the Python App Locally

```bash
git clone https://github.com/MohanMahesh10/cymbal-transit-python.git
cd cymbal-transit-python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Windows PowerShell:

```powershell
git clone https://github.com/MohanMahesh10/cymbal-transit-python.git
cd cymbal-transit-python
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

App URL: http://localhost:8080

## Deploy the Python Agent App to Cloud Run

```bash
gcloud run deploy cymbal-transit-python --source . --set-env-vars GCP_PROJECT_ID=<YOUR_PROJECT_ID>,GCP_REGION=us-central1,GEMINI_MODEL_NAME=gemini-2.5-flash,MCP_TOOLBOX_URL=<YOUR_MCP_TOOLBOX_URL>,PORT=8080 --allow-unauthenticated
```

Replace the placeholder variables enclosed in `< >`.

## App Endpoints

- `POST /api/agent/chat`
- `POST /chat`
- `POST /api/book`
- `GET /health`

## Notes

- This is the Python adaptation of the Cymbal Transit demo concept.
- The app uses `tools.yaml` for MCP tool configuration and endpoint integration.
- Do not commit real secrets in `tools.yaml`; use placeholders or environment variable expansion.
