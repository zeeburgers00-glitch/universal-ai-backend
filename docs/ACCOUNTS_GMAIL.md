# Connected accounts (Gmail), done with consent

The request was "use all my Gmail accounts automatically". This file is the honest version
of that sentence: **many accounts, each connected once by you, with the minimum permission
needed — and nothing that requires your password.**

## What this does

| Capability | Endpoint | Permission |
|---|---|---|
| Add an account | `POST /v1/accounts/oauth/start` → browser consent | `gmail.readonly` |
| Finish the flow | `GET /v1/accounts/oauth/callback?code=&state=` | — |
| List accounts | `GET /v1/accounts` | — |
| Read recent mail | `POST /v1/accounts/{id}/messages` | `gmail.readonly` |
| Digest unread | `POST /v1/accounts/{id}/digest` | `gmail.readonly` |
| Send a mail | `POST /v1/accounts/send` | `gmail.send` **+** `confirm=true` |
| Remove an account | `DELETE /v1/accounts/{id}` | — |

Up to 10 accounts side by side (`MAX_ACCOUNTS`), each with its own token, its own label and
its own scope set.

## What this will never do

| Refused | Why |
|---|---|
| Password-based login | Google does not permit it for apps, and it would mean holding your password |
| Bypassing 2FA | The OAuth consent screen *is* the supported path |
| Adding an account without its owner clicking "Allow" | Consent is the security model |
| Importing cookies/tokens from another app | Not our credentials to reuse |
| Bulk sending or auto-replying to strangers | Spam, and a fast way to lose the account |
| Returning any token through the API | Only the account metadata leaves the process |

If you ask for "all accounts auto", the closest legitimate thing is: connect each mailbox
once (30 seconds each), then let `/digest` run on a schedule you choose. That is what is
built.

## Setup, once

1. `console.cloud.google.com` → new project → **Enable the Gmail API**.
2. **OAuth consent screen** → External → add your own address as a test user.
3. **Credentials → Create credentials → OAuth client ID → Web application**, with the
   authorised redirect URI `http://127.0.0.1:8000/v1/accounts/oauth/callback`.
4. Provide the values (either way works):

```bash
export GOOGLE_CLIENT_ID="....apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="..."

# or at runtime, no restart:
curl -X POST localhost:8000/v1/vault/secrets -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"secrets":{"GOOGLE_CLIENT_ID":"...","GOOGLE_CLIENT_SECRET":"..."}}'
```

Until they exist, every account endpoint answers
`unavailable: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET ...`. No sample inbox.

## Connect an account

```bash
# 1. get the consent URL (read-only unless you plan to send)
curl -X POST localhost:8000/v1/accounts/oauth/start -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"label":"personal"}'
# → {"url":"https://accounts.google.com/o/oauth2/v2/auth?...","state":"..."}

# 2. open it, pick the mailbox, approve. Google redirects to the callback,
#    which stores the account and shows {"email": "...", "connected": true}

# 3. or paste the code manually
curl -X POST localhost:8000/v1/accounts/oauth/finish -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"code":"4/0A...","state":"..."}'
```

Then:

```bash
curl -X POST localhost:8000/v1/accounts/1/digest -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"query":"is:unread","limit":10}'
```

The digest is a faithful bullet list of subjects/senders. If a model is configured it
rewrites those bullets into prose — with an instruction not to invent names, numbers or
deadlines, and `"used_model": true` tells you which happened.

## Sending

Three independent keys must line up:

1. the account was connected **with** the send scope (`"allow_send": true` at start time),
2. the request carries `"confirm": true`,
3. if `UAI_REQUIRE_APPROVAL=1`, a valid approval token for `/v1/accounts/send`
   (`POST /v1/governance/approvals`).

Anything missing returns 422/403 with the reason. Every send is written to the audit log as
`account.send`.

## Token hygiene

- Tokens live in `UAI_DATA_ROOT/accounts.db`, mode `0600`, and are encrypted at rest with
  Fernet when `cryptography` is installed (`"tokens_encrypted": true` in
  `/v1/accounts/status`); otherwise the DB file permission is the only protection.
- `DELETE /v1/accounts/{id}` deletes the token rows and marks the account `revoked`. To
  remove the grant itself, also revoke the app at
  `myaccount.google.com/permissions`.
- Nothing token-shaped is ever logged or returned. The API surfaces labels and scopes only.

## Scheduling a daily digest

The job queue already exists (`/v1/jobs`). A cron-ish caller is enough:

```bash
# every morning at 8, from your own machine or a free VM
curl -X POST localhost:8000/v1/accounts/1/digest -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"query":"is:unread"}'
```

Note on Kaggle: session-based hosting means a scheduled digest is unreliable there
(sessions end, disks are wiped). Use a small always-on VM for anything recurring.
