"""Manual, single-job Lightning AI worker; never starts or purchases compute."""
from __future__ import annotations
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from workers.openavatar.worker_client import run_once
def main() -> None:
    if os.getenv("OPENAVATAR_LIGHTNING_FREE_CREDITS_ONLY", "").lower() != "true":
        raise RuntimeError("Set OPENAVATAR_LIGHTNING_FREE_CREDITS_ONLY=true only after confirming your account has no payment card and the job is covered by free credits")
    if os.getenv("OPENAVATAR_LIGHTNING_NO_CARD_CONFIRMED", "").lower() != "true":
        raise RuntimeError("Lightning worker disabled until no-card account eligibility is confirmed")
    print(run_once("lightning", ["sadtalker", "musetalk", "openvoice_v2", "whisper_cpp", "ffmpeg"]))
if __name__ == "__main__":
    main()
