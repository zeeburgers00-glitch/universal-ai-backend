"""Manual local CPU worker for transcription and FFmpeg assembly."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from workers.openavatar.worker_client import run_once
if __name__ == "__main__":
    import os
    import shutil
    capabilities = []
    if ":" in os.getenv("OPENAVATAR_OPENVOICE_ADAPTER", ""):
        capabilities.append("openvoice_v2")
    if os.getenv("WHISPER_CPP_MODEL") and Path(os.getenv("WHISPER_CPP_MODEL", "")).is_file():
        capabilities.append("whisper_cpp")
    try:
        import imageio_ffmpeg  # noqa: F401
        capabilities.append("ffmpeg")
    except Exception:
        if shutil.which(os.getenv("FFMPEG_BIN", "ffmpeg")):
            capabilities.append("ffmpeg")
    if not capabilities:
        raise RuntimeError("Install whisper.cpp, FFmpeg, or a reviewed OpenVoice adapter before starting this worker")
    print(run_once("local_cpu", capabilities))
