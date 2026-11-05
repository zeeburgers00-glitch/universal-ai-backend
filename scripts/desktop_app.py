"""Open the UI as its own window instead of a browser tab.

Chrome, Edge and Brave can run without tabs or an address bar (``--app=URL``), which is the
cheapest way to make a web UI feel like a desktop app — no Electron, no installer, nothing
to sign. If none of those browsers is found, it falls back to the default browser and says
so, because pretending a window opened would be worse than a tab.

The server must already be running. This script deliberately does not start it: one thing
per script is easier to debug than a script that half-starts.

    python scripts/desktop_app.py                # open http://127.0.0.1:8000/editor
    python scripts/desktop_app.py --port 8100
    python scripts/desktop_app.py --wait         # start the click, then wait for /health
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

DEFAULT_PORT = 8000
DEFAULT_PATH = "/editor"


def build_url(host: str = "127.0.0.1", port: int = DEFAULT_PORT, path: str = DEFAULT_PATH) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return f"http://{host}:{int(port)}{path}"


def browser_candidates(platform: str | None = None) -> list[list[str]]:
    """App-window capable browsers, most likely first, per platform."""

    platform = platform or sys.platform
    if platform.startswith("win"):
        roots = [os.getenv("PROGRAMFILES", r"C:\Program Files"),
                 os.getenv("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 os.getenv("LOCALAPPDATA", "")]
        relative = [
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
        return [[os.path.join(root, rel)] for root in roots for rel in relative]
    if platform == "darwin":
        return [
            ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
            ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
            ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
        ]
    return [
        ["google-chrome"], ["chromium"], ["chromium-browser"],
        ["microsoft-edge"], ["brave-browser"],
    ]


def app_window_command(url: str, platform: str | None = None) -> list[str] | None:
    """A ready-to-run command, or None when no app-capable browser exists."""

    for candidate in browser_candidates(platform):
        binary = candidate[0]
        found = binary if os.path.isabs(binary) and os.path.exists(binary) else shutil.which(binary)
        if found:
            return [found, f"--app={url}", "--window-size=1440,920",
                    "--user-data-dir=" + os.path.join(
                        os.getenv("TEMP", os.getenv("TMPDIR", "/tmp")), "uai-desktop-profile")]
    return None


def healthy(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=timeout) as response:  # noqa: S310
            return response.status < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_for(url: str, seconds: float = 60.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if healthy(url):
            return True
        time.sleep(0.5)
    return False


def open_window(url: str, platform: str | None = None) -> str:
    """Returns what actually happened: 'app' or 'browser'."""

    command = app_window_command(url, platform)
    if command:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "app"
    webbrowser.open(url)
    return "browser"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open the backend UI as a desktop window")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--url", default="", help="full URL override")
    parser.add_argument("--wait", action="store_true", help="wait up to 60s for /health")
    parser.add_argument("--print-command", action="store_true", help="show the command only")
    args = parser.parse_args(argv)

    url = args.url or build_url(args.host, args.port, args.path)
    root = f"{args.host}:{args.port}" if not args.url else args.url.split("/editor")[0]

    if args.print_command:
        command = app_window_command(url)
        print(" ".join(command) if command else f"no app-capable browser; would open {url}")
        return 0

    if not healthy(f"http://{root}"):
        if args.wait:
            print(f"waiting for http://{root}/health …", flush=True)
            if not wait_for(f"http://{root}"):
                print("server never answered. Start it first:\n"
                      "  Windows:  scripts\\start_windows.bat\n"
                      "  any OS:   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000",
                      file=sys.stderr)
                return 1
        else:
            print(f"server is not running at http://{root}\n"
                  "Start it (scripts/start_windows.bat or uvicorn app.main:app), then run this again.\n"
                  "Tip: add --wait to have this script wait instead.", file=sys.stderr)
            return 1

    how = open_window(url)
    print(f"opened {url} as a {'window (app mode)' if how == 'app' else 'browser tab'}"
          f"{'' if how == 'app' else ' — Chrome/Edge not found for a borderless window'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
