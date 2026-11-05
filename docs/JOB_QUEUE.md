# Job queue — SQLite, Redis ke bina

`/v1/jobs/*` — durable queue jo ek SQLite file me rehti hai. Celery ke liye broker
chahiye (jo free deploy par down ho sakta hai ya bill de sakta hai); ye uske bina chalta hai.

| Endpoint | Kaam |
|---|---|
| `GET /v1/jobs/kinds` | kaun se job types hain + queue stats |
| `POST /v1/jobs` | job queue me daalo (`kind` + `payload`) |
| `GET /v1/jobs/{id}` | status, progress, stage, result, error |
| `GET /v1/jobs?status=done` | filter |
| `POST /v1/jobs/{id}/cancel` | queued job cancel |
| `POST /v1/jobs/run-once` | ek job abhi chalao (tests/cron) |

## Built-in job kinds (video toolkit ke saath wired)

`video.probe`, `video.cut_silence`, `video.chapters`, `video.thumbnails`,
`video.loudnorm`, `video.clip`, `video.subtitles`

```bash
curl -s -X POST localhost:8000/v1/jobs -H "X-API-Key: $KEY" -H 'content-type: application/json' \
  -d '{"kind":"video.cut_silence","payload":{"path":"data/raw/talk.mp4"}}'
# → {"id":"...","status":"queued"}

curl -s localhost:8000/v1/jobs/<id> -H "X-API-Key: $KEY"
# → {"status":"done","progress":100,"result":{"output":"...","removed_seconds":42.1}}
```

## Apna handler

```python
from app import jobs

@jobs.register("report.weekly")
def weekly(payload, progress):
    progress(10, "collecting")
    ...
    return {"file": "..."}
```

Handler ke `return` value hi job ka `result` banta hai. Exception = `status: failed` +
`error` + traceback (worker thread zinda rehti hai).

## Settings

| Env | Default | Matlab |
|---|---|---|
| `UAI_JOBS_DB` | `$UAI_DATA_ROOT/jobs.db` | DB path (shared volume ho sakta hai) |
| `UAI_JOBS_CONCURRENCY` | 2 | worker threads |
| `UAI_JOBS_DISABLE` | — | `1` = background workers band (tests/cron mode) |
| `UAI_MEDIA_ROOTS` | — | video jobs ke liye allowed media roots |

## Honest limits

- **Single host**: ek hi process ke threads claim karte hain. Kai containers ho to
  `UAI_JOBS_DB` shared volume par rakho, ya Celery use karo.
- Job **cancel** sirf queued state me kaam karta hai; chalte hue job ko force-kill nahi
  karta (FFmpeg chhod dena process kill ke bina mushkil hai).
- SQLite WAL mode; crash ke baad bhi jobs DB me rehte hain (restart test me verified).
