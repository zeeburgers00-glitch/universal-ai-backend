# Supabase connection

Do projects hain, aur ye repo **`yqutpgefnykkqjifbgec`** (`zeeburgers00-glitch's Project`) se
baat karta hai — wahi jisme `uaib_*` tables hain. Doosra project
(`ankoqogbbclovfuurujw`, "ai-youtube-studio-autopilot") alag app ka hai; usme `pos_*`/`ros_*`
tables hain, use mat milao.

## Kya ho gaya (is session me, asli)

| Kaam | Halat |
|---|---|
| `uaib_custom_tools`, `uaib_execution_logs`, `uaib_runtime_secrets`, `uaib_client_campaign_*`, `uaib_base44_sync_runs` | pehle se maujood ✅ |
| `uaib_finance_entries` | **banaya** (finance ledger ise dhoond raha tha, 404 de raha tha) |
| `uaib_payout_requests` | **banaya** |
| `uaib_jarvis_facts` / `uaib_jarvis_lessons` / `uaib_jarvis_journal` | **banaye** — JARVIS ki memory ka durable copy |
| RLS | sab par **enabled, zero policies** = sirf service-role key |
| `anon`/`authenticated` | sab par **revoked** — leak hui anon key kuch nahi dekh sakti |
| Migration file | `supabase/migrations/20261105140000_uaib_core_tables.sql` (idempotent, fresh project me bhi chalega) |

## Backend ko jodna (2 line)

Dashboard → **Project Settings → API** → `Project URL` aur **`service_role`** key (anon key
kaam nahi karegi: RLS on hai, policies nahi hain).

```bash
# .env me (gitignored) — ya runtime par, restart ke bina:
SUPABASE_URL=https://yqutpgefnykkqjifbgec.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role key>

curl -X POST localhost:8000/v1/vault/secrets -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"secrets":{"SUPABASE_URL":"https://yqutpgefnykkqjifbgec.supabase.co","SUPABASE_SERVICE_ROLE_KEY":"..."}}'
```

Key mujhe chat me na bhejo — `.env` me daal do, backend khud padh lega.

## Check karna (jhoot nahi, naapa hua)

```bash
curl localhost:8000/v1/supabase/status -H "X-API-Key: $KEY"
# {"configured": true, "project_ref": "yqutpgefnykkqjifbgec", "ping": {"reachable": true, "latency_ms": 180}}

curl localhost:8000/v1/supabase/schema -H "X-API-Key: $KEY"
# {"present": [10 tables], "missing": [], "blocked": [], "complete": true}
```

`schema` har table ke liye PostgREST se **ek row maangta hai** — status code hi sach hai:
`200` = maujood, `404` = missing (migration chalao), `401/403` = key galat.

## Memory sync (do direction)

```bash
# local SQLite → Supabase (upsert, idempotent)
curl -X POST localhost:8000/v1/supabase/sync -H "X-API-Key: $KEY"
# → {"pushed": {"facts": 12, "lessons": 4, "journal": 30}, "errors": []}

# Supabase → local (naya PC, ya Kaggle session wipe ke baad)
curl -X POST localhost:8000/v1/supabase/pull -H "X-API-Key: $KEY"
# → {"restored": 12, "skipped": 0}
```

Design decision: **local SQLite hi source of truth hai** chat ke liye (ek turn network par
nahi rukna chahiye), Supabase durable copy hai. Isliye sync manual/explicit hai, aur har
response me `pushed`/`errors` asli count batata hai — "sync ho gaya" ka dawa nahi.

## Kya nahi kiya (jaan-boojh kar)

- **Anon key support nahi** — RLS on + zero policies, to anon se kuch bhi nahi khulega; galat
  key dene se aadha-adhoora kaam karna bura hai.
- **Schema auto-create nahi** — PostgREST DDL nahi kar sakta. Isliye migration file hai aur
  `schema` endpoint missing tables batata hai. (Is session me maine connector se create kar
  diye, tumhare project par.)
- **Service key repo me nahi** — `.env` gitignored hai; `GET /v1/supabase/status` key ko
  mask karke dikhata hai (`abc123…wxyz`), poora kabhi nahi.

## Purane modules

Ye repo pehle se `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` env use karta tha
(`app/supabase_store.py`, `app/finance_ledger.py`, `app/autopilot_store.py`,
`app/client_campaign.py`, `app/vault.py`). Is session me unhi variables par ek
verification + sync layer add hui hai — purana code chhua nahi gaya.
