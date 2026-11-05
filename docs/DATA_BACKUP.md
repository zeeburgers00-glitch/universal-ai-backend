# Backup / restore — sab kuch ek tar.gz me

Poore system ka durable data `UAI_DATA_ROOT` ke andar hai (SQLite job DB, quota state,
registry caches, media outputs). Isliye backup = ek archive, restore = safe extraction.

| Endpoint | Kaam |
|---|---|
| `GET /v1/data/manifest` | data dir me kya hai (files, size, suffix breakdown) |
| `POST /v1/data/backup` | `{include_media: false, label: "nightly"}` → archive banao |
| `GET /v1/data/backups` | kitne backups hain |
| `POST /v1/data/restore` | `{name, snapshot_first: true}` |
| `GET /v1/data/verify?name=…` | archive khol kar members check (kuch likhta nahi) |
| `GET /v1/data/download?name=…` | file download (gzip) |

```bash
# raat ka backup
curl -s -X POST localhost:8000/v1/data/backup -H "X-API-Key: $KEY" \
  -H 'content-type: application/json' -d '{"label":"nightly"}'
# → {"name":"20261105-021500-nightly.tar.gz","bytes":184320,"files":37,"sha256":"…"}
```

## Safety

- Default me **media files skip** hoti hain (video bhaari hota hai); `include_media: true` se aata hai.
- Restore se pehle **current state ka snapshot** khud ban jata hai (`pre-restore`) — galat
  restore ho jaye to wapas ja sakte hain.
- Archives me `../` ya absolute paths ho to **restore refuse** ho jata hai (test me verified).
- Sirf 10 latest backups rakhe jate hain, purane khud delete.

## Cron

```bash
# har roz 2 baje
0 2 * * * curl -s -X POST localhost:8000/v1/data/backup -H "X-API-Key: $KEY" \
  -H 'content-type: application/json' -d '{"label":"cron"}' >/dev/null
```

## Sach

- Backup **usi disk** par banta hai. Off-site chahiye to archive ko `rclone`/S3 par
  bhejna hoga — wo credential mangta hai, isliye default me nahi hai.
- SQLite WAL mode me live DB ka copy thoda inconsistent ho sakta hai; restore ke baad
  app restart karna best practice hai (`jobs.db-wal` bhi archive me hota hai).
