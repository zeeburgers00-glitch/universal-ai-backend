# Lightning AI manual worker (optional)

Lightning AI documentation currently describes free account creation without a card,
phone verification, one free CPU Studio, and introductory GPU credits/hours. Country
availability and the amount of free GPU capacity can vary. The backend adapter is
disabled by default.

## Strict no-card activation

1. Create an account only if signup is available in your country.
2. Do not add a payment card and do not purchase credits or enable paid top-ups.
3. Verify the current free GPU allowance in your account before running anything.
4. Start a free Studio manually and attach a GPU only if it is visibly covered by the
   free allowance. Do not automate instance creation, paid upgrades, or credit purchase.
5. Set these backend environment flags only after checking account eligibility:
   - OPENAVATAR_LIGHTNING_ENABLED=true
   - OPENAVATAR_LIGHTNING_NO_CARD_CONFIRMED=true
6. Set these worker environment flags in the Studio:
   - OPENAVATAR_API_URL
   - OPENAVATAR_WORKER_TOKEN
   - OPENAVATAR_WORKER_ID
   - OPENAVATAR_LIGHTNING_FREE_CREDITS_ONLY=true
   - OPENAVATAR_LIGHTNING_NO_CARD_CONFIRMED=true
7. Run one job manually:
   python workers/openavatar/lightning/worker.py

This script claims at most one job. It does not start/stop cloud instances, buy credits,
or call a payment API. If the free allocation is exhausted, stop; there is no paid
fallback. The worker must remain disabled if your account requires adding a card or
cannot clearly show that the selected GPU is free.

Official references:
- https://lightning.ai/docs/platform/build/ai-studio
- https://lightning.ai/pricing
