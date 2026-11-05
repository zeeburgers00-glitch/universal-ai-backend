# "Free + unlimited" — kya sach me possible hai

**Short answer: managed cloud APIs me unlimited kuch nahi.** Par teen layers mila kar aap
practically unlimited ho sakte hain — bas sach pata hona chahiye.

---

## Layer 1 — Local model: **sach me free + sach me unlimited** ✅

Aapke apne computer par model chalao. Koi key nahi, koi daily cap nahi, data bahar nahi jata.
Bijli ke ilawa cost zero, aur jitni baar chahein chalao.

```bash
# 1) Ollama install karo, phir model khinch lo
ollama pull llama3.1:8b          # ~4.7 GB, 8GB RAM par chalta hai
ollama serve                     # http://127.0.0.1:11434

# 2) Backend ko bolo local pehle use kare
AI_PROVIDER_ORDER=ollama,groq,gemini
OLLAMA_DEFAULT_MODEL=llama3.1:8b
```

Backend me support pehle se hai: `ollama`, `lmstudio`, `llamacpp` providers (loopback HTTP allowed).
Test proof: `tests/test_free_pool.py::test_router_uses_a_local_server_for_free` ek asli local
OpenAI-compatible server chala kar check karta hai — key ke bina answer aata hai.

**Sach:** 8B local model GPT-5.6/Claude jaisa nahi hota. Script writing theek, complex reasoning kamzor.
Zyada power chahiye to 14B/32B chalao (16–24 GB RAM) ya GPU.

## Layer 2 — Free-tier rotation: capped, par multiplied ⚠️

Ek provider ki free tier chhoti hai; 4–5 mila kar kaafi bara ho jata hai.

| Provider | Free cap (estimate) | Notes |
|---|---|---|
| Gemini 3.x Flash | ~20/day | sabse tight |
| Gemini Flash-Lite | ~500/day | sasta kaam |
| Groq (Llama/Qwen/Kimi) | ~14,400/day | 30 RPM |
| OpenRouter `:free` models | ~50/day | account balance $0 chahiye |
| Mistral / Cerebras free | ~1,000/day | key chahiye |

Backend ab **quota-aware** hai (`app/quota.py`):
- har call par counter barhta hai, **429 par provider turant skip** ho jata hai
- agla provider khud le leta hai (failover)
- din UTC 00:00 par reset

```bash
AI_PROVIDER_ORDER=ollama,groq,gemini,openrouter
AI_QUOTA_GEMINI=20          # apna estimate set karo
```

**Keyring — ek provider ki kai keys:**
```bash
GROQ_API_KEYS=key1,key2,key3     # 3 × 14,400 = 43,200 requests/day
```
⚠️ **Ye legitimate hai sirf un keys ke saath jo aap ki apni hain (same org/project).**
Naye accounts bana kar limit bypass karna zyadatar providers ki **ToS violation** hai — account ban ho sakta hai.
Main aap ko wo suggest nahi karunga.

## Layer 3 — Bina AI ka fallback: unlimited ♾️

Jab koi model available na ho, backend template/rule-based path use karta hai:
video script, timing, captions, render — sab chalta rehta hai (verified: 1080p MP4 bina kisi key ke).

Quality AI jaisi nahi, par **kabhi fail nahi hota aur kabhi paisa nahi leta**.

---

## Kya dekhne ke liye endpoints

```bash
GET  /v1/ai/free/status              # kaun configured, kitni keys, kitna bacha
GET  /v1/ai/free/status?probe=true   # local server sach me chal raha hai?
POST /v1/ai/free/reset               # counters saaf (API key chahiye)
```

Sample output (local down, Groq configured):
```json
{
  "unlimited_options": ["llamacpp", "lmstudio", "ollama"],
  "local_running": [],
  "providers": [
    {"provider": "ollama",  "configured": true, "daily_cap": 0, "remaining_today": null, "local": true},
    {"provider": "groq",    "configured": true, "daily_cap": 14400, "remaining_today": 14400},
    {"provider": "gemini",  "configured": false}
  ]
}
```

---

## Bottom line

| Chahiye | Solution | Unlimited? |
|---|---|---|
| AI bilkul free, unlimited | Ollama local | ✅ haan (aapka hardware) |
| Best quality, free | Free tiers rotate karo | ❌ daily caps |
| Video/thumbnail/render | Local ffmpeg | ✅ haan |
| Image/video generation | Paid (Nano Banana/Veo/ComfyUI GPU) | ❌ |
| 4K, bulk TTS, high concurrency | Paid | ❌ |

**Jo koi bole "sab kuch free unlimited" — wo jhooth bol raha hai.** Local model + rotation +
template fallback = practically unlimited, aur maine wo teeno laga diye hain.
