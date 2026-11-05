"""The free tool belt: 65 tools, honest availability, real execution.

`prompts/free_toolbelt.json` is the catalogue (what exists, what it does, how to prove
it works). This module is the part that makes those entries callable:

* availability is *measured* — a binary on PATH, an importable module, an env var, a
  listening local service — never assumed from the catalogue
* a tool with no runner still appears in the list and fails with
  ``unavailable: <install command>`` instead of pretending
* runners validate their arguments and stay inside the repo / `UAI_DATA_ROOT`
* network tools are off unless ``UAI_TOOLS_ALLOW_NETWORK=1``, so a chat message cannot
  quietly turn into an outbound request

The catalogue is deliberately bigger than the runner set: JARVIS should tell the truth
about a tool it cannot use yet, and the list is the roadmap.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import shutil
import sqlite3 as sqlite_module
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import governance, video_tools

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "prompts" / "free_toolbelt.json"
CACHE_TTL = 30.0


class ToolError(ValueError):
    """Bad arguments or a failed run — the caller's problem (HTTP 422)."""


class ToolUnavailable(RuntimeError):
    """A dependency is genuinely missing — say which, don't improvise (HTTP 503)."""


def network_enabled() -> bool:
    return (os.getenv("UAI_TOOLS_ALLOW_NETWORK") or "").strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- #
# Bindings: what a tool id needs, and what it actually runs
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Binding:
    binaries: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    service: str = ""                     # local URL that must be listening
    params: dict[str, Any] = field(default_factory=dict)
    runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    note: str = ""

    @property
    def callable(self) -> bool:
        return self.runner is not None


def _cmd(binary: str) -> str | None:
    """Resolve a binary, including the bundled ffmpeg and venv-only pytest."""

    if binary in {"ffmpeg", "ffprobe"}:
        try:
            from videoengine.assembly import find_ffmpeg

            return find_ffmpeg()
        except Exception:  # noqa: BLE001 - report unavailable, never crash
            return None
    if binary == "imagemagick":
        return shutil.which("convert") or shutil.which("magick")
    if binary == "pytest":
        return sys.executable
    return shutil.which(binary)


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _probe_service(url: str, timeout: float = 0.25) -> bool:
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Runners — every one of these does real work, or fails loudly
# --------------------------------------------------------------------------- #

def _need(args: dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if args.get(key) in (None, "")]
    if missing:
        raise ToolError(f"missing argument(s): {', '.join(missing)}")


def _media_path(value: str) -> Path:
    return video_tools.resolve_input(str(value))


def _new_output(stem: str, suffix: str) -> Path:
    directory = video_tools.output_dir()
    safe = re.sub(r"[^\w.-]+", "_", stem)[:60] or "out"
    return directory / f"{safe}-{time.strftime('%H%M%S')}{suffix}"


def _ff(args: list[str], timeout: int = 600) -> str:
    from videoengine.assembly import find_ffmpeg

    binary = find_ffmpeg()
    completed = subprocess.run([binary, "-hide_banner", "-y", *args],
                               capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip().splitlines()[-3:]
        raise ToolError("ffmpeg failed: " + " | ".join(tail))
    return (completed.stderr or "")[-1500:]


def _run_ffmpeg(args: dict[str, Any]) -> dict[str, Any]:
    op = str(args.get("op") or "probe").strip().lower()
    if op == "probe":
        _need(args, "path")
        return {"probe": video_tools.probe_media(_media_path(args["path"]))}

    if op == "thumbnails":
        _need(args, "path")
        return video_tools.thumbnails(str(_media_path(args["path"])),
                                      count=int(args.get("count") or 3),
                                      width=int(args.get("width") or 1280))

    if op == "chapters":
        _need(args, "path")
        return video_tools.chapters(str(_media_path(args["path"])))

    if op == "cut_silence":
        _need(args, "path")
        return video_tools.cut_silence(str(_media_path(args["path"])))

    if op == "loudnorm":
        _need(args, "path")
        return video_tools.loudnorm(str(_media_path(args["path"])))

    source = _media_path(args["path"]) if args.get("path") else None
    if source is None:
        _need(args, "path")

    if op == "trim":
        _need(args, "start", "end")
        start, end = float(args["start"]), float(args["end"])
        if end <= start:
            raise ToolError("end must be greater than start")
        out = Path(args["out"]) if args.get("out") else _new_output(source.stem, source.suffix)
        _ff(["-ss", f"{start}", "-to", f"{end}", "-i", str(source), "-c", "copy", str(out)])
        return {"output": str(out), "start": start, "end": end, "size_bytes": out.stat().st_size}

    if op == "extract_audio":
        fmt = str(args.get("format") or "m4a").lstrip(".")
        if fmt not in {"m4a", "mp3", "wav", "ogg", "flac"}:
            raise ToolError("format must be one of m4a, mp3, wav, ogg, flac")
        out = Path(args["out"]) if args.get("out") else _new_output(source.stem, f".{fmt}")
        _ff(["-i", str(source), "-vn", str(out)])
        return {"output": str(out), "format": fmt, "size_bytes": out.stat().st_size}

    if op in {"scale", "convert"}:
        out = Path(args["out"]) if args.get("out") else _new_output(source.stem, ".mp4")
        filters = []
        if args.get("width"):
            filters.append(f"scale={int(args['width'])}:-2")
        _ff(["-i", str(source), *(["-vf", ",".join(filters)] if filters else []),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
             "-c:a", "aac", "-b:a", "128k", str(out)])
        return {"output": str(out), "size_bytes": out.stat().st_size}

    if op == "gif":
        _need(args, "start", "end")
        width = int(args.get("width") or 480)
        fps = int(args.get("fps") or 12)
        out = Path(args["out"]) if args.get("out") else _new_output(source.stem, ".gif")
        _ff(["-ss", str(float(args["start"])), "-to", str(float(args["end"])), "-i", str(source),
             "-vf", f"fps={fps},scale={width}:-1:flags=lanczos", str(out)])
        return {"output": str(out), "size_bytes": out.stat().st_size}

    raise ToolError(f"unknown ffmpeg op: {op} (probe, trim, extract_audio, thumbnails, "
                    f"chapters, cut_silence, loudnorm, scale, convert, gif)")


def _run_imagemagick(args: dict[str, Any]) -> dict[str, Any]:
    _need(args, "path")
    binary = _cmd("imagemagick")
    if not binary:  # pragma: no cover - availability check runs first
        raise ToolUnavailable("unavailable: apt-get install imagemagick")
    source = video_tools.resolve_input(str(args["path"]))
    suffix = Path(str(args.get("out") or "")).suffix or source.suffix or ".png"
    out = Path(args["out"]) if args.get("out") else _new_output(source.stem, suffix)
    command = [binary, str(source), "-strip"]
    if args.get("width"):
        command += ["-resize", f"{int(args['width'])}x"]
    if args.get("crop"):
        command += ["-gravity", "center", "-crop", str(args["crop"])]
    command.append(str(out))
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode != 0:
        raise ToolError(f"imagemagick failed: {(completed.stderr or '').strip()[:300]}")
    return {"output": str(out), "size_bytes": out.stat().st_size}


GIT_OPS = {"status", "log", "diff", "show", "branch"}


def _run_git(args: dict[str, Any]) -> dict[str, Any]:
    op = str(args.get("op") or "status").strip().lower()
    if op not in GIT_OPS:
        raise ToolError(
            f"git tool is read-only here: {op} is not allowed. Mutating git (commit, push, "
            "reset) needs a deliberate action, not a chat message."
        )
    limit = max(1, min(int(args.get("limit") or 10), 50))
    command = ["git"]
    if op == "status":
        command += ["status", "--porcelain"]
    elif op == "log":
        command += ["log", f"--max-count={limit}", "--pretty=%h %ad %s", "--date=short"]
    elif op == "diff":
        command += ["diff", "--stat"]
        if args.get("path"):
            command.append(str(args["path"]))
    elif op == "show":
        command += ["show", "--stat", "--oneline", "HEAD"]
    else:
        command += ["branch", "--show-current"]
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True,
                               timeout=60, check=False)
    if completed.returncode != 0:
        raise ToolError(f"git {op} failed: {(completed.stderr or '').strip()[:300]}")
    return {"op": op, "output": (completed.stdout or "").strip()[:4000]}


def _run_ripgrep(args: dict[str, Any]) -> dict[str, Any]:
    _need(args, "pattern")
    binary = _cmd("rg")
    if not binary:  # pragma: no cover
        raise ToolUnavailable("unavailable: apt-get install ripgrep")
    target = Path(str(args.get("path") or "app"))
    if not target.is_absolute():
        target = REPO_ROOT / target
    if not str(target.resolve()).startswith(str(REPO_ROOT)):
        raise ToolError("path must stay inside the repository")
    command = [binary, "--no-heading", "--line-number", "--color", "never",
               "--max-count", str(max(1, min(int(args.get("max") or 50), 200))),
               str(args["pattern"]), str(target)]
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True,
                               timeout=60, check=False)
    lines = [line for line in (completed.stdout or "").splitlines() if line][:200]
    return {"matches": len(lines), "lines": lines}


def _run_ast(args: dict[str, Any]) -> dict[str, Any]:
    import ast as ast_module

    _need(args, "path")
    target = Path(str(args["path"]))
    if not target.is_absolute():
        target = REPO_ROOT / target
    if not str(target.resolve()).startswith(str(REPO_ROOT)):
        raise ToolError("path must stay inside the repository")
    if not target.is_file():
        raise ToolError(f"not a file: {args['path']}")
    tree = ast_module.parse(target.read_text(encoding="utf-8", errors="replace"))
    op = str(args.get("op") or "symbols").lower()
    if op == "imports":
        names: list[str] = []
        for node in ast_module.walk(tree):
            if isinstance(node, ast_module.Import):
                names += [alias.name for alias in node.names]
            elif isinstance(node, ast_module.ImportFrom) and node.module:
                names.append(node.module)
        return {"file": str(target.relative_to(REPO_ROOT)), "imports": sorted(set(names))}
    if op != "symbols":
        raise ToolError("op must be 'symbols' or 'imports'")
    symbols = [
        {"kind": type(node).__name__.lower(), "name": node.name, "line": node.lineno}
        for node in tree.body
        if isinstance(node, (ast_module.FunctionDef, ast_module.AsyncFunctionDef, ast_module.ClassDef))
    ]
    return {"file": str(target.relative_to(REPO_ROOT)), "count": len(symbols),
            "symbols": symbols[:200]}


SAFE_SQL = re.compile(r"^\s*(select|with|pragma|explain)\b", re.IGNORECASE)


def _run_sqlite3(args: dict[str, Any]) -> dict[str, Any]:
    _need(args, "db", "query")
    if not SAFE_SQL.match(str(args["query"])):
        raise ToolError("only read-only SQL is allowed here (SELECT / WITH / PRAGMA / EXPLAIN)")
    path = Path(str(args["db"])).expanduser()
    if not path.is_absolute():
        path = (Path(os.getenv("UAI_DATA_ROOT") or "data") / path).resolve()
    if not path.exists():
        raise ToolError(f"database not found: {path}")
    limit = max(1, min(int(args.get("limit") or 100), 1000))
    connection = sqlite_module.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cursor = connection.execute(str(args["query"]))
        columns = [column[0] for column in (cursor.description or [])]
        rows = [dict(zip(columns, row)) for row in cursor.fetchmany(limit)]
    except sqlite_module.Error as exc:
        raise ToolError(f"SQL error: {exc}") from exc
    finally:
        connection.close()
    return {"db": str(path), "columns": columns, "row_count": len(rows), "rows": rows}


def _run_pytest(args: dict[str, Any]) -> dict[str, Any]:
    target = str(args.get("path") or "tests").strip()
    if ".." in target:
        raise ToolError("path must not escape the repository")
    command = [sys.executable, "-m", "pytest", target, "-q"]
    extra = args.get("args")
    if isinstance(extra, list):
        command += [str(item) for item in extra][:5]
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True,
                               timeout=int(args.get("timeout") or 600), check=False)
    output = (completed.stdout or "") + (completed.stderr or "")
    tail = "\n".join(output.strip().splitlines()[-6:])
    passed = re.search(r"(\d+) passed", output)
    failed = re.search(r"(\d+) failed", output)
    return {
        "target": target,
        "returncode": completed.returncode,
        "passed": int(passed.group(1)) if passed else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "tail": tail[-1200:],
    }


def _run_httpx(args: dict[str, Any]) -> dict[str, Any]:
    import httpx

    _need(args, "url")
    url = str(args["url"]).strip()
    if not url.startswith(("http://", "https://")):
        raise ToolError("url must start with http:// or https://")
    method = str(args.get("method") or "GET").upper()
    if method not in {"GET", "HEAD"}:
        raise ToolError("only GET/HEAD are allowed from the belt")
    limit = max(256, min(int(args.get("max_bytes") or 4000), 20000))
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.request(method, url)
    return {
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "bytes": len(response.content),
        "body": response.text[:limit],
    }


def _run_ollama(args: dict[str, Any]) -> dict[str, Any]:
    import httpx

    _need(args, "prompt")
    base = (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
    base = base.removesuffix("/v1")
    model_name = str(args.get("model") or os.getenv("OLLAMA_DEFAULT_MODEL") or "llama3.1")
    with httpx.Client(timeout=120.0) as client:
        response = client.post(f"{base}/api/generate",
                               json={"model": model_name, "prompt": str(args["prompt"]),
                                     "stream": False})
    if response.status_code >= 400:
        raise ToolError(f"ollama HTTP {response.status_code}: {response.text[:200]}")
    return {"model": model_name, "text": str(response.json().get("response") or "").strip()}


def _run_pillow(args: dict[str, Any]) -> dict[str, Any]:
    from PIL import Image

    _need(args, "path")
    source = video_tools.resolve_input(str(args["path"]))
    out = Path(args["out"]) if args.get("out") else _new_output(source.stem, ".png")
    with Image.open(source) as image:
        if args.get("width"):
            width = int(args["width"])
            height = max(1, round(image.height * width / image.width))
            image = image.resize((width, height))
        image.save(out)
        return {"output": str(out), "width": image.width, "height": image.height}


NETWORK_PARAMS = {"url": "string", "method": "string", "max_bytes": "integer"}
MEDIA_PARAMS = {"path": "string", "op": "string", "start": "number", "end": "number",
                "format": "string", "width": "integer", "count": "integer",
                "fps": "integer", "out": "string"}

BINDINGS: dict[str, Binding] = {
    # --- media ---------------------------------------------------------------
    "ffmpeg": Binding(binaries=("ffmpeg",), params=MEDIA_PARAMS, runner=_run_ffmpeg,
                      note="probe/trim/extract_audio/thumbnails/chapters/cut_silence/gif/scale"),
    "imagemagick": Binding(binaries=("imagemagick",),
                           params={"path": "string", "width": "integer", "crop": "string",
                                   "out": "string"},
                           runner=_run_imagemagick),
    "pillow": Binding(modules=("PIL",),
                      params={"path": "string", "width": "integer", "out": "string"},
                      runner=_run_pillow),
    # --- code / data ---------------------------------------------------------
    "git": Binding(binaries=("git",),
                   params={"op": "string", "path": "string", "limit": "integer"},
                   runner=_run_git, note="read-only: status/log/diff/show/branch"),
    "ripgrep": Binding(binaries=("rg",),
                       params={"pattern": "string", "path": "string", "max": "integer"},
                       runner=_run_ripgrep),
    "ast": Binding(modules=("ast",), params={"op": "string", "path": "string"},
                   runner=_run_ast),
    "pytest": Binding(binaries=("pytest",), modules=("pytest",),
                      params={"path": "string", "args": "array", "timeout": "integer"},
                      runner=_run_pytest),
    "sqlite3": Binding(modules=("sqlite3",),
                       params={"db": "string", "query": "string", "limit": "integer"},
                       runner=_run_sqlite3, note="read-only SQL, no writes"),
    # --- web / ai ------------------------------------------------------------
    "httpx": Binding(modules=("httpx",), params=NETWORK_PARAMS, runner=_run_httpx,
                     note="off unless UAI_TOOLS_ALLOW_NETWORK=1"),
    "ollama": Binding(service="http://127.0.0.1:11434",
                      params={"prompt": "string", "model": "string"}, runner=_run_ollama),
    # --- declared, not bound yet ---------------------------------------------
    # Everything else in the catalogue resolves its dependencies and reports honestly;
    # it just has no runner, so run() returns "unavailable" with the install command.
    "telegram": Binding(env=("TELEGRAM_BOT_TOKEN",), note="messaging needs an approval token"),
    "discord-webhook": Binding(env=("DISCORD_WEBHOOK_URL",), note="approval required"),
    "smtp": Binding(env=("SMTP_APP_PASSWORD",), note="approval required"),
    "ntfy": Binding(service="https://ntfy.sh", note="push; needs network"),
    "rclone": Binding(binaries=("rclone",), env=("RCLONE_CONFIG",), note="approval required"),
    "faster-whisper": Binding(modules=("faster_whisper",)),
    "edge-tts": Binding(modules=("edge_tts",)),
    "piper": Binding(modules=("piper",)),
    "pydub": Binding(modules=("pydub",), binaries=("ffmpeg",)),
    "pymupdf": Binding(modules=("fitz",)),
    "pdfplumber": Binding(modules=("pdfplumber",)),
    "reportlab": Binding(modules=("reportlab",)),
    "weasyprint": Binding(modules=("weasyprint",)),
    "python-docx": Binding(modules=("docx",)),
    "openpyxl": Binding(modules=("openpyxl",)),
    "python-pptx": Binding(modules=("pptx",)),
    "jinja2": Binding(modules=("jinja2",)),
    "pandoc": Binding(binaries=("pandoc",)),
    "libreoffice": Binding(binaries=("soffice",)),
    "ruff": Binding(binaries=("ruff",)),
    "mypy": Binding(modules=("mypy",)),
    "semgrep": Binding(binaries=("semgrep",)),
    "radon": Binding(modules=("radon",)),
    "pip-audit": Binding(modules=("piptools",)),
    "duckdb": Binding(modules=("duckdb",)),
    "polars": Binding(modules=("polars",)),
    "pandas": Binding(modules=("pandas",)),
    "matplotlib": Binding(modules=("matplotlib",)),
    "jsonschema": Binding(modules=("jsonschema",)),
    "csvkit": Binding(binaries=("csvstat",)),
    "llama-cpp-python": Binding(modules=("llama_cpp",)),
    "sentence-transformers": Binding(modules=("sentence_transformers",)),
    "sqlite-vec": Binding(modules=("sqlite_vec",)),
    "spacy": Binding(modules=("spacy",)),
    "langdetect": Binding(modules=("langdetect",)),
    "tiktoken": Binding(modules=("tiktoken",)),
    "playwright": Binding(modules=("playwright",)),
    "beautifulsoup4": Binding(modules=("bs4",)),
    "trafilatura": Binding(modules=("trafilatura",)),
    "feedparser": Binding(modules=("feedparser",)),
    "duckduckgo-search": Binding(modules=("duckduckgo_search",)),
    "wikipedia-api": Binding(modules=("wikipediaapi",)),
    "arxiv": Binding(modules=("arxiv",)),
    "open-meteo": Binding(service="https://api.open-meteo.com"),
    "nominatim": Binding(service="https://nominatim.openstreetmap.org"),
    "psutil": Binding(modules=("psutil",)),
    "watchfiles": Binding(modules=("watchfiles",)),
    "systemd-timer": Binding(binaries=("systemctl",)),
    "yt-dlp": Binding(binaries=("yt-dlp",)),
    "whisper-cpp": Binding(binaries=("whisper-cli",)),
    "espeak-ng": Binding(binaries=("espeak-ng",)),
    "sox": Binding(binaries=("sox",)),
    "pyjwt": Binding(modules=("jwt",)),
    "cryptography": Binding(modules=("cryptography",)),
    "argon2": Binding(modules=("argon2",)),
}


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Tool:
    id: str
    name: str
    category: str
    kind: str
    does: str
    install: str
    test: str
    offline: bool
    needs: tuple[str, ...]
    tos_caveat: str
    binding: Binding

    def to_dict(self, available: bool | None = None, detail: str = "") -> dict[str, Any]:
        payload = {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "kind": self.kind,
            "does": self.does,
            "install": self.install,
            "test": self.test,
            "offline": self.offline,
            "needs": list(self.needs),
            "tos_caveat": self.tos_caveat,
            "runnable": self.binding.callable,
            "params": self.binding.params,
        }
        if available is not None:
            payload["available"] = available
            payload["detail"] = detail
        return payload


_CACHE: dict[str, tuple[float, tuple[bool, str]]] = {}
_REGISTRY: dict[str, Tool] | None = None


def _load() -> dict[str, Tool]:
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY

    if not MANIFEST.exists():
        raise ToolUnavailable(f"unavailable: catalogue missing at {MANIFEST}")

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    registry: dict[str, Tool] = {}
    for entry in data.get("tools", []):
        binding = BINDINGS.get(str(entry["id"]), Binding())
        registry[str(entry["id"])] = Tool(
            id=str(entry["id"]),
            name=str(entry.get("name") or entry["id"]),
            category=str(entry.get("category") or "misc"),
            kind=str(entry.get("kind") or "python"),
            does=str(entry.get("does") or ""),
            install=str(entry.get("install") or ""),
            test=str(entry.get("test") or ""),
            offline=bool(entry.get("offline")),
            needs=tuple(entry.get("needs") or ()),
            tos_caveat=str(entry.get("tos_caveat") or ""),
            binding=binding,
        )
    _REGISTRY = registry
    return registry


def refresh() -> dict[str, int]:
    """Forget cached availability (after installing something)."""

    _CACHE.clear()
    return {"tools": len(_load()), "cached": 0}


def _evaluate(tool: Tool) -> tuple[bool, str]:
    """Measure, don't guess."""

    binding = tool.binding
    if binding.env:
        missing = [name for name in binding.env if not (os.getenv(name) or "").strip()]
        if missing:
            return False, f"unavailable: set {', '.join(missing)}"
    if binding.modules:
        missing = [name for name in binding.modules if not _has_module(name)]
        if missing:
            pip_name = {"PIL": "Pillow", "fitz": "PyMuPDF", "bs4": "beautifulsoup4",
                        "duckduckgo_search": "duckduckgo-search", "faster_whisper": "faster-whisper",
                        "sqlite_vec": "sqlite-vec", "llama_cpp": "llama-cpp-python",
                        "sentence_transformers": "sentence-transformers",
                        "edge_tts": "edge-tts", "wikipediaapi": "wikipedia-api",
                        "piptools": "pip-audit", "jwt": "PyJWT", "docx": "python-docx",
                        "pptx": "python-pptx", "argon2": "argon2-cffi"}.get(missing[0], missing[0])
            return False, f"unavailable: pip install {pip_name}"
    if binding.binaries:
        resolved = [(name, _cmd(name)) for name in binding.binaries]
        missing = [name for name, path in resolved if not path]
        if missing:
            hint = tool.install or f"install {', '.join(missing)}"
            return False, f"unavailable: {hint}"
        detail = ", ".join(f"{name}={path}" for name, path in resolved if path)
    else:
        detail = "python project"
    if binding.service:
        if not _probe_service(binding.service):
            return False, f"unavailable: nothing listening on {binding.service}"
        detail += f", service={binding.service}"
    if "network" in tool.needs and not network_enabled():
        return False, "unavailable: network tools are off (set UAI_TOOLS_ALLOW_NETWORK=1)"
    return True, detail


def availability(tool_id: str) -> tuple[bool, str]:
    tool = _load().get(tool_id)
    if tool is None:
        raise ToolError(f"unknown tool: {tool_id}", )
    now = time.time()
    cached = _CACHE.get(tool_id)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]
    verdict = _evaluate(tool)
    _CACHE[tool_id] = (now, verdict)
    return verdict


def get(tool_id: str) -> Tool:
    tool = _load().get((tool_id or "").strip())
    if tool is None:
        raise ToolError(f"unknown tool: {tool_id}")
    return tool


def list_tools(category: str | None = None, only_available: bool = False,
               runnable_only: bool = False) -> dict[str, Any]:
    _load()
    rows: list[dict[str, Any]] = []
    for tool in _load().values():
        if category and tool.category != category:
            continue
        if runnable_only and not tool.binding.callable:
            continue
        ok, detail = availability(tool.id)
        if only_available and not ok:
            continue
        rows.append(tool.to_dict(ok, detail))
    rows.sort(key=lambda row: (row["category"], not row["available"], row["id"]))
    available = sum(1 for row in rows if row["available"])
    return {
        "count": len(rows),
        "available": available,
        "runnable": sum(1 for row in rows if row["runnable"]),
        "network_enabled": network_enabled(),
        "categories": sorted({row["category"] for row in rows}),
        "tools": rows,
    }


# --------------------------------------------------------------------------- #
# BM25 search so a message can find the right tool
# --------------------------------------------------------------------------- #

# Words people actually type, mapped to the tools that answer them. BM25 alone misses
# these: "subtitles" never appears in ffmpeg's catalogue line, but it is what the caller
# means. Synonym hits add a bonus; they do not replace the text match.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "caption": ("ffmpeg", "faster-whisper"), "captions": ("ffmpeg", "faster-whisper"),
    "subtitle": ("ffmpeg", "faster-whisper"), "subtitles": ("ffmpeg", "faster-whisper"),
    "srt": ("ffmpeg", "faster-whisper"), "video": ("ffmpeg", "yt-dlp", "imagemagick"),
    "clip": ("ffmpeg",), "reel": ("ffmpeg",), "shorts": ("ffmpeg",),
    "audio": ("ffmpeg", "sox", "pydub", "espeak-ng"),
    "voice": ("piper", "edge-tts", "espeak-ng", "faster-whisper"),
    "speech": ("piper", "edge-tts", "faster-whisper"),
    "transcribe": ("faster-whisper", "whisper-cpp"), "transcript": ("faster-whisper",),
    "stt": ("faster-whisper", "whisper-cpp"), "tts": ("piper", "edge-tts", "espeak-ng"),
    "image": ("imagemagick", "pillow"), "photo": ("imagemagick", "pillow"),
    "thumbnail": ("ffmpeg", "imagemagick", "pillow"),
    "resize": ("imagemagick", "pillow", "ffmpeg"),
    "pdf": ("pymupdf", "reportlab", "weasyprint", "pandoc", "pdfplumber"),
    "word": ("python-docx", "pandoc", "libreoffice"),
    "docx": ("python-docx", "pandoc", "libreoffice"),
    "excel": ("openpyxl", "pandas", "duckdb"), "spreadsheet": ("openpyxl", "pandas"),
    "slides": ("python-pptx", "pandoc", "libreoffice"),
    "markdown": ("pandoc", "jinja2"), "template": ("jinja2",),
    "chart": ("matplotlib",), "graph": ("matplotlib",),
    "test": ("pytest",), "tests": ("pytest",),
    "lint": ("ruff", "mypy", "semgrep"), "typecheck": ("mypy",),
    "search": ("ripgrep", "duckduckgo-search"), "grep": ("ripgrep",),
    "code": ("ast", "ripgrep", "ruff", "semgrep"),
    "database": ("sqlite3", "duckdb"), "sql": ("sqlite3", "duckdb"),
    "csv": ("csvkit", "pandas", "duckdb", "polars"),
    "embedding": ("sentence-transformers", "sqlite-vec"),
    "embeddings": ("sentence-transformers", "sqlite-vec"),
    "vector": ("sqlite-vec", "sentence-transformers"),
    "llm": ("ollama", "llama-cpp-python"), "model": ("ollama", "llama-cpp-python"),
    "scrape": ("beautifulsoup4", "trafilatura", "playwright"),
    "html": ("beautifulsoup4", "trafilatura", "jinja2"),
    "rss": ("feedparser",), "news": ("feedparser", "trafilatura"),
    "weather": ("open-meteo",), "map": ("nominatim",), "location": ("nominatim",),
    "notify": ("ntfy", "telegram", "discord-webhook", "smtp"),
    "notification": ("ntfy", "telegram", "discord-webhook", "smtp"),
    "email": ("smtp",), "push": ("ntfy",), "backup": ("rclone",), "sync": ("rclone",),
    "metric": ("psutil",), "monitor": ("psutil", "watchfiles"), "watch": ("watchfiles",),
    "cron": ("systemd-timer",), "schedule": ("systemd-timer",),
    "download": ("yt-dlp", "httpx"), "http": ("httpx",), "api": ("httpx",),
    "token": ("tiktoken", "pyjwt"), "tokens": ("tiktoken",),
    "encrypt": ("cryptography",), "hash": ("cryptography", "argon2"),
    "language": ("langdetect", "spacy"), "entity": ("spacy",),
    "arxiv": ("arxiv",), "paper": ("arxiv",), "wikipedia": ("wikipedia-api",),
    "git": ("git",), "commit": ("git",), "diff": ("git",),
}


def _tokenise(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def search(query: str, limit: int = 8) -> dict[str, Any]:
    _load()
    docs = {tool.id: _tokenise(f"{tool.id} {tool.name} {tool.category} {tool.does} "
                               f"{' '.join(tool.needs)}") for tool in _load().values()}
    query_tokens = _tokenise(query or "")
    if not query_tokens:
        return {"query": query, "count": 0, "results": []}

    total = len(docs)
    average = sum(len(tokens) for tokens in docs.values()) / max(1, total)
    idf: dict[str, float] = {}
    for token in set(query_tokens):
        seen = sum(1 for tokens in docs.values() if token in tokens)
        idf[token] = math.log(1 + (total - seen + 0.5) / (seen + 0.5))

    k1, b = 1.5, 0.75
    scored: list[tuple[float, str]] = []
    alias_hits: dict[str, float] = {}
    for token in query_tokens:
        for tool_id in SYNONYMS.get(token, ()):
            alias_hits[tool_id] = alias_hits.get(tool_id, 0.0) + 2.5
    for tool_id, tokens in docs.items():
        length = len(tokens) or 1
        score = 0.0
        for token in query_tokens:
            frequency = tokens.count(token)
            if not frequency:
                continue
            score += idf[token] * (frequency * (k1 + 1)) / (
                frequency + k1 * (1 - b + b * length / max(1.0, average))
            )
        score += alias_hits.get(tool_id, 0.0)
        if score > 0:
            scored.append((score, tool_id))

    scored.sort(reverse=True)
    results = []
    for score, tool_id in scored[: max(1, min(limit, 25))]:
        tool = _load()[tool_id]
        ok, detail = availability(tool_id)
        results.append({**tool.to_dict(ok, detail), "score": round(score, 3)})
    return {"query": query, "count": len(results), "results": results}


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #

def run(tool_id: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    tool = get(tool_id)
    args = args or {}
    ok, detail = availability(tool.id)
    if not ok:
        # always the honest prefix, so callers can pattern-match on it
        raise ToolUnavailable(detail if detail.startswith("unavailable:") else f"unavailable: {detail}")

    runner = tool.binding.runner
    if runner is None:
        raise ToolUnavailable(
            f"unavailable: {tool.name} has no runner wired yet — {tool.install}"
        )

    started = time.perf_counter()
    try:
        result = runner(args)
    except (ToolError, ToolUnavailable):
        raise
    except FileNotFoundError as exc:
        raise ToolUnavailable(f"unavailable: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{tool.id} timed out after {exc.timeout}s") from exc
    except Exception as exc:  # noqa: BLE001 - surface it, keep the API alive
        governance.record("tool.failed", target=tool.id, outcome="error",
                          detail={"error": f"{type(exc).__name__}: {exc}"[:300]})
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    elapsed = round((time.perf_counter() - started) * 1000, 2)
    governance.record("tool.run", target=tool.id, outcome="ok",
                      detail={"ms": elapsed, "args": sorted(args)})
    return {"ok": True, "tool": tool.id, "name": tool.name,
            "elapsed_ms": elapsed, "result": result}


def verify(tool_id: str, timeout: int = 20) -> dict[str, Any]:
    """Run the catalogue's own proof command for one tool.

    This is the difference between "installed" and "works": the JSON says how to prove
    it, and this executes exactly that.
    """

    tool = get(tool_id)
    ok, detail = availability(tool.id)
    if not tool.test:
        raise ToolUnavailable(f"unavailable: no test command in the catalogue for {tool.id}")
    if not ok:
        raise ToolUnavailable(detail)

    command = tool.test
    if command.startswith("ffmpeg") and _cmd("ffmpeg"):
        command = command.replace("ffmpeg", f'"{_cmd("ffmpeg")}"', 1)
    if command.startswith("python "):
        command = command.replace("python", f'"{sys.executable}"', 1)
    started = time.perf_counter()
    completed = subprocess.run(command, shell=True, cwd=REPO_ROOT, capture_output=True,
                               text=True, timeout=timeout, check=False)
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    return {
        "tool": tool.id,
        "command": tool.test,
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "output": output[-800:],
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def summary() -> dict[str, Any]:
    listing = list_tools()
    by_category: dict[str, dict[str, int]] = {}
    for row in listing["tools"]:
        bucket = by_category.setdefault(row["category"], {"total": 0, "available": 0})
        bucket["total"] += 1
        bucket["available"] += 1 if row["available"] else 0
    ready = [row["id"] for row in listing["tools"] if row["available"] and row["runnable"]]
    measured = [row["id"] for row in listing["tools"] if row["available"]]
    return {
        "total": listing["count"],
        "available": listing["available"],
        "runnable": listing["runnable"],
        "ready": len(ready),
        "ready_ids": ready,
        "network_enabled": listing["network_enabled"],
        "by_category": by_category,
        "available_ids": measured,
        "missing": [{"id": row["id"], "detail": row["detail"]}
                    for row in listing["tools"] if not row["available"]][:20],
    }


# --------------------------------------------------------------------------- #
# Claude tool definitions
# --------------------------------------------------------------------------- #

_TYPE_MAP = {"string": "string", "integer": "integer", "number": "number", "array": "array"}


def claude_tools(only_available: bool = True) -> list[dict[str, Any]]:
    """Tool definitions for Anthropic's tool-use API — one per runnable tool."""

    definitions: list[dict[str, Any]] = []
    for tool in _load().values():
        if not tool.binding.callable or not tool.binding.params:
            continue
        ok, _ = availability(tool.id)
        if only_available and not ok:
            continue
        properties = {
            name: {"type": _TYPE_MAP.get(kind, "string")}
            for name, kind in tool.binding.params.items()
        }
        if "array" in [kind for kind in tool.binding.params.values()]:
            for name, kind in tool.binding.params.items():
                if kind == "array":
                    properties[name] = {"type": "array", "items": {"type": "string"}}
        definitions.append({
            "name": f"run_{tool.id.replace('-', '_').replace('.', '_')}",
            "description": f"[{tool.category}] {tool.does}",
            "input_schema": {"type": "object", "properties": properties,
                             "additionalProperties": False},
        })
    return definitions


def claude_name(tool_id: str) -> str:
    return f"run_{tool_id.replace('-', '_').replace('.', '_')}"


def run_from_claude(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Bridge Anthropic tool names back to the registry."""

    raw = (name or "").strip()
    if not raw.startswith("run_"):
        raise ToolError(f"unknown tool: {name}")
    candidate = raw[4:]
    known = _load()
    for tool_id in known:
        if claude_name(tool_id) == raw:
            return run(tool_id, args)
    raise ToolError(f"unknown tool: {name} (tried {candidate})")
