from pathlib import Path

import pytest

from videoengine import assembly


def test_video_scene_regenerates_timestamps_and_uses_constant_frame_rate(monkeypatch, tmp_path):
    captured = {}

    def fake_run_ffmpeg(args, *, ffmpeg, timeout=3600):
        captured["args"] = args
        return ""

    monkeypatch.setattr(assembly, "run_ffmpeg", fake_run_ffmpeg)
    output = tmp_path / "scene.mp4"
    assembly.render_scene(
        out=output,
        duration=3,
        width=1280,
        height=720,
        fps=30,
        ffmpeg="ffmpeg",
        video=tmp_path / "stock.mp4",
        ken_burns=False,
    )

    args = captured["args"]
    assert args[:5] == ["-y", "-fflags", "+genpts", "-stream_loop", "-1"]
    assert "fps=30" in args[args.index("-vf") + 1]
    assert args[args.index("-fps_mode") + 1] == "cfr"
    assert args[args.index("-avoid_negative_ts") + 1] == "make_zero"


def test_ffmpeg_failure_includes_error_line_and_exit_code(monkeypatch):
    class Result:
        returncode = 1
        stderr = "Input #0, mov,mp4\n[Parsed_scale] Error while configuring filter\nframe=0 fps=0"

    monkeypatch.setattr(
        assembly.subprocess,
        "run",
        lambda *args, **kwargs: Result(),
    )

    with pytest.raises(RuntimeError, match="exit 1") as error:
        assembly.run_ffmpeg(["-i", "input.mp4", "output.mp4"], ffmpeg="ffmpeg")

    assert "Error while configuring filter" in str(error.value)
