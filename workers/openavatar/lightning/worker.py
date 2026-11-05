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
    import shutil
    from pathlib import Path
    capabilities = []
    if (Path(os.getenv("SADTALKER_ROOT", "")).expanduser() / "inference.py").is_file():
        capabilities.append("sadtalker")
    if ":" in os.getenv("OPENAVATAR_MUSETALK_ADAPTER", ""):
        capabilities.append("musetalk")
    if ":" in os.getenv("OPENAVATAR_OPENVOICE_ADAPTER", ""):
        capabilities.append("openvoice_v2")
    if Path(os.getenv("WHISPER_CPP_MODEL", "")).is_file():
        capabilities.append("whisper_cpp")
    try:
        import imageio_ffmpeg  # noqa: F401
        capabilities.append("ffmpeg")
    except Exception:
        if shutil.which(os.getenv("FFMPEG_BIN", "ffmpeg")):
            capabilities.append("ffmpeg")
    if not capabilities:
        raise RuntimeError("No compatible engine is installed; configure a model adapter or CPU tool first")
    print(run_once("lightning", capabilities))
if __name__ == "__main__":
    main()
