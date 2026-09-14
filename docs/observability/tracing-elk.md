# Tracing with ELK (local dev)

The Telegram bot and the usage dashboard can export OpenTelemetry traces
(`shared/obs/tracing.py`) to a local Elastic APM Server. Tracing is **off by default**
(`OTEL_ENABLED=false`) and everything works without it.

Current state, stated plainly: the exporter, sampler and resource metadata are wired,
but no module creates spans of its own yet (there is no `get_tracer(...)` call in the
code). Turning tracing on today registers the services in APM without producing
traces. The stack below is scaffolding for the instrumentation that adds them.

Flow:

`telegram-bot / usage-dashboard (shared.obs.tracing) -> APM Server -> Elasticsearch -> Kibana`

## 1) Start the observability stack

```bash
cp tools/observability/.env.example tools/observability/.env
# set KIBANA_ENCRYPTION_KEY in that file (openssl rand -hex 16), then:
docker compose -f tools/observability/docker-compose.elastic.yml --env-file tools/observability/.env up -d
```

Check health:

```bash
curl -fsS http://localhost:9200/_cluster/health
curl -fsS http://localhost:5601/api/status
curl -fsS http://localhost:8200/
```

## 2) Set app env

Add to `.env`:

```bash
OTEL_ENABLED=true
OTEL_SERVICE_NAMESPACE=ai_agents
OTEL_DEPLOYMENT_ENVIRONMENT=local
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8200
OTEL_TRACES_SAMPLER=always_on
```

## 3) Run a service

```bash
uv run usage-dashboard --port 8081   # or: uv run telegram-bot
```

## 4) View in Kibana

Open [http://localhost:5601](http://localhost:5601), then APM / Services.

## Notes

- PII policy for future spans: attributes carry only safe metadata (ids, status, counts),
  never document text or user messages.
- The droplet deployment forces `OTEL_ENABLED=false` (`infrastructure/docker/docker-compose.yml`).
