# Prompt 2 — "saare free tools" wala

Ye prompt **`prompts/free_toolbelt.json`** ke saath use hota hai (65 free tools ki ready list).
Us AI ko ye file bhi do — warna wo 5-6 tools par ruk jayega aur baqi "baad me add karenge"
likh dega.

**Kaise do:** pehle `free_toolbelt.json` attach/paste karo, phir neeche ka prompt. Dono ek hi
message me.

---

=== PROMPT START ===

You are the senior engineer on this repository. Your job in this task is **one thing, done
properly: give this assistant every free tool in the attached `free_toolbelt.json`, each one
actually working.** Answer me in Hinglish at the end of each turn; code and commits in English.

## 0. The two rules that decide success

1. **A tool counts only when its `test` command printed success and one real run happened.**
   Not "it should work". Not "imported successfully". A wrapper that has never processed a
   real file is not a tool.
2. **Never fake a capability.** If a binary is missing, the tool must report
   `unavailable: <what to install>` at call time — it must not return invented data, and it
   must not be listed as available in the tool list.

If you cannot install something, say so and continue with the rest. Partial and honest
beats complete and fake.

## 1. Baseline first (do this before writing any code)

```bash
pytest -q 2>&1 | tail -1                  # note the count
python -c "from app.main import app; print(len(app.openapi()['paths']))"   # note it
python -c "import shutil; print({b: bool(shutil.which(b)) for b in ['ffmpeg','pandoc','soffice','rg','git']})"
```

Report those three lines back to me. Every later claim is measured against them.

## 2. Tool registry (build this first, not last)

Create `app/toolbelt.py` with one dataclass and one decorator — the same idea as a job queue,
but for capabilities:

```python
@dataclass
class Tool:
    id: str                  # "media.probe", "docs.md_to_pdf", "data.duckdb_query"
    name: str
    category: str            # media | docs | code | data | ai | web | ops | comms | security
    description: str         # one sentence, used by BM25 selection
    inputs: dict[str, str]   # field -> description
    required: list[str]
    needs: list[str]         # binaries/services this depends on
    offline: bool
    cost: str                # must literally be "free"
    handler: Callable[[dict], dict]
```

Requirements for the registry itself:

- `registry()` returns every tool with a **runtime availability check** (`shutil.which`,
  import probe) — the list must never advertise a tool whose binary is missing.
- `run(tool_id, payload)` validates required inputs, times the call, writes an audit entry,
  and returns `{"ok": bool, "result"| "error", "elapsed_ms"}`.
- `search(query)` picks tools by **BM25 over id + name + description + category** (write the
  40 lines yourself, no library).
- One `tools/<category>.py` file per category. No file over 300 lines. No giant `if/elif`
  dispatch — the decorator registers.

## 3. Wire the tools — five waves, in this order

Work wave by wave. After each wave: run its tests, run the full suite, commit, report numbers.
**Do not start wave N+1 before wave N's tests pass.**

### Wave 1 — media (11 tools, highest value)
ffmpeg, imagemagick, pillow, yt-dlp, faster-whisper, whisper.cpp, piper, edge-tts, espeak-ng,
sox, pydub.
Expose as tools: `media.probe`, `media.trim`, `media.cut_silence`, `media.chapters`,
`media.thumbnails`, `media.clip_vertical`, `media.subtitles_convert`, `media.loudnorm`,
`media.extract_audio`, `media.concat`, `media.watermark`, `media.transcribe` (whisper),
`media.speak` (piper/edge/espeak with automatic fallback).
Acceptance: generate a 6-second test clip with ffmpeg (tone + silence + tone), then prove
silence removal, chapter detection, 9:16 crop (assert output resolution is 1080x1920),
transcription producing non-empty words, and TTS producing a playable file >1 KB.

### Wave 2 — documents (10)
pandoc, libreoffice, pymupdf, pdfplumber, reportlab, weasyprint, python-docx, openpyxl,
python-pptx, jinja2.
Tools: `docs.md_to_pdf`, `docs.docx_to_pdf`, `docs.pdf_text`, `docs.pdf_tables`,
`docs.build_pdf`, `docs.html_to_pdf`, `docs.read_docx`, `docs.read_xlsx`,
`docs.make_deck`, `docs.render_template`.
Acceptance: markdown → real PDF whose extracted text contains the input; xlsx cell read back;
template rendered with a payload.

### Wave 3 — code & data (15)
git, ripgrep, ruff, mypy, pytest, semgrep, radon, pip-audit, ast, duckdb, polars, pandas,
matplotlib, jsonschema, csvkit.
Tools: `code.search`, `code.lint`, `code.types`, `code.security`, `code.complexity`,
`code.symbols`, `code.deps_audit`, `data.sql` (DuckDB over CSV/Parquet), `data.describe`,
`data.chart`, `data.validate`.
Acceptance: `code.search` finds a known string in this repo; `data.sql` runs a real
`SELECT count(*)` over a generated CSV; `data.chart` writes a PNG >5 KB.

### Wave 4 — ai local (7)
ollama, llama-cpp-python, sentence-transformers, sqlite-vec, spacy, langdetect, tiktoken.
Tools: `ai.ask` (Ollama, honest error when absent), `ai.embed`, `ai.semantic_search`,
`ai.entities`, `ai.detect_language`, `ai.count_tokens`.
Acceptance: with no Ollama installed, `ai.ask` returns a clear "install ollama" error and
**the rest of the system keeps working**; with a fake/echo model injected, the plumbing works.
Upgrade BM25 retrieval to embeddings **only as an optional path** — keep BM25 as the default
so the system stays dependency-free.

### Wave 5 — web, ops, comms, security (22)
httpx, playwright, beautifulsoup4, trafilatura, feedparser, duckduckgo-search, wikipedia-api,
arxiv, open-meteo, nominatim, psutil, watchfiles, sqlite3, ntfy, rclone, cron,
telegram, discord-webhook, smtp, pyjwt, cryptography, argon2.
Tools: `web.fetch`, `web.extract_article`, `web.screenshot`, `web.rss`, `web.search`,
`ops.metrics`, `ops.notify`, `ops.backup`, `comms.telegram`, `comms.discord`, `comms.email`,
`security.sign`, `security.hash`.
Acceptance: `web.fetch` hits a real public URL (skip gracefully offline — mark the test with a
network marker and report skipped, do not fake the response). Every tool that needs a token
must raise `needs_setup: <var name>` rather than silently doing nothing.

## 4. Make the assistant use them (this is the point)

- Planner: extend the keyword table so a plain sentence maps to the right tool
  ("is PDF ko text me badlo" → `docs.pdf_text`; "chart banao" → `data.chart`).
- JARVIS chat must answer with the tool result, and must say which tool ran.
- `/v1/tools` lists available tools (with `available: true/false`), `/v1/tools/search?q=`
  ranks them, `POST /v1/tools/{id}/run` executes one.
- Dangerous tools (delete, overwrite, send message, spend anything) go behind an approval
  token; read-only tools stay open.

## 5. Definition of done — paste this table filled in

```
[ ] pytest -q                          → <before> -> <after>, all pass
[ ] tools registered                   → <n> of 65
[ ] tools available in THIS container  → <n> (rest honestly say "unavailable: <install>")
[ ] every available tool has a real-run test → <n>
[ ] one end-to-end flow                → e.g. "download -> cut silence -> transcribe -> pdf"
[ ] GET /v1/tools shows availability   → pasted
[ ] a missing binary is reported, not faked → pasted
[ ] no tool returns mock data          → grep for "sample", "dummy", "TODO" in tool handlers
[ ] route count                        → <before> -> <after>
```

## 6. What is genuinely NOT free (do not pretend otherwise)

Listing something here as a tool is a failure, not a bonus:

- High-volume web search APIs (Google/Bing/SerpAPI) — free tiers are tiny.
- Premium TTS voices (ElevenLabs-class) and official image/video generation APIs.
- Managed vector databases and message queues (use SQLite + files instead).
- Cloud GPU at scale (Modal/RunPod free credits are limited; local Ollama is the free route).
- Anything that "requires a credit card to start" — that is not free, that is a trial.

If the attached JSON marks `tos_caveat` (yt-dlp, edge-tts, duckduckgo-search, nominatim),
implement it with caching, a timeout, and a local fallback — and document the caveat in
`docs/TOOLS.md` next to that tool.

## 7. Reporting format for every wave

```
WAVE <n> — <category>
installed: <tools that pass their test>
unavailable here: <tool> — <exact install command>
tests: <before> -> <after>
real run: <one line, with the actual output of a real file>
next: <the single next step>
```

One caveat, said once and honestly: if you cannot install a binary in this environment, say
so in the `unavailable` line. I will install it. What I will not accept is a tool that claims
to work and returns made-up output.

## 8. Compact version (if your context window is small)

```
Give this assistant every tool in free_toolbelt.json, wave by wave: media -> docs ->
code/data -> ai -> web/ops.
Rules: (1) a tool exists only after its test command passed AND it processed a real file;
(2) missing binary => return {"error": "unavailable: <install>"} at call time, never fake
data; (3) registry with runtime availability checks + BM25 search; (4) one file per category,
decorator registration, no elif-chains; (5) approval token for destructive or messaging
tools; (6) after each wave: pytest count, tool count, one real-run output, commit.
Report any tool you could not install — that is acceptable, a fake tool is not.

Do wave 1 (media) now. Stop after reporting.
```

=== PROMPT END ===

---

## Us AI ke jawab ko kaise check karein

| Wo bolega | Tum poocho |
|---|---|
| "65 tools add kar diye" | `curl /v1/tools \| grep -c '"available": true'` — kitne **asli me** available hain |
| "tests pass hain" | `pytest -q` ki aakhri line paste karo |
| "ffmpeg kaam kar raha hai" | ek asli clip par command chala kar output path dikhao |
| "tool unavailable hai" | acha hai — usko `docs/TOOLS.md` me likhwao, wo honest hai |

**Yaad rakho:** jo AI "sab ho gaya" bolta hai par ek bhi real file process nahi dikhata, usne
kuch nahi kiya. Tumhare paas ab 65 tools ki checklist hai — poochne ke liye ek list kaafi hai.
