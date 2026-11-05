# Kaggle manual worker (optional)

Kaggle is a notebook-only, personal/non-commercial experiment worker. It is not an
always-on server and must not be used to serve customer or commercial production jobs.
The backend rejects Kaggle jobs with commercial_use=true.

## Setup

1. Clone this repository into a private Kaggle Notebook or upload the worker files.
2. Set Accelerator to GPU in Notebook settings and check the live quota displayed by
   Kaggle. Hardware and capacity can vary.
3. Add Kaggle Secrets: OPENAVATAR_API_URL, OPENAVATAR_WORKER_TOKEN, and optional
   OPENAVATAR_WORKER_ID.
4. On the backend, set OPENAVATAR_KAGGLE_ENABLED=true and restart the API.
5. Run this script manually once per job. It does not create a tunnel or loop forever:
   python workers/openavatar/kaggle/worker.py
6. The worker claims at most one job and exits. Run it again only while your account
   quota and session are available.

The provider's current quota/session limits are authoritative; do not hardcode a weekly
allowance into the application. Kaggle terms restrict the service to personal,
non-commercial use. Check the account's own terms before each use.

Official references:
- https://www.kaggle.com/docs/notebooks
- https://www.kaggle.com/docs/efficient-gpu-usage
- https://www.kaggle.com/terms
