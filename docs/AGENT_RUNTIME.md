# Universal Agent Runtime

The Universal Agent Runtime adds a persistent task lifecycle around the existing agent worker:
queueing, bounded leases, retries, dependency-aware workflows, approval gates, event history
and scoped text memory. It is API-only and does not create 120 continuously running processes.

## Capabilities

- **Task queue:** submit work, list/filter tasks, inspect task details and event history, cancel queued or approval-pending tasks. Running work cannot be hard-cancelled by the API; stop it through the executor first.
- **Worker leases:** workers claim one task at a time, heartbeat leases, and complete or fail tasks. Global parallelism defaults to 5 (hard-capped at 20); per-agent concurrency defaults to 1.
- **Retries:** failed work returns to the queue while attempts remain; expired leases are recovered on the next claim.
- **Workflow DAGs:** up to 100 steps per workflow, with dependency validation and cycle detection. A step is claimable only after every dependency succeeds. Its inputs can use explicit `$from_step` references to consume structured outputs from direct prerequisites.
- **Approvals:** high and critical tasks are held in pending_approval; an operator must approve or reject them through the API before claim.
- **Memory:** simple scoped key/content memory with substring search and metadata. This is not an embeddings/vector database.
- **Audit history:** task creation, claims, heartbeats, approvals, completion, retries and dependency blocking are recorded.
- **Unified agent catalog:** searchable, paginated directory merges the 42 general agents, 120 OpenAvatar roles and 120 YouTube roles (282 unique IDs in the current checked-in catalogs). Catalog IDs also supply minimum risk classifications; callers cannot downgrade a critical role to low risk.
- **Worker registry:** workers register capabilities and are tracked as idle/busy/offline based on last-seen heartbeats; the same worker cannot claim a second active task.

All routes require X-API-Key using the server's BACKEND_API_KEY. This deployment is a single trusted workspace behind one API key. Memory scope is a logical namespace, **not** a per-user security boundary. Do not expose this API directly to untrusted clients or treat a shared API key as end-user authentication.

## Storage and deployment

Set AGENT_RUNTIME_DB_PATH to a writable persistent disk path, for example:

~~~env
AGENT_RUNTIME_DB_PATH=/var/lib/universal-ai-backend/agent_runtime.sqlite3
AGENT_RUNTIME_MAX_PENDING_TASKS=1000
~~~

If `AGENT_RUNTIME_DB_PATH` is blank, the default local path is data/agent_runtime.sqlite3. On Vercel, the fallback is /tmp/universal-ai-agent-runtime.sqlite3, which is ephemeral and must not be treated as durable storage. Use a persistent-volume host for the SQLite queue. This SQLite implementation is intended for a single API instance and a shared local persistent disk; do not put a SQLite WAL database on an arbitrary network filesystem or horizontally scale multiple API replicas over it. A PostgreSQL/managed-queue adapter is a future scale-out step.

## No-card execution gate

The queue API can accept tasks while execution is disabled. Worker claims return 503 unless the API server has:

~~~env
AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED=true
~~~

Only set this after checking the worker's actual provider configuration. The reference worker also refuses to start unless its own AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED=true is set. No payment credentials are accepted, no GPU is provisioned, and the dispatch envelope explicitly forbids paid-provider fallback. This attestation is an operator assertion, not an automatic audit of a third-party worker.

Configure the existing generic agent executor on the worker host:

~~~env
AGENT_RUNTIME_API_URL=https://your-backend.example
BACKEND_API_KEY=...
AGENT_WORKER_URL=https://your-agent-worker.example
AGENT_WORKER_API_KEY=...
AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED=true
AGENT_RUNTIME_WORKER_ID=agent-worker-01
AGENT_RUNTIME_POLL_SECONDS=5
AGENT_RUNTIME_LEASE_SECONDS=300
AGENT_RUNTIME_EXECUTOR_PATH=/v1/agents/run
~~~

Keep all keys in server/worker secret storage. Never put them in task inputs, memory metadata, or prompts. The API rejects common credential-shaped payload keys. The worker URL must use HTTPS; loopback HTTP is permitted only with the explicit local-development switch.

Start the reference worker from the repository root:

~~~bash
python -m workers.agent_runtime.worker
~~~

The worker polls one task, forwards it to the configured generic agent executor, renews its lease while that executor runs, and reports output/failure. The bundled `workers/agent_worker` returns HTTP 202 and a Celery task ID; the reference worker then polls the status route until it receives the final result. Defaults are `AGENT_RUNTIME_EXECUTOR_STATUS_PATH_TEMPLATE=/v1/tasks/{task_id}`, `AGENT_RUNTIME_EXECUTOR_MAX_WAIT_SECONDS=3600`, and `AGENT_RUNTIME_EXECUTOR_POLL_SECONDS=5`. Use the placeholder exactly once in the status-path template. The executor itself must enforce the supplied tool_allowlist, respect consent/licensing, and honor the no-paid-fallback policy. The runtime cannot prove that an external executor behaves correctly.

**Important execution boundary:** the bundled `workers/agent_worker` is a *plan-only* worker. It produces a structured action plan and does not execute the plan's actions (it does not upload videos, send messages, invoke shell commands, or create media). A runtime task marked `succeeded` means the executor returned its completed output/plan—not that every proposed side effect was performed. Reviewed actions must be routed to the existing dedicated backend/worker endpoints, which apply their own credentials, permissions, consent and approval rules. The current reference polling worker is for this plan-only executor contract; an executor that really performs tasks must be separately audited and must return a trustworthy final status/result.

## API examples

Create a basic task:

~~~bash
curl -X POST "$BACKEND_URL/v1/agent-runtime/tasks" \
  -H "X-API-Key: $BACKEND_API_KEY" -H "Content-Type: application/json" \
  -d '{"objective":"Summarize these project notes","agent_id":"research-agent","inputs":{"notes":"..."},"risk_level":"low"}'
~~~

Explore agents:

- `GET /v1/agent-runtime/catalog?limit=100`
- `GET /v1/agent-runtime/catalog?source=youtube&risk_level=critical`
- `GET /v1/agent-runtime/catalog/{agent_id}`

Inspect tasks:

- GET /v1/agent-runtime/status
- GET /v1/agent-runtime/tasks?status=queued&limit=50
- GET /v1/agent-runtime/tasks/{task_id}
- GET /v1/agent-runtime/tasks/{task_id}/events
- POST /v1/agent-runtime/tasks/{task_id}/cancel

Worker protocol:

- POST /v1/agent-runtime/workers/claim with {"worker_id":"agent-worker-01"}
- POST /v1/agent-runtime/workers/{worker_id}/tasks/{task_id}/heartbeat
- POST /v1/agent-runtime/workers/{worker_id}/tasks/{task_id}/complete
- POST /v1/agent-runtime/workers/{worker_id}/tasks/{task_id}/fail

Create a workflow with step dependencies and hand results from one agent to the next. The `$from_step` reference can only name a direct dependency; its dotted path is read from that step's stored result JSON:



~~~json
{
  "name": "research then write",
  "steps": [
    {"id":"research","objective":"Research the topic","agent_id":"research-agent"},
    {"id":"write","objective":"Draft the script","agent_id":"script-agent","depends_on":["research"],"inputs":{"research_summary":{"$from_step":"research","path":"output.summary"}}}
  ]
}
~~~

Submit it to POST /v1/agent-runtime/workflows; inspect it at
GET /v1/agent-runtime/workflows/{workflow_id}. Cycles, duplicate step IDs and unknown
step dependencies are rejected. A failed dependency blocks downstream tasks.

Approvals and memory:

- GET /v1/agent-runtime/approvals?status=pending
- POST /v1/agent-runtime/approvals/{approval_id}/decision with {"decision":"approved","note":"Reviewed"}
- POST /v1/agent-runtime/memory with {"scope":"project-x","key":"brand-voice","content":"Clear, warm and concise"}
- GET /v1/agent-runtime/memory?scope=project-x&query=warm
- DELETE /v1/agent-runtime/memory/{memory_id}

Task result JSON is capped at 256 KiB. Store large media/artifacts using the existing artifact/storage services and return their IDs/URIs in the task result.


## Docker Compose worker service

The polling worker has its own lightweight container and is guarded by the opt-in Compose
profile. To start the agent planner and its polling bridge after configuring
`workers/.env.workers`, use:

~~~bash
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml --profile agent-runtime up --build -d agent-api agent-runtime-worker
~~~

For the isolated Compose network, the example uses `AGENT_WORKER_URL=http://agent-api:8500`.
That private-network HTTP exception requires both
`AGENT_RUNTIME_ALLOW_PRIVATE_NETWORK_HTTP=true` and
`AGENT_RUNTIME_PRIVATE_HTTP_HOSTS=agent-api`; keep the host allowlist narrow. Public API
URLs still require HTTPS. The worker container exits unless
`AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED=true` is explicitly set.


## Worker draining, operator retry and Prometheus metrics

Use worker draining during rolling deployments or maintenance. A drained worker will
not receive new tasks, but its current lease can heartbeat and finish normally:

~~~bash
curl -X POST "$BACKEND_URL/v1/agent-runtime/workers/agent-worker-01/drain" \
  -H "X-API-Key: $BACKEND_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Rolling deployment"}'
~~~

Re-enable task claims after maintenance:

~~~bash
curl -X POST "$BACKEND_URL/v1/agent-runtime/workers/agent-worker-01/undrain" \
  -H "X-API-Key: $BACKEND_API_KEY"
~~~

A terminally failed standalone task can be manually retried by an authenticated operator:

~~~bash
curl -X POST "$BACKEND_URL/v1/agent-runtime/tasks/TASK_ID/retry" \
  -H "X-API-Key: $BACKEND_API_KEY"
~~~

Manual retry resets the attempt counter and clears the prior result/error. High and critical
tasks return to pending_approval; the previous approval is reopened and must be decided
again. Failed workflow steps are intentionally not replayed individually: submit a new
workflow so its dependency graph and handoffs are rebuilt consistently.

The GET /v1/agent-runtime/metrics endpoint returns Prometheus text exposition with task,
worker, approval, queue-age, memory and no-card-attestation gauges. The endpoint uses the
same X-API-Key protection as the other runtime endpoints. Configure your scraper with
this header; do not expose metrics publicly without an authenticated reverse proxy.
