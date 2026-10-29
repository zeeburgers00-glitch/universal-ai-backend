# Windows JARVIS desktop agent

This is the trusted local executor for the JARVIS workflow. It runs on the user's Windows PC, not inside Vercel. The agent supports a narrow allowlist: status, approved app launch, explicitly approved HTTPS navigation to allowlisted hosts, screenshot, approved typing/clicks, and text file read/write/delete within a single configured workspace. It does not accept arbitrary shell commands from the cloud.

## Setup (PowerShell)

\`\`\`powershell
cd workers\\windows_agent
py -3.12 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
$env:DESKTOP_AGENT_API_KEY = "GENERATE-A-LONG-RANDOM-SECRET"
$env:WINDOWS_AGENT_DEVICE_ID = "my-windows-pc-01"
$env:WINDOWS_AGENT_WORKSPACE = "$HOME\\UniversalAIAgentWorkspace"
$env:WINDOWS_AGENT_ALLOWED_URL_HOSTS = "www.youtube.com,github.com,docs.python.org"
uvicorn app:app --host 127.0.0.1 --port 8410
\`\`\`

`uvicorn` defaults to loopback only. To connect Vercel, publish it through a secure HTTPS tunnel or private network, then set Vercel `DESKTOP_AGENT_URL` and `DESKTOP_AGENT_API_KEY`. Use a strong unique shared secret, restrict tunnel access, and pair the device ID. Do not expose port 8410 directly to the public internet.

## Local security controls

- File access is limited to `WINDOWS_AGENT_WORKSPACE`.
- Application names must be in the local `WINDOWS_AGENT_APPS_JSON` allowlist.
- URL hosts must be allowlisted in `WINDOWS_AGENT_ALLOWED_URL_HOSTS`.
- Typing, clicking, writing/deleting files, and shutdown require `user_approved=true`.
- Shutdown is additionally disabled unless `WINDOWS_AGENT_ALLOW_SHUTDOWN=true`.
- Raw shell execution and software installation are disabled by default.
- The agent should run as a standard user, not Administrator, unless a reviewed use case specifically requires elevation.

## Optional REA (Reverse Engineer Anything) MCP integration

REA is a separate MIT-licensed CLI/MCP server specializing in evidence-backed reverse engineering; it is not a TTS or general-purpose LLM. The bridge in `rea_mcp.py` launches the locally installed REA CLI over its default **stdio** transport and keeps one local MCP session alive so multi-step investigations retain state. The cloud API does not run REA binaries or host the REA HTTP listener.

Install supported Node.js/npm first. The upstream repository currently declares Node.js `^22.23.4 || ^24.22.1 || >=26.12.1`.

```powershell
node --version
npm install --global rea-agents@6.8.0
$env:REA_NODE_EXECUTABLE = (Get-Command node).Source
$globalNodeModules = (npm root -g).Trim()
$env:REA_ENTRY_SCRIPT = Join-Path $globalNodeModules "rea-agents\scripts\rea.mjs"
$env:REA_MCP_ENABLED = "true"
$env:REA_MCP_CALL_TIMEOUT_SECONDS = "180"
# Set these to folders/hosts that you own or are explicitly authorized to inspect.
$env:REA_ALLOWED_TARGET_ROOTS = "$HOME\UniversalAIAgentWorkspace;$HOME\AuthorizedApps"
$env:REA_ALLOWED_URL_HOSTS = "github.com,rea.tools"
# Initially leave empty. Read /v1/rea/tools, review exact tool names, then enable only selected names.
$env:REA_ALLOWED_TOOL_NAMES = ""
uvicorn app:app --host 127.0.0.1 --port 8410
```

After restarting the Windows agent, the existing Vercel backend can call:
- `GET /v1/rea/tools` to list the locally installed tool names and schemas;
- `POST /v1/rea/jobs` to queue one approved, locally allowlisted tool call;
- `GET /v1/tasks/rea/{task_id}` on the Vercel API to poll the asynchronous result.

Every call needs `user_approved=true`, an authorization-scope confirmation and a brief scope note. File/artifact arguments must stay under `REA_ALLOWED_TARGET_ROOTS`; URL arguments must use a hostname in `REA_ALLOWED_URL_HOSTS`. The exact tool names must appear in `REA_ALLOWED_TOOL_NAMES` (comma-separated), and the bridge is disabled unless `REA_MCP_ENABLED=true`. Do not allowlist installation, destructive, network-capture or runtime-mutation tools until you have reviewed their individual behavior.

The upstream REA HTTP transport is documented as plain HTTP without client authentication or TLS. This integration deliberately avoids that mode and launches REA via local stdio. REA's security policy also states that runtime analysis is **not a sandbox**; analyze only targets you own or are authorized to inspect and use an isolated test environment for untrusted binaries. See https://github.com/morluto/rea/blob/main/SECURITY.md and https://github.com/morluto/rea/blob/main/docs/mcp-contracts.md.

Treat screenshots, clipboard contents, local files, and webpages as potentially sensitive. Obtain user consent before recording/sharing them. For safer production operation, bind approval records to the exact action payload, use a durable audit log, and implement session expiry/replay protection.
