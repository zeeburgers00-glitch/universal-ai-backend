# JARVIS se kaam karana — kya complete karega, kya nahi

Seedha jawab: **haan, wo kaam complete karega jo is machine par asli tool/skill se mumkin hain.**
Baat karne wala hissa (Claude) aage ka plan bana sakta hai, par jo cheez machine par nahi hai
(installed MCP server, OAuth consent, internet access, koi GUI click) wo chup-chaap jhooth nahi
banayega — saaf bolega "unavailable" aur agla step batayega.

## Kaam kaise pura hota hai (3 raaste)

| # | Raasta | Kab | Model key chahiye? |
|---|---|---|---|
| 1 | **Seedha command** — `skill <id> k=v` / `tool ffmpeg op=probe path=clip.mp4` | jab aap id jaante hain | ❌ nahi |
| 2 | **Normal sentence (router)** — "clip.mp4 ko 480p kar do" | jab aap aam bol-chaal me bolte hain | ❌ nahi |
| 3 | **Claude brain** — `ANTHROPIC_API_KEY` ho to model khud `skill_search` → `skill_run` karta hai, 4 rounds tak | naya/ulti-seedhi kaam, jahan shabd match na karein | ✅ haan |

Teenon raaste **ek hi skills engine** chalate hain, isliye result ka proof same hota hai:
asli output file ya asli error.

## Sentence router kya samajhta hai (no key needed)

```
clip.mp4 ko 480p me chhota kar do        → media.video.resize.mp4-to-480p        ✅ chala
clip.mp4 ko webm banao                   → media.video.convert.mp4-to-webm-vp9     ✅ chala
clip.mp4 se audio mp3 nikal do           → media.audio.convert.mp4-to-mp3-192k     ✅ chala
clip.mp4 ka gif banao                    → media.video.gif.mp4                    ✅ chala
photo.png ko jpg me convert karo         → media.image.convert.png-to-jpg-q85      ✅ chala
photo.png ko 720px karo                  → media.image.resize.png-to-720           ✅ chala
rows.csv me duplicate hata do            → data.table.op.dedupe.csv                ✅ chala
text "ali ali sara" ke words batao       → text.word-frequency.inline              ✅ chala
app/skills.py me kitne functions hain    → code.python.symbols                     ✅ chala
app/skills.py me koi secret hai kya      → code.python.secret-scan                 ✅ chala
clip.mp4 ka probe karo                   → media.probe.mp4                         ✅ chala
shorts pack banao                        → recipe.video-to-shorts-pack             ✅ chala (ffmpeg)
release se pehle check karo              → recipe.release-check                    ✅ chala (pytest)
```

Rules:

- **File naam** sentence me ho (`clip.mp4`, `rows.csv`, `app/skills.py`) — CWD, repo aur
  `UAI_DATA_ROOT` teeno me dhoonda jaata hai, isliye `photo.png` bhi mil jaati hai.
- **Text** quotes me ho to inline text maana jaata hai: `text "hello hello" ke word count`.
- Router sirf tab chalta hai jab **koi agent intent** na mile, aur confidence **75%+** ho.
- Confidence kam ho ya kuch match na ho → `"Ye mujhe samajh nahi aaya"` + kareeb ka skill
  suggest karta hai. **Guess karke galat kaam nahi karta.**

## Kya JARVIS pura kar sakta hai (aaj, is machine par)

| Kaam | Hal | Proof |
|---|---|---|
| Video convert / resize / platform export / gif / trim / mute / speed / rotate / probe | ffmpeg skills (712 media skills) | `tests/test_skills.py`, live run |
| Audio nikalna / convert / mono / normalize / silence trim | ffmpeg audio skills | tests + live |
| Image convert / resize / 12 ops | ImageMagick skills | tests + live |
| CSV/TSV/JSON/JSONL ops, asli SQL, sqlite export | stdlib + in-memory SQLite | tests |
| Text stats / emails / URLs / hashtags / slug / dedupe lines | stdlib | tests |
| Code symbols / todos / secrets / imports / complexity (13 languages) | stdlib regex | tests |
| System health, queue, providers, governance tail | in-process modules | live |
| Multi-step recipes (shorts pack, release check, repo brief…) | agent registry | live |
| Yaad rakhna, episodes, governance record | SQLite memory | tests |
| Free tools (git, ripgrep, sqlite3, ast, pytest, ffmpeg, imagemagick) | tool belt | live |
| Naya kaam jahan shabd match na karein | Claude + `skill_search`/`skill_run` (key ho to) | code path + dispatch test |

## Kya pura NAHI kar sakta (bina aap ke kiye)

| Cheez | Kyun nahi | Kya chahiye |
|---|---|---|
| 1,763 external MCP servers (slack, notion, browser, github…) | wo catalogue entries hain, installed nahi | server install + keys, phir native skill banegi |
| Gmail bhejna/padhna | sirf OAuth consent se | aapka Google consent + redirect |
| Internet se live data (mausam, news, rate) | koi browsing tool nahi hai (sirf allowlisted hosts) | ek fetch tool + allowlist, ya MCP |
| Windows GUI clicks / kisi aur app ko chalana | PC par GUI control nahi hai | desktop helper agent (alag kaam) |
| Payment, phone call, WhatsApp message bhejna | koi authenticated channel nahi | MCP/API + aapki key |
| Kaggle par "24/7 always-on" | Kaggle session based hai, working dir wipe hoti hai | apna VPS/PC |
| Kuch bhi **bina proof** claim karna | design rule: fake output kabhi nahi | — |

## Kaise check karein ki kaam hua

```bash
# 1) JARVIS se bolo
curl -X POST localhost:8000/v1/jarvis/chat -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" -d '{"message":"clip.mp4 ko 480p me chhota kar do"}'

# 2) reply me plan + asli output path aata hai
#    "Samajh gaya — media.video.resize.mp4-to-480p chalaya (90% match: 480p)... output: data/video/clip-480p-....mp4"

# 3) file khud dekh lo
ls -lh data/video/
```

Har turn `governance.record("jarvis.chat", ...)` me `intent` aur `ok` ke saath chala jaata hai,
`GET /v1/governance/tail` se audit dikh jaata hai.

## Naya kaam add karna (jab router kisi sentence ko na samjhe)

1. `app/skill_runners.py` me runner + `RUNNERS["xyz"]`.
2. `app/skills.py` me `Skill(...)` entry.
3. `app/task_router.py` me us sentence ke shabd → skill id mapping.
4. `tests/test_task_router.py` me ek line: `("sentence", "skill.id")`.
