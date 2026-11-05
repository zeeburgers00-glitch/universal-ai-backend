# JARVIS ko free me advance karna — 7 layers

Tumhara JARVIS "pagal" lagta hai to 99% chance hai ke usme **ye 7 cheezein** missing hain.
Model badalne se kuch nahi hota — architecture badalne se hota hai. Aur saatoin free hain.

| # | Layer | Bina iske kya hota hai | Free me kaise |
|---|---|---|---|
| 1 | **Memory** | har baat bhool jata hai, tumhe dobara batana padta | SQLite file (0 rupya) |
| 2 | **Retrieval** | purani baat dhoondh nahi sakta | BM25 (koi embedding model nahi) |
| 3 | **Planning** | seedha jawab deta hai, kaam nahi karta | goal → steps, rules se |
| 4 | **Tools** | sirf baatein, koi action nahi | 40 agents + 151 routes |
| 5 | **Local brain** | general knowledge zero | `ollama` + 3B–8B model |
| 6 | **Verification** | jhooth bol deta hai "ho gaya" | har step ka result check |
| 7 | **Honesty** | "main ye kar sakta hoon" ka pata nahi | capability list + clear error |

## Is repo me ab ye poora stack hai

| Endpoint | Kaam |
|---|---|
| `POST /v1/jarvis/chat` | ek turn: memory seekho → tools chalao → jawab do |
| `POST /v1/jarvis/plan` | kya chalega, bina chalaye |
| `GET/POST/DELETE /v1/jarvis/memory` | facts + BM25 search + bhoolna |
| `GET /v1/jarvis/history` | session-wise baat-cheet |
| `GET /v1/jarvis/status` | memory size, model on/off, agents count |

```bash
KEY=...; H="X-API-Key: $KEY"; B=localhost:8000

curl -s -X POST $B/v1/jarvis/chat -H "$H" -H 'content-type: application/json' \
  -d '{"message":"mera naam Ali hai, mujhe free tools pasand hai"}'
# → {"reply":"Yaad rakh liya: name=Ali, likes=free tools...","learned":[...]}

curl -s -X POST $B/v1/jarvis/chat -H "$H" -H 'content-type: application/json' \
  -d '{"message":"live_demo.mp4 ke chapters banao"}'
# → {"reply":"Chapter Writer: done — duration=4.0 · chapter_count=1","actions":[...]}

curl -s -X POST $B/v1/jarvis/chat -H "$H" -H 'content-type: application/json' \
  -d '{"message":"tell me a joke"}'
# → {"reply":"Ye mujhe samajh nahi aaya. Jo pakka kar sakta hoon: backup-keeper, ..."}
```

**Last wala jawab hi asli farq hai.** Dumb assistant yahan bakwaas bana deta hai; ye batata
hai ke kya kar sakta hai — aur model lagane par yahi sawaal model ko jata hai.

## Model free me kaise lagao (yahi "advance" ka asli jump hai)

```bash
# 1) install (Linux/macOS)
curl -fsSL https://ollama.com/install.sh | sh

# 2) RAM ke hisaab se model chuno — sab free, koi key nahi
ollama pull qwen2.5:3b-instruct     # ~2 GB RAM  — laptop-safe
ollama pull llama3.1:8b-instruct-q4_0  # ~5 GB RAM — best quality/price
ollama pull qwen2.5:1.5b-instruct   # ~1 GB RAM  — phone/edge

# 3) backend ko bolo isko use kare
OLLAMA_BASE_URL=http://127.0.0.1:11434 AI_PROVIDER_ORDER=ollama uvicorn app.main:app
```

Ab wahi `/v1/jarvis/chat` ka jawab model deta hai, **memory aur tool results ke saath**
(prompt me MEMORY aur TOOLS RUN blocks jate hain). Model fail ho jaye ya na ho — tools
phir bhi chalte hain aur rule-based jawab aata hai. Kabhi jhooth nahi.

GPU ki zarurat nahi. 8B q4 CPU par ~5–10 token/sec deta hai — chat ke liye kaafi.

## Apne existing JARVIS ko isse jodna (3 tareeqe)

**1. HTTP se (kisi bhi language se):**
```python
import httpx
r = httpx.post("http://localhost:8000/v1/jarvis/chat",
               headers={"X-API-Key": KEY},
               json={"message": user_text, "session": user_id})
answer = r.json()["reply"]
```
Telegram bot, Discord, desktop app, web — sab yahi ek call karega. Memory server par rehti hai.

**2. Python import se (agar tumhara jarvis isi repo me hai):**
```python
from app import jarvis
jarvis.chat("backup lo", session="desktop")
```

**3. Prompt-only (agar tumhara apna OpenAI/Ollama loop hai):** system prompt me ye daalo —
yahi cheez "pagal" ko "samajhdaar" banati hai:
```
You are JARVIS. Rules:
- Use MEMORY for facts about the user; never invent them.
- Only claim an action if TOOLS shows its result.
- If unsure, name the tool id to use, or say you cannot.
- Answer in the user's language, 1-4 sentences.
```

## Free upgrade ladder (isi order me karo, har step ka faayda hai)

1. **Memory** — `POST /v1/jarvis/memory` + auto-extract patterns (`mera naam X hai`,
   `yaad rakho: ...`). Turant farq: dobara nahi batana padta.
2. **Tools** — 40 agents (`/v1/agents/runtime`). Ab "karo" ka matlab kuch hota hai.
3. **Planning** — `/v1/jarvis/plan`. Multi-step kaam ("chapters + package") dikhta hai.
4. **Local model** — Ollama. Ab samajhne ki power aati hai, tools wahi rehte hain.
5. **Verification** — har step `ok` check. "Ho gaya" sirf tab jab sach me hua ho.
6. **Eval** — 20 sawaal likho jinke jawab tumhe pata hain, har change ke baad chalao.
   Ye sabse zyada ignore hota hai aur sabse zyada faayda deta hai.

## Sach (jo chhupaya nahi)

- **Rule-based mode me ye genius nahi hai** — 30+ intents samajhta hai, creativity nahi.
  Model lagane par hi "advanced" feel aata hai. Dono free hain, par RAM chahiye.
- Memory **facts + episodes** hai; ye long-term reasoning ya entity graph nahi hai.
- BM25 retrieval hai (embeddings nahi) — "milta-julta" dhoondhta hai, "matlab" nahi samajhta.
- Voice (STT/TTS) is layer me nahi hai — `/v1/voice/*` aur worker alag hai, wo bhi free
  (browser Web Speech ya Whisper local).
- Ollama call **synchronous** hai; lamba jawab 60s le sakta hai (serverless par limit dekho).
