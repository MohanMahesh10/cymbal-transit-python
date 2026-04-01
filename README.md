# Cymbal Transit Python

Production-ready Python implementation of the Cymbal Transit multi-agent bus assistant.

The app combines Flask, LangChain LCEL routing, and MCP Toolbox tools backed by AlloyDB to support:

- Route and schedule discovery
- Policy lookup
- Ticket booking
- Seat availability checks
- Ticket confirmation rendering in the web chat UI

## Highlights

- Multi-agent orchestration with deterministic intent routing
- MCP tool execution over JSON-RPC
- Structured tool contracts in tools.yaml
- Booking confirmation flow with ticket metadata extraction
- Lightweight web UI for conversational interactions

## Tech Stack

- Python 3.10+
- Flask
- LangChain Core
- MCP Toolbox Python SDK (toolbox-core)
- AlloyDB (PostgreSQL + vector extension)

## Repository Layout

- app.py: Flask server, intent routing, MCP integration
- templates/index.html: chat UI and ticket card rendering
- static/css/style.css: styling assets
- tools.yaml: MCP source and tool definitions
- requirements.txt: Python dependencies

## Quick Start

### 1) Clone and install

```bash
git clone https://github.com/MohanMahesh10/cymbal-transit-python.git
cd cymbal-transit-python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2) Configure tools.yaml

Update these sections in tools.yaml:

- app.mcp_toolbox_url
- sources.alloydb
- authServices.google_auth (if auth is required)

Important:

- Do not commit real database passwords, client IDs, or private endpoints.
- Use environment variable interpolation where possible.

### 3) Run the app

```bash
python app.py
```

Open:

- http://localhost:8080

Health endpoint:

- http://localhost:8080/health

## MCP Tools

The default tool catalog includes:

- find-bus-schedules
- query-schedules
- book-ticket
- book-ticket-ui
- search-policies

All tools are declared in tools.yaml and invoked from app.py through the toolbox endpoint.

## AlloyDB Schema

Core tables expected by this app:

- transit_policies
- bus_schedules
- bookings

If you are bootstrapping from scratch, use the schema and seed pattern from the official Cymbal Transit codelab.

## API Surface

- POST /api/agent/chat
- POST /chat
- POST /api/book
- GET /health

## Deployment

This app is Cloud Run friendly.

```bash
gcloud run deploy cymbal-transit-python \
  --source . \
  --set-env-vars PORT=8080 \
  --allow-unauthenticated
```

## Security and Git Hygiene

- .gitignore excludes env and bytecode artifacts.
- Keep tools.yaml sanitized before pushing.
- Prefer placeholders or env variables for all credentials.

## Contributing

1. Create a feature branch.
2. Keep commits scoped and descriptive.
3. Validate app startup and critical chat flows.
4. Open a pull request with test notes and screenshots for UI changes.

## Acknowledgements

- Reference concept: https://github.com/AbiramiSukumaran/cymbal-transit
- Codelab: https://codelabs.developers.google.com/cymbal-bus-agent-mcp-toolbox-java#0
