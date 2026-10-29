# Workflow dispatcher

The workflow dispatcher consumes a workflow blueprint supplied by the main API. Without `inputs.actions`, it returns the blueprint as a plan. With `inputs.actions`, it dispatches only fixed action names through server-configured downstream worker URLs—never a caller-supplied URL, shell command, or arbitrary function.

Allowed action types:
- `voice_tts` → `VOICE_WORKER_URL/v1/voice/tts`
- `voice_clone` → `VOICE_WORKER_URL/v1/voice/clone` (speaker consent record required)
- `media_job` → `MEDIA_WORKER_URL/v1/media/jobs`
- `youtube_publish` → `YOUTUBE_WORKER_URL/v1/youtube/publish` (approval required)
- `channel_action` → `CHANNEL_WORKER_URL/v1/channels/action` (approval required)
- `desktop_action` → `DESKTOP_AGENT_URL/v1/desktop/actions` (approval required)

The dispatcher returns downstream subtask identifiers/statuses; it does not wait until every GPU/video task completes. Poll each subtask using the corresponding service on `GET /v1/tasks/{service}/{task_id}`. A blocked or missing worker is reported explicitly.

Use explicit `user_approved=true` only after showing the exact proposed actions to the user. This service uses a shared backend secret; a production multi-user app must also bind actions and approval records to authenticated user/tenant identities.


## REA action

The `rea_call` action dispatches to the paired Windows agent's `POST /v1/rea/jobs` route. Payload must include `paired_device_id`, `tool_name`, `arguments`, `authorization_scope_confirmed=true`, and `authorization_scope_note`. It must also set `user_approved=true`. The local agent independently checks its `REA_ALLOWED_TOOL_NAMES`, `REA_ALLOWED_TARGET_ROOTS`, and `REA_ALLOWED_URL_HOSTS` configuration. The response carries a local task ID; poll it using the main API's `/v1/tasks/rea/{task_id}`. Never treat a queued REA call as a completed analysis.
