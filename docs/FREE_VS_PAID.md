# Kya free hai, kya nahi — seedhi baat (Nov 2026)

**TL;DR: "unlimited" kuch bhi nahi hai.** Teen alag cheezein hain, inhe mix na karo:

1. **Code / repos** — free to read, par licence + hosting cost alag
2. **Hamara catalog** — 100% free, offline, no quota (local JSON file)
3. **Model APIs + GPU** — yahan paisa aur limits hain

---

## 1. GitHub tool registry (196 repos) — free hai, par unlimited nahi

| Cheez | Limit |
|---|---|
| Snapshot (`/v1/discover/github/registry`) | **Unlimited** — local JSON, koi network call nahi |
| Live search (`/v1/discover/github`) | GitHub ke quota par — token ke bina ~60 req/hour, token ke saath 5,000/hour, **search 30/minute** |
| Repo code use karna | Licence par depend |
| Self-host karna | Aapka server, aapka bill |

**Licence ka sach (registry me counted):**
- 185 repos: MIT / Apache-2.0 / BSD — use kar sakte ho (attribution rakho)
- **11 repos: koi licence nahi** — legally default copyright, production me risky
- Kuch AGPL/NOASSERTION hain (jaise `firecrawl`, `n8n`, `dify`) — inhe **SaaS bana kar bechne** par source
  share karna padta hai. Personal/internal use theek hai.

---

## 2. Models — free tier hai, magar chhota

| Provider | Free? | Actual limit |
|---|---|---|
| **Gemini** (3.8/3.6 Flash) | Haan, card ke bina | ~**20 requests/day**, ~5 RPM, 250k TPM — per project |
| **Gemini** (3.5/3.1 Flash-Lite) | Haan | ~**500 requests/day** |
| **Gemini Pro / Gemini 4 Argon** | **Nahi** | Paid only |
| **Groq** (Llama 3.3 70B, 8B, Qwen3, Kimi) | Haan | ~30 RPM, 1,000–14,400 requests/day (model ke hisaab se) |
| **Groq Whisper** (speech-to-text) | Haan | ~20 RPM, ~2,000/day |
| **OpenAI** | **Nahi** | Pay per token, koi free tier nahi |
| **Gemini image** (Nano Banana) | **Nahi** | ~$0.03–0.24 per image |
| **Veo 3.1 video** | **Nahi** | Per second billing |
| **TTS (Groq Orpheus)** | Paid | ~$22 per 1M characters |

**Trap jo log miss karte hain:**
- Free tier par Google **aapka data apne products improve karne ke liye use kar sakta hai**
- Ek project ki limit **sab keys par same** hoti hai — nayi key banao to limit double nahi hoti
- Limit khatam = **429**, automatic charge nahi (achhi baat), par kaam ruk jata hai

---

## 3. GPU / compute — free nahi, sasta zaroor hai

| Option | Cost |
|---|---|
| **Aapka apna laptop/PC** | **Free aur genuinely unlimited** (bijli chhod kar) — render, thumbnail, captions sab yahan chal jate hain |
| **Modal** | $30/month free credits, **roll over nahi hote**, idle = $0 |
| **RunPod / Vast.ai** | 4090 ~$0.20–0.34/hour, per-second billing |
| **Kaggle / Colab** | Free GPU hours (Kaggle ~30h/week) par sirf notebooks, server nahi |

---

## 4. Hamare backend me kya free chalta hai (verified)

Bina kisi key ke, aaj test kiya:
- Poori **1080p video render** (1920×1080, 60s, MP4) — free, unlimited, aapke CPU par
- Thumbnail, audio extract, captions burn — free
- Saare catalogs, studio/explorer UI, health/status — free
- 196-repo registry + 67-model catalog — free

Key chahiye (par free tier se kaam ho jata hai): AI script/SEO, Pexels stock, YouTube upload, Supabase storage, voice clone (Modal credits).

**Paid sirf tab:** heavy volume, image/video generation, 4K, real-time voice, ya OpenAI.

---

## 5. Honest summary

| Sawal | Jawab |
|---|---|
| "Sab free hai?" | **Nahi.** ~70% free tier / self-host se chal jata hai |
| "Unlimited hai?" | **Nahi.** Har free tier par daily cap hai — Gemini 20/day is the tightest |
| "Kuch bhi bina paise ke chalega?" | **Haan** — video render, catalogs, workflows, local agents, 196 repos browse |
| "Production scale free me?" | **Nahi.** Free tier sirf dev/testing ke liye hai |
