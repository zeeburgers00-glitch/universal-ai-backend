# Skills — 2,845 cheezein, par sirf sach bola jayega

Ye document batata hai ki skill catalogue me kya hai, kaunsi cheez **abhi chalegi** aur kaunsi
**pehle install maangti hai**. Har skill ka ek id hota hai jo sentence ki tarah padha jaata hai.

```
media.video.convert.mp4-to-webm-vp9
data.table.op.dedupe.csv
code.python.todos
```

## Numbers (is machine par, aaj)

| Layer | Count | Chalega? |
|---|---|---|
| **Native** (humne likhi, real runner ke saath) | **1,082** | 937 abhi is machine par ready |
| **External** (MCP ecosystem catalogue import) | **1,763** | ❌ install karna padega — `available: false` |
| **Total registered** | **2,845** | — |

Native 1,082 me se baaki 145 ka reason bhi honest hai: jo cheez machine par nahi hai
(pandoc, libreoffice, pymupdf, docx libs) wo `unavailable: <exact install command>` bolti hai.

`GET /v1/skills/stats` hamesha yahi split dikhata hai — `available_now`, `native`, `external`.
Koi skill "installed" nahi dikhti jab tak uska asli runner kaam na kare.

## Categories

| Category | Skills | Examples |
|---|---|---|
| `media` | 712 | video convert (6 source × containers × codecs), 7 resize presets, 9 platform exports, 17 video ops, gif, probe, audio convert/ops (mp4/mov/mkv se bhi audio nikalta hai), image convert/resize/12 ops |
| `tools` | 130 | har tool-belt tool ke 2 skills (run + verify) — ffmpeg, ripgrep, sqlite3, git… |
| `data` | 80 | csv/tsv/json/jsonl × 11 table ops, 4×4 format converts, 5 SQL analyses (asli in-memory SQLite) |
| `code` | 65 | 13 languages × 5 inspections: symbols, todos, secret-scan, imports, complexity-hint |
| `text` | 38 | 19 text ops × inline/file — word frequency, email/URL/hashtag extract, slugify, dedupe lines, hash |
| `ai` | 26 | provider chat × 11 providers (+ fallback), 4 recipes |
| `docs` | 13 | md→pdf, pdf→txt, xlsx→csv etc. — tool ke bina 503 |
| `system` | 12 | health, queue, providers, governance tail, disk, jobs |
| `recipe` | 6 | multi-step agents: shorts pack, podcast pack, repo brief, release check… |

## HTTP

```bash
# kitni skills hain + honest split
curl localhost:8000/v1/skills/stats -H "X-API-Key: YOUR_KEY"

# category-wise
curl "localhost:8000/v1/skills/categories" -H "X-API-Key: YOUR_KEY"

# search (BM25, Hinglish/English dono)
curl "localhost:8000/v1/skills/search?q=convert%20video%20to%20webm" -H "X-API-Key: YOUR_KEY"

# ek skill ki poori detail (inputs, needs, example)
curl "localhost:8000/v1/skills/media.video.convert.mp4-to-webm-vp9" -H "X-API-Key: YOUR_KEY"

# chalao
curl -X POST "localhost:8000/v1/skills/text.stats.inline/run" \
  -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"args": {"text": "hello world. This is a test!"}}'
```

Listing: `GET /v1/skills?category=media&available=true&limit=50&offset=0`
(`source=native|external`, `level=basic|intermediate|advanced` bhi chalte hain).
`POST /v1/skills/refresh` external catalogue dobara padhta hai.

Status codes: `200` chala, `422` argument galat, `503` dependency missing (message me install
command), `404` aisa id nahi + "Did you mean…".

## JARVIS se

```
skill text.stats.inline text="hello world"
skill media.video.convert.mp4-to-webm-vp9 path=clip.mp4
```

`kitne tools hain` poochho to JARVIS skill count bhi batata hai.

## External layer (1,763 MCP servers — jo abhi installed NAHI hain)

`catalog/mcp_ecosystem.json` me 1,763 MCP server entries hain (naam, description, capabilities,
risk level, repo URL). Inhe humne **catalogue** ki tarah import kiya hai, taaki search me mile:

```
GET /v1/skills/search?q=slack        →  external entries, available: false
GET /v1/skills/mcp.<id>              →  "external_reason": "catalogue entry from mcp_ecosystem.json — install the MCP server to use it"
POST /v1/skills/mcp.<id>/run         →  503 "unavailable: external MCP server …"
```

Ye jaan-boojh kar aisa hai: 1,763 servers install karna ek alag, bhaari kaam hai (node/python,
keys, config). Jab tak install nahi, ye skills **sirf discovery** hain — isliye totals me inhe
`external` alag column me rakha gaya hai, native me milaya nahi gaya.

## Kya sach me chalta hai (test proof)

`tests/test_skills.py` — 30 tests, sab asli:

- `ffmpeg` se 1 second ka sample video (audio ke saath) bana kar **mp4 → mkv h264**, **mp4 → webm vp9**
  aur **480p resize** — output files exist karti hain, size > 1 KB. webm me audio `libopus` se jaata hai
  (aac webm accept nahi karta — pehle wahi bug tha, ab test pakadta hai).
- `ffprobe` probe: width 160, height 90 — numbers asli file se.
- CSV string par `data.table.op.dedupe.csv` → 3 rows in, 2 rows out, output file me "Ali" ek baar.
- `csv-to-json` → file me sahi array; SQL count → 1 row; `csv-to-sqlite` → asli SQLite file
  (header bytes `SQLite format 3`, `select count(*)` = 2).
- `code.python.symbols` asli file `app/skills.py` par → `Skill`, `run`, `search` mile.
- secret-scan aur todos ek temp file par → 1-1 hit.
- `text.stats.inline` → 6 words, 2 sentences (galat number nahi).
- Refusals: external skill → `unavailable:` 503, pandoc na ho to pandoc ka naam, GROQ key na ho
  to `GROQ_API_KEY` ka naam, argument missing → 422.

## Naya skill add karna

1. `app/skill_runners.py` me runner likho (`def run_xyz(args) -> dict`), `RUNNERS["xyz"] = run_xyz`.
2. `app/skills.py` ke generator me `Skill(...)` add karo (`engine="xyz"`).
3. `tests/test_skills.py` me ek asli file par test.
4. `GET /v1/skills/stats` — count khud badh jayega.
