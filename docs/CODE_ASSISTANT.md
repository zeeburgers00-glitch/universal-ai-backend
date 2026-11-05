# Code Assistant — Cursor-style features, zero API keys

Ye module (`app/code_assistant.py` + `app/code_routes.py`) Cursor jaisi coding
intelligence deta hai, magar **bilkul local**: koi model call nahi, koi key nahi,
koi quota nahi. Isliye ye kabhi "API key missing" se fail nahi hoti.

Verified on this repo: **252 files, 1,203 symbols, index build 246 ms.**

## Built-in editor (browser me, koi install nahi)

`GET /editor` — backend khud ek poora code editor serve karta hai: file tree, editor,
outline, review, tests, plan, diff aur chat panel. **Ek hi HTML response (21 KB), koi CDN,
koi npm, koi build step nahi** — offline/air-gapped bhi chalta hai.

Kholein: `http://<host>:8000/editor?key=<BACKEND_API_KEY>`

| Panel | Kaam |
|---|---|
| File tree | search filter, folder grouping, click = open |
| Editor | line numbers, tab = 4 spaces, Ctrl+S save, dirty marker |
| Outline | symbols par click → line par jump |
| Review | severity ke saath findings, click → jump |
| Tests | pytest skeleton, copy ya save |
| Plan | goal → steps + related files |
| Diff | save ke baad +/− colored diff |
| Chat | local Ollama ya free key ho to kaam karta hai, warna saaf error |

## Endpoints (sab `/v1/code/*`, sab API key chahiye)

| Endpoint | Kya karta hai | Cursor equivalent |
|---|---|---|
| `POST /index` | repo walk + AST symbol extraction, disk par index | Codebase indexing |
| `GET /tree` | editor ka file tree | file explorer |
| `GET /read` | file content | open file |
| `POST /write` | editor buffer save (default dry-run, `.bak`) | save file |
| `GET /search?q=` | symbol + filename + text search, ranked, snippets ke saath | `@codebase` search |
| `POST /outline` | file ke classes/functions/imports line numbers ke saath | file structure view |
| `POST /diff` | find/replace ka unified diff — **kuch likhta nahi** | inline edit preview |
| `POST /apply` | edit apply (default `dry_run:true`, `.bak` backup) | apply edit / Composer |
| `POST /review` | secrets, bare-except, eval, shell=True, lambi functions, missing docstring | Bug finder |
| `POST /tests` | module ke public functions ka pytest skeleton | generate tests |
| `GET /commit-message` | git diff se conventional commit draft | commit message AI |
| `GET /rules` | `.cursorrules`, `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md` padhta hai | Rules |
| `POST /plan` | goal → 6 reviewable steps + related files | Composer plan |

## Examples

```bash
KEY="X-API-Key: $BACKEND_API_KEY"

curl -s -X POST localhost:8000/v1/code/index -H "$KEY" -H 'content-type: application/json' -d '{}'

curl -s "localhost:8000/v1/code/search?q=quota&limit=5" -H "$KEY"

curl -s -X POST localhost:8000/v1/code/diff -H "$KEY" -H 'content-type: application/json' \
  -d '{"path":"app/quota.py","find":"DEFAULT_CAPS","replace":"DAILY_CAPS"}'

curl -s -X POST localhost:8000/v1/code/apply -H "$KEY" -H 'content-type: application/json' \
  -d '{"path":"app/quota.py","find":"DEFAULT_CAPS","replace":"DAILY_CAPS","dry_run":false}'
```

## Safety

- Har path `REPO_ROOT` ke andar resolve hota hai; `../` ya absolute path → **400**
- `apply` default me **dry run** hai; likhte waqt `.bak` backup banta hai
- Binary aur 512 KB se bade files edit nahi hote
- `review` aur `plan` read-only hain

## Jo Cursor karta hai par ye NAHI karta

| Cursor feature | Yahan status |
|---|---|
| Autonomous multi-file refactor | ❌ needs a model (Ollama local se possible, tab `plan` steps execute kar sakte hain) |
| Tab autocomplete (ghost text) | ❌ editor ka kaam hai, server se nahi hota |
| Semantic embeddings index | ⚠️ abhi keyword+symbol ranking (free); embeddings chahiye to local model se add ho sakta hai |
| Inline AI answers about code | ⚠️ model chahiye — local Ollama configure karo to free hai |

Baat simple hai: **jo cheez bina model ke ho sakti thi, wo sab add hai.** Jo model maangti hai,
wo `/v1/ai/free/status` me Ollama configure karne ke baad free + unlimited chalti hai.
