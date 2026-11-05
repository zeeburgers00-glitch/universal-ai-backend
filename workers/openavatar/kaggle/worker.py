"""Manual one-job Kaggle worker. Personal/non-commercial use only."""
from __future__ import annotations
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
def _load_kaggle_secrets() -> None:
    try:
        from kaggle_secrets import UserSecretsClient
        client = UserSecretsClient()
    except Exception as exc:
        raise RuntimeError("Run this inside Kaggle and add OPENAVATAR_API_URL and OPENAVATAR_WORKER_TOKEN as Kaggle Secrets") from exc
    for name in ("OPENAVATAR_API_URL", "OPENAVATAR_WORKER_TOKEN", "OPENAVATAR_WORKER_ID"):
        try:
            value = client.get_secret(name)
        except Exception:
            value = ""
        if value:
            os.environ[name] = value
    if not os.getenv("OPENAVATAR_API_URL") or not os.getenv("OPENAVATAR_WORKER_TOKEN"):
        raise RuntimeError("Missing OPENAVATAR_API_URL or OPENAVATAR_WORKER_TOKEN Kaggle Secret")
if __name__ == "__main__":
    _load_kaggle_secrets()
    if os.getenv("OPENAVATAR_KAGGLE_PERSONAL_USE_CONFIRMED", "").lower() != "true":
        raise RuntimeError("Set OPENAVATAR_KAGGLE_PERSONAL_USE_CONFIRMED=true only for personal, non-commercial jobs")
    from workers.openavatar.worker_client import run_once
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
        pass
    if not capabilities:
        raise RuntimeError("No compatible engine is installed; configure a model adapter or CPU tool first")
    print(run_once("kaggle", capabilities))
