# Metrics + rate limiting — bina kisi service ke

## `/metrics` (Prometheus text format, public)

```bash
curl -s localhost:8000/metrics | head -12
```

Nikalta hai:

```
uai_up 1
uai_uptime_seconds 812.4
uai_requests_total{method="GET",route="/v1/code/search",status="2xx"} 12
uai_request_duration_seconds_sum{route="/v1/code/search"} 0.412
uai_request_duration_seconds_count{route="/v1/code/search"} 12
uai_request_duration_seconds_bucket{route="/v1/code/search",le="0.25"} 9
uai_inflight_requests 0
```

Route **groups** use karte hain (`/v1/jobs/:id`) taake cardinality na phat jaye.

Aur ek insaan ke padhne wala version: `GET /v1/observability/summary` (API key chahiye).

## `/health/deep` — asli readiness

`/health` sasta liveness hai (load balancer ke liye). `/health/deep` batata hai ke process
**kaam kar sakta hai ya nahi**:

```json
{"status":"ok","checks":[
  {"name":"api_key","ok":true,"detail":"configured"},
  {"name":"data_root","ok":true,"detail":"/data"},
  {"name":"job_db","ok":true,"detail":"/data/jobs.db"},
  {"name":"disk","ok":true,"detail":"18.8 GB free of 20.3 GB"},
  {"name":"ffmpeg","ok":true,"detail":".../imageio_ffmpeg/binaries/ffmpeg-..."},
  {"name":"queue","ok":true,"detail":"queued=0 running=0 done=42 failed=1 workers=2"}
]}
```

- **critical** fail (data dir likhne layak nahi / DB nahi khulti) → HTTP **503**
- warning (key nahi, disk < 1 GB, ffmpeg nahi, queued jobs par worker 0) → **200 + degraded**
- Har check apna detail deta hai — "unhealthy" jaisa bekaar boolean nahi.

## Rate limiting

- Per client: `X-API-Key` (ya IP agar key nahi)
- Sliding window, 1 minute, in-memory
- Default **600/min**; `UAI_RATE_LIMIT=0` = band; `UAI_RATE_LIMIT=60` = 60/min
- `/health` aur `/metrics` exempt hain (monitoring kabhi block na ho)
- Limit cross → `429` + `Retry-After` header

```bash
UAI_RATE_LIMIT=60 uvicorn app.main:app
```

## Sach

- Ye **per-process** hai. 3 containers = 3× limit. Global limit chahiye to Redis/API gateway.
- Restart par counters reset ho jate hain (ye metrics hain, billing records nahi).
- Koi external dependency nahi — na statsd, na sidecar, na account.
