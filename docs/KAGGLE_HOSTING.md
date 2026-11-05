# Hosting JARVIS + the tool belt on Kaggle

You said it plainly: give Claude a key, put the tools on Kaggle, use them from there. This
is that path, with the parts Kaggle will actually let you do and the parts it will not.

Files:

| Path | What it is |
|---|---|
| `deploy/kaggle/jarvis_kaggle.py` | bootstrap: secrets → uvicorn → cloudflared tunnel → printed URLs |
| `deploy/kaggle/JARVIS_kaggle.ipynb` | the same thing as a notebook you can open and run |
| `deploy/kaggle/README.md` | trade-offs table, Ollama-on-GPU variant, cost notes |

**API key se kya hota hai:** `docs/KAGGLE_API_LIMITS.md` — short version: key batch kernels
chala sakti hai (`/v1/kaggle/*`), live endpoint nahi khol sakti. Wo notebook yahan se
manually start hota hai, tabhi tunnel URL milta hai.

## Five minutes, start to finish

1. Kaggle → **Create → Notebook** → File → Import → `JARVIS_kaggle.ipynb` (or paste the
   clone cell).
2. Settings → **Internet: On**. Without it, no Claude calls and no tunnel.
3. Add-ons → **Secrets**:

   | Secret | Why |
   |---|---|
   | `ANTHROPIC_API_KEY` | Claude brain (`sk-ant-…`) |
   | `BACKEND_API_KEY` | the key clients send as `X-API-Key`; make it long |

4. Run the notebook. You get:

```json
{
  "local_url": "http://127.0.0.1:8000",
  "public_url": "https://brave-tiger-violet-123.trycloudflare.com",
  "api_key": "<your key>",
  "claude": true
}
```

5. From anywhere:

```bash
curl -s $PUBLIC/v1/belt/status -H "X-API-Key: $KEY"
curl -s -X POST $PUBLIC/v1/jarvis/chat -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message":"tool ffmpeg op=probe path=/kaggle/working/uai-data/sample.mp4"}'
```

## What Kaggle really is

| Constraint | Consequence |
|---|---|
| No inbound ports | You need the tunnel. URL changes on every restart |
| ~9h GPU / ~12h CPU session | Nothing survives the session end; no always-on API |
| `/kaggle/working` wiped | SQLite memory and renders are temporary unless you commit or sync to Drive |
| Secret values are notebook-scoped | Rotate `BACKEND_API_KEY` per session if the URL leaks |
| Public tunnel URL | Anyone with URL + key can run your tools; the key is the only lock |

For an always-on endpoint this repo runs unchanged on a free-tier VM (Render, Fly, Oracle
free tier) or your own machine. Use Kaggle for the heavy work: whisper transcription on
GPU, batch renders, embedding jobs.

## Two honest brains

**Claude (paid, best quality).** Set `ANTHROPIC_API_KEY`. Model defaults to
`claude-sonnet-4-5`; override with `ANTHROPIC_DEFAULT_MODEL`. One `/v1/jarvis/chat` message
costs at most 3 tool rounds. `/v1/jarvis/chat` returns `"model": {"provider": "anthropic",
"rounds": 2}` so you can see what you paid for.

**Ollama on the Kaggle GPU (free).**

```bash
curl -fsSL https://ollama.com/install.sh | sh
nohup ollama serve > /tmp/ollama.log 2>&1 &
ollama pull qwen2.5:3b-instruct
python deploy/kaggle/jarvis_kaggle.py --port 8000 --provider ollama
```

Quality is lower than Claude, especially at tool selection. That trade-off is stated, not
hidden: the tool belt does the factual work, the model only chooses and phrases.

**Neither available?** The backend still starts. JARVIS answers in rules mode, runs the
same tools via `tool <id> k=v`, and every reply carries `"used_model": false`.
