# Universal Agent Runtime worker

This container polls the protected Universal Agent Runtime API, claims one task at a time, renews leases while the downstream planner works, and submits final output or failure. It is profile-gated in the shared Compose stack so it does not start accidentally.

## Run

~~~bash
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml --profile agent-runtime up --build -d agent-api agent-runner agent-runtime-worker
~~~

Configure the variables from `workers/.env.workers.example`. The API server and worker must both have `AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED=true`, but only after the chosen model provider and account have been checked as free/no-card. The default is false and worker claims are denied until attested.

The reference executor is the existing `workers/agent_worker` planner. It returns plans only; this container does not execute shell commands, publishing, messages or media steps. Every side effect must be reviewed and routed to a dedicated API with its own permissions and consent checks.

For the Compose-internal `agent-api` service only, private HTTP is allowed only with `AGENT_RUNTIME_ALLOW_PRIVATE_NETWORK_HTTP=true` and `AGENT_RUNTIME_PRIVATE_HTTP_HOSTS=agent-api`. All remote services must use HTTPS.
