# Universal Agent Runtime

The Universal Agent Runtime adds a persistent task lifecycle around the existing agent worker:
queueing, bounded leases, retries, dependency-aware workflows, approval gates, event history
and scoped text memory. It is API-only and does not create 120 continuously running processes.

## Capabilities

- **Task queue:** submit work, list/filter tasks, inspect task details and event history, cancel queued/running tasks.
- **Worker leases:** workers claim one task at a time, heartbeat leases, and complete or fail tasks.
- **Retries:** failed work returns to the queue while attempts remain; expired leases are recovered on the next claim.
- **Workflow DAGs:** up to 100 steps per workflow, with dependency validation and cycle detection. A step is claimable only after every dependency succeeds.
- **Approvals:** high and critical tasks are held in pending_approval; an operator must approve or reject them through the API before claim.
- **Memory:** simple scoped key/content memory with substring search and metadata. This is not an embeddings/vector database.
- **Audit history:** task creation, claims, heartbeats, approvals, completion, retries and dependency blocking are recorded.

All routes require X-API-Key using the server's BACKEND_API_KEY. This deployment is a single trusted workspace behind one API key. Memory scope is a logical namespace, **not** a per-user security boundary. Do not expose this API directly to untrusted clients or treat a shared API key as end-user authentication.

## Storage and deployment

Set AGENT_RUNTIME_DB_PATH to a writable persistent disk path, for example:

~~~env
AGENT_RUNTIME_DB_PATH=/var/lib/universal-ai-backend/agent_runtime.sqlite3
AGENT_RUNTIME_MAX_PENDING_TASKS=1000
~~~

The default local path is data/agent_runtime.sqlite3. On Vercel, the fallback is /tmp/universal-ai-agent-runtime.sqlite3, which is ephemeral and must not be treated as durable storage. Use a persistent-volume host for the SQLite queue. This SQLite implementation is intended for a single API instance and a shared local persistent disk; do not put a SQLite WAL database on an arbitrary network filesystem or horizontally scale multiple API replicas over it. A PostgreSQL/managed-queue adapter is a future scale-out step.

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

The worker polls one task, forwards it to the configured agent executor, renews its lease while the executor runs, and reports output/failure. The executor itself must enforce the supplied tool_allowlist, respect consent/licensing, and honor the no-paid-fallback policy. The runtime cannot prove that an external executor behaves correctly.

## API examples

Create a basic task:

~~~bash
curl -X POST "$BACKEND_URL/v1/agent-runtime/tasks" \
  -H "X-API-Key: $BACKEND_API_KEY" -H "Content-Type: application/json" \
  -d '{"objective":"Summarize these project notes","agent_id":"research-agent","inputs":{"notes":"..."},"risk_level":"low"}'
~~~

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

Create a workflow with step dependencies:

~~~json
{
  "name": "research then write",
  "steps": [
    {"id":"research","objective":"Research the topic","agent_id":"research-agent"},
    {"id":"write","objective":"Draft the script","agent_id":"script-agent","depends_on":["research"]}
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
