# Scopes, audit log, approval gates, aur tool search

## 1. Scoped API keys

Default: `BACKEND_API_KEY` ek hi shared secret hai (unrestricted). Team ke liye scopes:

```bash
UAI_KEY_SCOPES='{"kid-readonly":"","kid-video":"video:*","kid-ci":"code:write,jobs:write"}' \
BACKEND_API_KEY=master-secret uvicorn app.main:app
```

- **Reads (GET) kabhi block nahi hote** — warna studio/editor scoped key par toot jate.
- Writes scope maangte hain: `code:write`, `video:write`, `jobs:write`, `data:write`, `git:write`
- `video:*` = area wildcard, `*` / `admin` = sab kuch
- List me na hone wali key **default me unrestricted** rehti hai (`UAI_UNSCOPED_DENY=1` se
  usko bhi band kar sakte hain) — isse purana setup tootta nahi.
- Kaun kya kar sakta hai: `GET /v1/governance/whoami`

## 2. Audit log (append-only)

`$UAI_DATA_ROOT/audit.jsonl` — har write + admin action, ek JSON line:

```json
{"at":"2026-11-05T11:49:02","action":"http.write","actor":"8254c329a928",
 "target":"/v1/video/probe","outcome":"error:400","detail":{}}
```

- `actor` = key ka **SHA-256 fingerprint** (12 chars) — secret kabhi log nahi hota
- Padho: `GET /v1/governance/audit?limit=50&action=http.write`
- Logging fail ho jaye to request **fail nahi hoti** (by design)

## 3. Approval gates

```bash
UAI_REQUIRE_APPROVAL=1 uvicorn app.main:app
```

Dangerous operations: `/v1/code/write`, `/v1/code/apply`, `/v1/data/restore`, `/v1/git/commit`

```bash
# 1) token lo (15 min, single-use)
curl -s -X POST localhost:8000/v1/governance/approvals -H "X-API-Key: $KEY" \
  -H 'content-type: application/json' -d '{"path":"/v1/data/restore","reason":"restore nightly"}'
# → {"token":"...","expires_in":900}

# 2) asli call me header lagao
curl -s -X POST localhost:8000/v1/data/restore -H "X-API-Key: $KEY" \
  -H "X-Approval-Token: <token>" -H 'content-type: application/json' -d '{"name":"…"}'
```

- Token **ek hi baar** chalta hai (reuse → 403)
- Doosre operation ke liye issued token → 403
- 15 min me expire
- Bina token → **428 Precondition Required**

## 4. Tool search (BM25, koi model nahi)

```bash
curl -s "localhost:8000/v1/tools/search?q=text%20to%20speech%20voiceover&limit=5" -H "X-API-Key: $KEY"
curl -s "localhost:8000/v1/tools/routes?q=remove%20silence" -H "X-API-Key: $KEY"
curl -s "localhost:8000/v1/tools/capabilities" -H "X-API-Key: $KEY"
```

BM25 kyun, embeddings kyun nahi: offline chalta hai, koi OpenAI/Gemini key nahi chahiye,
aur **kyun match hua** wo bhi batata hai (`matched`, `coverage`).

Asli results:
- `text to speech voiceover` → `k2-fsa/sherpa-onnx`, `rany2/edge-tts`, `m-bain/whisperX`
- `scrape websites crawler` → `apify/crawlee`, `apify/crawlee-python`
- `remove silence` (routes) → `POST /v1/video/cut-silence`

## Sach

- Tool search **catalog** par chalta hai (205 repos, offline snapshot) — GitHub par live
  search nahi karta; wo `app/github_discovery.py` karta hai (network + rate limit chahiye).
- "Integration: reference-only" ka matlab: code vendored nahi hai, sirf reference hai.
- Approvals **memory** me hain: process restart par pending tokens khatam. Ye security ke
  liye theek hai (short-lived), par multi-container me har container apna token rakhta hai.
