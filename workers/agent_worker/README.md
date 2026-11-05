# Agent planning worker

This worker turns a named agent blueprint plus a user's objective into a validated JSON action plan. It calls a configured OpenAI-compatible model endpoint and rejects plan steps outside a fixed action vocabulary.

It **does not execute the returned steps**. The UI/backend should show the plan and use the existing dedicated endpoints for each reviewed action: voice synthesis, media jobs, YouTube publishing, channel actions and paired Windows actions. Those endpoints apply their own consent, allowlist, credential and approval checks. Arbitrary shell, code execution, caller-supplied URLs, and unbounded tool calls are not part of this worker.

## Configuration

- `AGENT_WORKER_API_KEY`: shared secret to authenticate the Vercel control plane.
- `CELERY_BROKER_URL`: private Redis broker.
- `AGENT_MODEL_BASE_URL`, `AGENT_MODEL_API_KEY`, `AGENT_DEFAULT_MODEL`: planner model endpoint and credentials. If omitted, the worker may use `AI_BASE_URL`, `AI_API_KEY`, and `AI_DEFAULT_MODEL`.
- Only use HTTP on an isolated local test network with `AGENT_ALLOW_INSECURE_HTTP=true`; production requires HTTPS/private networking.

## Universal Agent Runtime polling bridge

The repository-level polling worker at `workers/agent_runtime` consumes tasks created through
`/v1/agent-runtime/tasks` or workflows created through `/v1/agent-runtime/workflows`.
It dispatches to the existing plan-only agent API and waits for its Celery result before
marking a runtime task complete. It does not execute plan steps or side effects.

Set `AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED=true` only after verifying the selected model
provider and its account are genuinely free/no-card. The API control plane has a separate
attestation setting with the same name and must also be configured. A false/default setting
keeps worker claims disabled.

For Docker Compose, `agent-api` is isolated on the private worker network. HTTP to that
one explicitly allowlisted service can be enabled using
`AGENT_RUNTIME_ALLOW_PRIVATE_NETWORK_HTTP=true` and
`AGENT_RUNTIME_PRIVATE_HTTP_HOSTS=agent-api`. Public or remote endpoints must use HTTPS.
