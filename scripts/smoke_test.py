#!/usr/bin/env python3
"""Smoke-test a deployed Universal AI Backend without dispatching side-effecting jobs."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

CHECKS = (
    ("/health", "health"),
    ("/v1/runtime/capabilities", "runtime capabilities"),
    ("/v1/catalog/stats", "catalog statistics"),
    ("/v1/tools?limit=1", "tool catalog"),
    ("/v1/workflows", "workflow catalog"),
    ("/v1/agents", "agent catalog"),
    ("/v1/providers", "provider status"),
    ("/v1/workers/status", "worker configuration status"),
)


def request_json(base_url: str, path: str, api_key: str, timeout: float) -> tuple[int, Any]:
    headers = {"Accept": "application/json", "User-Agent": "universal-ai-backend-smoke-test/1.0"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(base_url.rstrip("/") + path, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("response exceeded 2 MB smoke-test limit")
        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type.lower():
            raise ValueError(f"expected JSON content type, got {content_type or 'missing'}")
        return response.status, json.loads(body.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", nargs="?", default=os.getenv("BACKEND_BASE_URL", ""),
                        help="deployed API base URL (or set BACKEND_BASE_URL)")
    parser.add_argument("--api-key", default=os.getenv("BACKEND_API_KEY", ""),
                        help="optional server API key; never place it in a frontend bundle")
    parser.add_argument("--timeout", type=float, default=12.0, help="per-request timeout in seconds")
    parser.add_argument("--json", action="store_true", help="print a machine-readable result summary")
    args = parser.parse_args()

    if not args.base_url:
        parser.error("provide base_url or set BACKEND_BASE_URL")
    if not args.base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        parser.error("use HTTPS for remote hosts; HTTP is only allowed for localhost development")
    if args.timeout <= 0 or args.timeout > 120:
        parser.error("--timeout must be between 0 and 120 seconds")

    results: list[dict[str, Any]] = []
    failures = 0
    for path, label in CHECKS:
        started = time.monotonic()
        try:
            status, data = request_json(args.base_url, path, args.api_key, args.timeout)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            item = {"check": label, "path": path, "ok": 200 <= status < 300, "status": status,
                    "elapsed_ms": elapsed_ms}
            if path == "/health" and isinstance(data, dict):
                item["health"] = data.get("status", data.get("ok", "responded"))
            if path == "/v1/catalog/stats" and isinstance(data, dict):
                item["catalog_tool_count"] = data.get("total_tools")
            if not item["ok"]:
                failures += 1
                item["error"] = "non-success HTTP status"
        except urllib.error.HTTPError as exc:
            failures += 1
            item = {"check": label, "path": path, "ok": False, "status": exc.code,
                    "error": "HTTP error"}
        except (urllib.error.URLError, TimeoutError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            failures += 1
            item = {"check": label, "path": path, "ok": False,
                    "error": type(exc).__name__, "message": str(exc)[:240]}
        results.append(item)

    summary = {"base_url": args.base_url.rstrip("/"), "passed": len(results) - failures,
               "failed": failures, "checks": results}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Smoke test: {summary['passed']}/{len(results)} checks passed for {summary['base_url']}")
        for item in results:
            state = "PASS" if item["ok"] else "FAIL"
            extra = f" ({item.get('status', item.get('error', ''))})"
            print(f"{state}: {item['check']} {item['path']}{extra}")
        if failures:
            print("A passing GET smoke test does not prove provider credentials, worker queues or external API writes work.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
