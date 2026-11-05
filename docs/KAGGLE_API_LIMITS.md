# Kaggle API key: kya kar sakta hai, kya nahi

Seedha jawab: **Kaggle API key se "saari tools Kaggle par" chal jayengi — lekin batch me,
live assistant ki tarah nahi.** Key compute nahi deti; wo tumhare account ko *notebook
submit karne* ki permission deti hai.

## Farq samajh lo (yahi asli jawab hai)

| Kaam | Kaggle API key se? | Kyun |
|---|---|---|
| Notebook/kernel remotely chalao (GPU/CPU) | ✅ | `kaggle kernels push` |
| Us kernel ka status dekho | ✅ | `kaggle kernels status` |
| Output (SRT, video, JSON) download karo | ✅ | `kaggle kernels output` |
| Us kernel me toolbelt ke tools chalao | ✅ | wahi run, bas batch me |
| PC se live `curl` karke JARVIS se baat karo | ❌ | kernel me inbound port nahi hota |
| Server 24×7 chalta rahe | ❌ | session ~9h (GPU) / 12h (CPU), phir band |
| "Ek message bheja, turant jawab" | ❌ | har job me VM cold start + queue = minute lagte hain |
| Data hamesha yaad rahe | ❌ | `/kaggle/working` restart par wipe |

Isliye do raste hain, dono is repo me hain:

| Rasta | Kab | File |
|---|---|---|
| **A. Batch** (API key) | transcribe 2 ghante ki video, 100 videos ke thumbnails, batch report | `app/kaggle_runner.py` |
| **B. Live tunnel** (manual) | JARVIS se baat karna, live tools | `deploy/kaggle/jarvis_kaggle.py` |

## Setup (ek baar)

1. kaggle.com → **Account** → **Create New Token** → `kaggle.json` download.
2. Wo file `~/.kaggle/kaggle.json` me rakho (Windows: `C:\Users\<you>\.kaggle\kaggle.json`).
   Ya env me: `KAGGLE_USERNAME` + `KAGGLE_KEY`.
3. CLI: `pip install -r requirements-kaggle.txt`

**Kaggle key mujhe mat bhejna** — ye tumhare poore account ki key hai. Isi machine par
`kaggle.json` rakh do, backend khud padh lega (aur status me sirf username dikhayega).

```bash
curl localhost:8000/v1/kaggle/status -H "X-API-Key: $KEY"
# {"cli": true, "credentials": true, "username": "ali", "limits": {...}}
```

## Batch job kaise bhejte hain

```bash
# 1. dekho kaunse templates hain
curl localhost:8000/v1/kaggle/templates -H "X-API-Key: $KEY"

# 2. job bhejo — file Kaggle dataset me honi chahiye (dataset_sources)
curl -X POST localhost:8000/v1/kaggle/jobs -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{
    "kind": "transcribe",
    "params": {"input_path": "/kaggle/input/my-videos/lecture.mp4"},
    "dataset_sources": ["ali/my-videos"]
  }'
# → {"id": 1, "ref": "ali/uai-transcribe-20261105-131500", "status": "queued"}

# 3. poll
curl -X POST localhost:8000/v1/kaggle/jobs/1/refresh -H "X-API-Key: $KEY"

# 4. complete hone par output lao (SRT + TXT)
curl -X POST localhost:8000/v1/kaggle/jobs/1/output -H "X-API-Key: $KEY"
# → {"files": ["transcripts/lecture.srt", "transcripts/lecture.txt"], "job_result": {...}}
```

### Templates

| `kind` | Kaggle par kya chalta hai | GPU |
|---|---|---|
| `transcribe` | faster-whisper → `.srt` + `.txt` | ✅ |
| `video` | ffmpeg: `probe` / `thumbnails` / `chapters` / `cut_silence` | ❌ |
| `toolbelt` | koi bhi belt tool + args | ❌ |
| `assistant` | ek `jarvis.chat()` turn (rules mode, ya Kaggle secret me Claude key ho to model) | ❌ |

Har notebook ke aakhir me `###UAI-RESULT###` marker ke baad JSON print hota hai — backend
output download karke wahi JSON parse karke deta hai. Isliye "job chala" ka proof asli output
hota hai, koi andaaza nahi.

## Live assistant chahiye to (rasta B)

Kaggle API se tunnel nahi khulta; notebook **UI me kholna padta hai**:

1. `deploy/kaggle/JARVIS_kaggle.ipynb` open karo, Internet On, secrets daalo.
2. Cell chalao → public `https://<random>.trycloudflare.com` URL milega.
3. `curl` wahi se karo — poora JARVIS + belt us box par chal raha hoga.

Band karte hi URL mar jata hai. Ye "hosting" nahi, "session" hai.

## Paise aur limits

| Cheez | Limit |
|---|---|
| GPU | ~30 ghante/hafta (T4 ×2 / P100), session max ~9h |
| CPU | 12-hour session limit, ~20 min idle par band |
| Disk | ~20 GB `/kaggle/working`, restart par wipe |
| API calls | Kaggle CLI ke push/poll par koi paid charge nahi |
| Claude (agar `assistant` template me use ho) | tumhari key, tumhara bill |

## Jo maine jaan-boojh kar nahi banaya

- Kaggle key ko backend me **store** karna — wo `~/.kaggle/kaggle.json` me rehti hai, hum
  sirf padhte hain aur status me mask karke dikhate hain.
- Ek kernel ko "always-on server" ki tarah treat karna — limit hi nahi deti.
- Job complete hone se pehle output dikhana — `fetch_output` saaf mana karta hai
  (`job is 'running', not complete`).

## Ek aur baat (is repo me mila)

Is kaam ke dauran `catalog/github_repos.json` (205 repos) accidentally 2 repos par
overwrite ho gaya tha — `test_catalog_guard` ne pakad liya, `git checkout` se wapas aaya.
Agar kabhi `/v1/tools` khali lage to wahi guard chalao:

```bash
python scripts/fetch_github_repos.py --check   # ya: git checkout catalog/github_repos.json
```
