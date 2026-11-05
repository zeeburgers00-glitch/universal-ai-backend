"""Manual local CPU worker for transcription and FFmpeg assembly."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from workers.openavatar.worker_client import run_once
if __name__ == "__main__":
    print(run_once("local_cpu", ["openvoice_v2", "whisper_cpp", "ffmpeg"]))
