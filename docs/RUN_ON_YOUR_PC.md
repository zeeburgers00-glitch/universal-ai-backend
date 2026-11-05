# Apne PC par chalana (Windows / macOS / Linux)

Haan — ye poora backend **tumhare PC par chalta hai**. Ye ek normal Python app hai, koi
Docker/GPU/paid host zaroori nahi. Windows par FFmpeg bhi alag se install nahi karna padta
(`imageio-ffmpeg` wheel ke saath aa jata hai).

## Windows — sabse chhota rasta

1. [python.org](https://www.python.org/downloads/) se Python 3.11+ install karo.
   **"Add Python to PATH"** ka box tick karna mat bhoolo.
2. Ye repo download/clone karo (`git clone …` ya ZIP extract).
3. `scripts\start_windows.bat` par **double-click**.

Script khud: `.venv` banata hai → requirements install karta hai → API key generate karke
`.backend_api_key` me save karta hai → server start karta hai → browser me
`http://127.0.0.1:8000/editor` khol deta hai.

Pehli baar ~2 minute lagta hai, uske baad ~5 second.

```powershell
# optional switches
.\scripts\start_windows.ps1 -Port 8100      # doosra port
.\scripts\start_windows.ps1 -Lan            # phone se same wifi par kholna ho
.\scripts\start_windows.ps1 -NoBrowser      # sirf server (Task Scheduler ke liye)
.\scripts\start_windows.ps1 -NoInstall      # pip skip
```

| Cheez | Kahan milegi |
|---|---|
| UI | `http://127.0.0.1:8000/editor` |
| API docs | `http://127.0.0.1:8000/docs` |
| API key | `.backend_api_key` file, ya startup window me print hota hai |
| Data (memory, mood, jobs) | `data\` folder (repo ke andar) |
| Band karna | Window me `Ctrl+C` |

## Desktop jaisa window (optional)

Browser tab ki jagah borderless window chahiye? Chrome/Edge ka app mode:

```bash
python scripts/desktop_app.py            # server chal raha ho tab
python scripts/desktop_app.py --wait     # server ka intezaar khud kare
```

Ye `chrome --app=` / `msedge --app=` use karta hai — koi Electron, koi installer, koi signing
nahi. Browser na mila to normal tab khul jayega aur script saaf bata dega.

## macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BACKEND_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# UI: http://127.0.0.1:8000/editor
```

## Phone se chalana (same wifi)

```powershell
.\scripts\start_windows.ps1 -Lan
```

Windows Firewall poochhega → **Allow** (private network). Phir PC ka IP nikaalo
(`ipconfig` → IPv4 Address, jaise `192.168.1.7`) aur phone me kholo:
`http://192.168.1.7:8000/editor`.

Ghar se bahar se chahiye? Do safe raste: (a) Kaggle + cloudflared tunnel
(`docs/KAGGLE_HOSTING.md`), ya (b) `cloudflared tunnel --url http://127.0.0.1:8000` apne PC
par — dono me API key kisi ko na do jo tumhe na de.

## PC par kya-kya chalta hai

| Feature | PC par | Note |
|---|---|---|
| JARVIS chat + memory | ✅ | SQLite, `data\` me |
| 65-tool belt | ✅ (jo install hain) | `GET /v1/belt` dekho; missing tools install command batate hain |
| ffmpeg tools | ✅ | bundled `imageio-ffmpeg`, alag install nahi |
| Character + mood + mind | ✅ | `data\character.json`, `affect.db`, `mind.db` |
| Claude brain | ✅ key ke saath | `ANTHROPIC_API_KEY` env me |
| Local model (Ollama) | ✅ agar PC 8 GB+ RAM | `ollama serve` + `AI_PROVIDER_ORDER=ollama` |
| Voice (Whisper/Piper) | ⏳ abhi code me nahi | agla kaam, CPU par bhi chalega |
| Gmail accounts | ✅ OAuth ke baad | `docs/ACCOUNTS_GMAIL.md` |

## Auto-start (Windows)

1. `Win + R` → `shell:startup` → Enter.
2. Wahan ek shortcut banao jo ye chalaye:
   `powershell -NoProfile -ExecutionPolicy Bypass -File "C:\path\to\repo\scripts\start_windows.ps1" -NoBrowser`
3. Restart ke baad server khud chalu ho jayega, browser nahi khulega.

## Masle (aur seedhe jawab)

| Masla | Wajah / hal |
|---|---|
| `python` not recognized | Python install me PATH tick nahi kiya — dobara install karo |
| `ERROR: pip install fail` | Internet/proxy; `-NoInstall` ke saath dobara chalao agar deps pehle se hain |
| Port 8000 busy | `-Port 8100` |
| UI khulta hai par "API key" error | `.backend_api_key` file ka content paste karo UI ke key field me |
| `ffmpeg not found` | `.venv` delete karke script dobara chalao (wheel dobara install hoga) |
| Windows Defender warning | Local Python + local server; `start_windows.ps1` khol ke padh sakte ho — kuch chhupa nahi hai |
