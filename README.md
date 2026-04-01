# Cymbal Bus Agentic App for MCP Toolbox Python SDK

## Cymbal Bus Agent (Python Version)

This project is the Python version of the Cymbal Bus Agent demo.

<table align="center">
<tr>
<td>![Before](https://github.com/user-attachments/assets/af53cfbf-1760-4f8a-8927-97f9e2415470)</td>
<td>![After](https://github.com/user-attachments/assets/427cf6a8-7077-4f10-8c72-c9a2bb9608e0)</td>
</tr>
</table>

**Live schedules working** - Portland→Seattle ($32), Chennai→Salem ($19)

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

[https://codelabs.developers.google.com/quick-alloydb-setup](https://codelabs.developers.google.com/quick-alloydb-setup)

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
  origin_city VARCHAR(1
