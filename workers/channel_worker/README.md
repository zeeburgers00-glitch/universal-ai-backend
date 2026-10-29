# Channel connector worker

The first executable channel worker supports approval-gated messages via Telegram Bot API, Discord Bot API, Slack chat.postMessage, and WhatsApp Business Cloud API approved templates. Other connectors in `catalog/channels.json` remain manifests until their own OAuth, refresh-token storage, platform review, scoped actions, and tests are implemented.

## Required environment

Set `CHANNEL_WORKER_API_KEY`, plus per-connector `*_CONNECTION_ID`, token, and `*_ALLOWED_TARGET_IDS`. Target allowlists are intentionally server-side so an API caller cannot choose an arbitrary destination. For WhatsApp also configure `WHATSAPP_PHONE_NUMBER_ID`, `META_GRAPH_API_VERSION`, and approved template names in your operational policy.

Run on a trusted host and expose it only over HTTPS/private networking. Configure the matching `CHANNEL_WORKER_URL` and `CHANNEL_WORKER_API_KEY` on Vercel. The worker never accepts a caller-supplied API endpoint or bot token.

Messaging is side-effectful; the API requires `user_approved=true`, and the worker enforces that again. Automated bulk messaging, spam and artificial engagement are not supported.
