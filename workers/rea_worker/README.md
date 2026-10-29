# REA Inspection Worker (`workers/rea_worker`)

Isolated FastAPI + Celery worker that executes allowlisted static [REA (`morluto/rea`)](https://github.com/morluto/rea) CLI inspections on artifacts staged inside `REA_ALLOWED_WORKSPACE_ROOT`.

## Security & Responsible-Use Boundaries

- **Authorized targets only:** Requests must set `authorized_target_confirmed=true` and `user_approved=true`. Follow REA's upstream `DISCLAIMER.md` — never analyze targets without legal authorization.
- **No arbitrary shell commands:** Only static, allowlisted REA operations (`capabilities`, `doctor`, `inspect-desktop-application`, `analyze-javascript-application`, `inspect-model-artifact`, `inspect-gpu-code-objects`, `inspect-python-pyc`, `inspect-sqlite-database`, `inspect-pe-imports`, `inspect-pe-certificates`, `inspect-elf-notes`, `inspect-go-binary`, `inspect-rust-binary`, `inspect-wasm-artifact`) are accepted, invoked via `subprocess.run(..., shell=False)`.
- **Path confinement:** `target_path` must resolve inside `REA_ALLOWED_WORKSPACE_ROOT` (`/workspace/targets` by default, mounted read-only in `workers/docker-compose.yml`).
