# CloudAura Observe — Unified Monitoring Stack

Centralized observability platform for the CloudAura portfolio. Collects Prometheus metrics from all services, provides Grafana dashboards, host-level metrics via Node Exporter, and LLM trace observability via Langfuse.

## Architecture

```mermaid
graph TD
    P1["P1 — RAG<br/>:8001/metrics"] --> Prom["Prometheus<br/>:9090"]
    P2["P2 — SLM<br/>:8002/metrics"] --> Prom
    P5["P5 — Voice<br/>:8005/metrics"] --> Prom
    P6["P6 — Platform<br/>:8006/metrics"] --> Prom
    NE["Node Exporter<br/>:9100"] --> Prom
    Prom --> Grafana["Grafana<br/>:3000"]
    Grafana --> D1["Portfolio Overview<br/>Dashboard"]
    Grafana --> D2["Host Metrics<br/>Dashboard"]
    P1 -.->|traces| LF["Langfuse<br/>:3001"]
    P2 -.->|traces| LF
    P5 -.->|traces| LF
    LF --> LFDB["PostgreSQL<br/>:5433"]
```

## Quick Start

```bash
cp .env.example .env
# edit .env — set Grafana admin password, Langfuse secrets
docker compose up -d
```

Grafana will be available at port 3000 with datasources and dashboards auto-provisioned. Langfuse will be available at port 3001.

## Services

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `observe-prometheus` | `prom/prometheus:v2.51.2` | 9090 (host network) | Metrics collection, alerting rules, 30-day retention |
| `observe-grafana` | `grafana/grafana:11.4.0` | 3000 | Dashboards and visualization |
| `observe-node-exporter` | `prom/node-exporter:v1.8.1` | 9100 | Host CPU, memory, disk, network metrics |
| `observe-langfuse` | `langfuse/langfuse:2` | 3001 | LLM observability — traces, costs, quality scoring |
| `observe-langfuse-db` | `postgres:16-alpine` | 5433 | Langfuse data store |

## Scrape Targets

Prometheus scrapes the following jobs every 15 seconds:

| Job | Target | Labels |
|-----|--------|--------|
| `prometheus` | `localhost:9090` | — |
| `cloudaura-rag` | `localhost:8001` | project=P1, stack=fastapi |
| `cloudaura-slm` | `localhost:8002` | project=P2, stack=fastapi |
| `cloudaura-voice` | `localhost:8005` | project=P5, stack=fastapi |
| `aura-platform` | `localhost:8006` | project=P6, stack=dotnet |
| `node` | `localhost:9100` | — |

## Alert Rules

Six alert rules across two groups:

### Service Health

| Alert | Condition | Severity |
|-------|-----------|----------|
| **ServiceDown** | `up == 0` for 2m | critical |
| **HighErrorRate** | >5% 5xx responses for 3m | warning |
| **HighLatency** | p95 latency > 5s for 3m | warning |

### Resource Health

| Alert | Condition | Severity |
|-------|-----------|----------|
| **HighCPU** | CPU usage > 85% for 5m | warning |
| **HighMemory** | Memory usage > 90% for 5m | critical |
| **DiskSpaceLow** | Root filesystem > 85% full for 5m | warning |

## Dashboards

Grafana ships with two pre-provisioned dashboards:

- **Portfolio Overview** — service uptime, request rates, error rates, latency across all projects
- **Host Metrics** — CPU, memory, disk, and network usage from Node Exporter

## Tech Stack

- **Metrics:** Prometheus v2.51.2 (host network mode, 30-day TSDB retention)
- **Visualization:** Grafana 11.4.0 (anonymous read access enabled, auto-provisioned datasources and dashboards)
- **Host Metrics:** Node Exporter v1.8.1
- **LLM Observability:** Langfuse 2 (self-hosted, backed by PostgreSQL 16)

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `GF_SECURITY_ADMIN_USER` | Grafana admin username | `admin` |
| `GF_SECURITY_ADMIN_PASSWORD` | Grafana admin password | `changeme` |
| `GF_SERVER_ROOT_URL` | Grafana public URL | `http://localhost:3000` |
| `LANGFUSE_SECRET_KEY` | Langfuse secret API key | — |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public API key | — |
| `LANGFUSE_NEXTAUTH_SECRET` | NextAuth session secret | `changeme-nextauth-secret` |
| `LANGFUSE_NEXTAUTH_URL` | Langfuse public URL | `http://localhost:3001` |
| `LANGFUSE_DATABASE_URL` | PostgreSQL connection string | `postgresql://langfuse:changeme@langfuse-db:5432/langfuse` |
| `LANGFUSE_SALT` | Langfuse encryption salt | `changeme-salt` |
| `POSTGRES_USER` | Langfuse DB username | `langfuse` |
| `POSTGRES_PASSWORD` | Langfuse DB password | `changeme` |
| `POSTGRES_DB` | Langfuse DB name | `langfuse` |

## Monitoring

Prometheus self-monitors at `localhost:9090`. Grafana health at `/api/health`. Langfuse health at `/api/public/health`.
