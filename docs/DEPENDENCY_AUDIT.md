# Dependency audit — "minimal aur free" ka proof

Claim nahi, **scan**. `GET /v1/audit/dependencies` source tree ko AST-parse karta hai aur
`requirements.txt` se compare karta hai.

```bash
curl -s localhost:8000/v1/audit/dependencies -H "X-API-Key: $KEY" | python -m json.tool
```

Aaj ka asli result (is repo par):

```
declared: 10            python_files_scanned: 100
used:        fastapi 42 files, httpx 23, pydantic 18, pytest 17, celery 8,
             pyyaml 4, imageio-ffmpeg 3, python-dotenv 2
runtime_only: uvicorn, python-multipart   (process use karta hai, import nahi)
declared_but_not_imported: []            ← dead weight zero
imported_but_not_declared: []            ← chhupa hua dependency zero
unpinned: []                             ← har package ka ceiling hai
verdict: "Requirements match the imports and every entry has a ceiling."
```

## Ye kya pakadta hai

| Cheez | Matlab |
|---|---|
| `declared_but_not_imported` | requirement list me hai, code me kahin use nahi → hatao |
| `imported_but_not_declared` | code import kar raha hai par manifest me nahi → deploy par tootega |
| `unpinned` | version ceiling nahi → rebuild par surprise |
| `runtime_only` | uvicorn/multipart jaisi cheezein jo import nahi hoti par chahiye |

Aliases handle hote hain (`pyyaml` → `yaml`, `python-dotenv` → `dotenv`,
`imageio-ffmpeg` → `imageio_ffmpeg`), aur `deploy/`/`workers/` me sirf optionally
import hone wali cheezein flag nahi hoti.

## Sach

- Ye **static** analysis hai — dynamic `importlib` calls nahi pakde jaate.
- "Unused" ka matlab "kahin import nahi hua", ye nahi ke package zaroori nahi
  (uvicorn isi liye `runtime_only` list me hai).
