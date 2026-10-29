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

Treat screenshots, clipboard contents, local files, and webpages as potentially sensitive. Obtain user consent before recording/sharing them. For safer production operation, bind approval records to the exact action payload, use a durable audit log, and implement session expiry/replay protection.
