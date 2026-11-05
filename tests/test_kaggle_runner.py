"""Kaggle batch jobs: honest about what an API token can and cannot do."""

from __future__ import annotations

import json

import pytest

from app import kaggle_runner as kr


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path / "no-such-dir"))
    for name in ("KAGGLE_USERNAME", "KAGGLE_KEY"):
        monkeypatch.delenv(name, raising=False)
    kr.init_db()
    yield tmp_path


@pytest.fixture()
def fake_cli(monkeypatch):
    """Pretend the CLI exists and record every call."""

    calls: list[list[str]] = []

    def fake_run(args, timeout=180):
        calls.append(args)
        if args[:2] == ["kernels", "push"]:
            return {"command": "kaggle " + " ".join(args), "returncode": 0,
                    "output": "Kernel version 1 successfully pushed"}
        if args[:2] == ["kernels", "status"]:
            return {"command": "kaggle " + " ".join(args), "returncode": 0,
                    "output": "uai/demo has status KernelWorkerStatus.COMPLETE"}
        if args[:2] == ["kernels", "output"]:
            return {"command": "kaggle " + " ".join(args), "returncode": 0, "output": "ok"}
        return {"command": "kaggle", "returncode": 1, "output": "unexpected"}

    monkeypatch.setattr(kr, "_cli", lambda: ["kaggle"])
    monkeypatch.setattr(kr, "_run_cli", fake_run)
    monkeypatch.setenv("KAGGLE_USERNAME", "ali")
    monkeypatch.setenv("KAGGLE_KEY", "secret-key")
    return calls


# --- the honest status ---------------------------------------------------------

def test_status_says_the_cli_is_missing_not_that_it_works():
    state = kr.status()
    assert state["cli"] is False
    assert state["cli_detail"].startswith("unavailable: pip install kaggle")
    assert state["credentials"] is False


def test_status_repeats_that_there_is_no_live_endpoint():
    limits = kr.status()["limits"]
    assert limits["inbound_ports"] is False
    assert limits["live_http_while_running"] is False
    assert "batch" in kr.status()["honesty"]


# --- credentials ---------------------------------------------------------------

def test_submit_without_credentials_is_unavailable(monkeypatch):
    monkeypatch.setattr(kr, "_cli", lambda: ["kaggle"])
    with pytest.raises(kr.KaggleUnavailable) as caught:
        kr.submit("toolbelt", {"tool": "ffmpeg", "args": {"op": "probe", "path": "x.mp4"}})
    assert "KAGGLE_USERNAME" in str(caught.value)


def test_missing_cli_is_unavailable_not_a_fake_success():
    with pytest.raises(kr.KaggleUnavailable) as caught:
        kr._cli()
    assert str(caught.value).startswith("unavailable: pip install kaggle")


# --- notebooks -----------------------------------------------------------------

def test_render_notebook_has_setup_and_marker():
    notebook = kr.render_notebook("toolbelt", {"tool": "git", "args": {"op": "status"}})
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) == 3
    body = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
    assert '"install"' in body and "requirements.txt" in body
    assert "universal-ai-backend.git" in body
    assert kr.RESULT_MARKER in body
    assert "toolbelt.run('git'" in body


def test_render_notebook_transcribe_uses_the_file_it_was_given():
    notebook = kr.render_notebook("transcribe", {"input_path": "/kaggle/input/x/talk.mp4"})
    body = "".join(notebook["cells"][2]["source"])
    assert "faster-whisper" in body
    assert "/kaggle/input/x/talk.mp4" in body
    assert ".srt" in body


def test_unknown_template_is_rejected():
    with pytest.raises(kr.KaggleError):
        kr.render_notebook("mine-bitcoin", {})


def test_unknown_template_is_a_422_even_without_credentials():
    """A typo must not masquerade as a credentials problem."""

    with pytest.raises(kr.KaggleError):
        kr.submit("mine-bitcoin", {})


# --- submit / poll / fetch -----------------------------------------------------

def test_submit_writes_the_metadata_kaggle_requires(fake_cli, isolated):
    job = kr.submit("toolbelt", {"tool": "ffmpeg", "args": {"op": "probe", "path": "x.mp4"}},
                    dataset_sources=["ali/videos"])
    assert job["status"] == "queued"
    assert job["ref"] == "ali/" + job["ref"].split("/")[1]
    assert job["gpu"] is False

    job_dir = isolated / "kaggle" / "jobs" / job["ref"].split("/")[1]
    metadata = json.loads((job_dir / "kernel-metadata.json").read_text())
    assert metadata["id"] == job["ref"]
    assert metadata["code_file"] == "job.ipynb"
    assert metadata["dataset_sources"] == ["ali/videos"]
    assert metadata["enable_internet"] is True
    assert fake_cli[0][:2] == ["kernels", "push"]


def test_gpu_templates_default_to_gpu(fake_cli):
    job = kr.submit("transcribe", {"input_path": "x.mp4"})
    assert job["gpu"] is True


@pytest.mark.parametrize("line,expected", [
    ("has status KernelWorkerStatus.RUNNING", "running"),
    ("has status KernelWorkerStatus.COMPLETE", "complete"),
    ("has status KernelWorkerStatus.QUEUED", "queued"),
    ("has status KernelWorkerStatus.ERROR", "error"),
    ("something unexpected", "unknown"),
])
def test_status_parsing(line, expected):
    assert kr._parse_status(line) == expected


def test_refresh_updates_the_job(fake_cli):
    job = kr.submit("toolbelt", {"tool": "git", "args": {"op": "status"}})
    polled = kr.refresh(job["id"])
    assert polled["status"] == "complete"
    assert kr.list_jobs(5)["jobs"][0]["status"] == "complete"


def test_output_refuses_an_incomplete_job(fake_cli, monkeypatch):
    job = kr.submit("toolbelt", {"tool": "git", "args": {"op": "status"}})
    with pytest.raises(kr.KaggleError) as caught:
        kr.fetch_output(job["id"])
    assert "not complete" in str(caught.value)


def test_output_parses_the_result_marker(fake_cli, isolated):
    job = kr.submit("toolbelt", {"tool": "git", "args": {"op": "status"}})
    kr.refresh(job["id"])

    job_dir = isolated / "kaggle" / "jobs" / job["ref"].split("/")[1]
    out = job_dir / "output"
    out.mkdir(parents=True, exist_ok=True)
    payload = {"ok": True, "run": {"tool": "git", "result": {"op": "status", "output": ""}}}
    (out / "job.ipynb").write_text(
        "notebook output\n" + kr.RESULT_MARKER + "\n" + json.dumps(payload))

    fetched = kr.fetch_output(job["id"])
    assert fetched["files"] == ["job.ipynb"]
    assert fetched["job_result"]["ok"] is True
    assert fetched["job_result"]["run"]["tool"] == "git"


def test_estimate_states_the_real_limits(fake_cli):
    gpu = kr.estimate("transcribe")
    assert gpu["gpu"] is True
    assert gpu["session_limit_hours"] == 9
    assert gpu["gpu_weekly_hours"] == 30
    assert gpu["inbound_port"] is False
