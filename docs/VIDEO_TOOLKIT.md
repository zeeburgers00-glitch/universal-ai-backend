# Video toolkit — FFmpeg, local, zero keys

`/v1/video/*` — har operation aapke machine par FFmpeg se chalta hai. Koi model, koi API
key, koi quota nahi. Modal, Docker, ya laptop — sab par same.

| Endpoint | Kaam | Output |
|---|---|---|
| `POST /v1/video/probe` | duration, resolution, fps, streams | JSON |
| `POST /v1/video/cut-silence` | dead air hatao (silencedetect + concat) | MP4 |
| `POST /v1/video/chapters` | pauses se chapters + YouTube description block | JSON |
| `POST /v1/video/thumbnails` | N frames, evenly spaced | JPG set |
| `POST /v1/video/loudnorm` | EBU R128, default −14 LUFS | MP4/M4A |
| `POST /v1/video/clip` | segment + centre-crop (9:16, 1:1, 4:5, 16:9) | MP4 |
| `POST /v1/video/subtitles` | SRT ↔ VTT | .srt/.vtt |

## Example

```bash
KEY="X-API-Key: $BACKEND_API_KEY"

curl -s -X POST localhost:8000/v1/video/cut-silence -H "$KEY" -H 'content-type: application/json' \
  -d '{"path":"data/raw/talk.mp4","threshold_db":-30,"min_silence":0.6}'

curl -s -X POST localhost:8000/v1/video/chapters -H "$KEY" -H 'content-type: application/json' \
  -d '{"path":"data/raw/talk.mp4","min_chapter":25}'

curl -s -X POST localhost:8000/v1/video/clip -H "$KEY" -H 'content-type: application/json' \
  -d '{"path":"data/raw/talk.mp4","start":42,"end":70,"aspect":"9:16"}'
```

## Kahan media rakh sakte hain

- repo ke andar (`data/raw/...`)
- `UAI_DATA_ROOT` ke andar
- ya `UAI_MEDIA_ROOTS=/renders:/mnt/media` — Modal volume / Docker volume ke liye

Baaki sab jagah se request **400** deta hai (path traversal block).

## Output kahan jata hai

`UAI_DATA_ROOT/video/` (default `data/video/`). Read-only filesystem par temp dir me.

## Verified (tests me)

Asli 6-second clip generate kar ke chalaya jata hai: 2s tone → 2s **silence** → 2s tone.
- probe: duration/resolution sahi
- silence detect: gap 1.5–2.5s me mila
- cut-silence: file ~2s chhoti hui, segments ≥2
- chapters: timestamps monotonic, 0:00 se shuru
- thumbnails: 3 alag frames
- loudnorm: naya file bana
- clip 9:16: output **1080×1920** verify
- SRT→VTT→SRT: cues aur timecodes sahi

Total: 15 tests, sab FFmpeg ke asli runs.
