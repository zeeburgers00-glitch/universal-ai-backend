"""Observability and protection with no external services.

Two things every deploy needs and neither of which should require an account:

* ``/metrics`` — Prometheus text format, generated from an in-process counter.
* rate limiting — a per-client sliding window, in memory, off by default at a
  generous ceiling so a normal integration never trips it.

Deliberately dependency-free: no statsd agent, no Redis, no sidecar.
"""

from __future__ import annotations

import os
import threading
import time
from collections import Counter, defaultdict, deque
from typing import Any

STARTED_AT = time.time()

_lock = threading.Lock()
_requests: Counter[tuple[str, str, str]] = Counter()          # (method, group, status)
_latency_sum: dict[str, float] = defaultdict(float)
_latency_count: Counter[str] = Counter()
_latency_buckets: Counter[tuple[str, str]] = Counter()        # (group, bucket)
_inflight = 0
_peak_inflight = 0

BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_windows: dict[str, deque[float]] = defaultdict(deque)


def path_group(path: str) -> str:
    """Collapse ids so metric cardinality stays sane: /v1/jobs/abc123 -> /v1/jobs/:id."""

    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return "/"
    kept = segments[:2]
    if len(segments) > 2:
        kept.append(":id" if _looks_like_id(segments[2]) else segments[2])
    return "/" + "/".join(kept)


def _looks_like_id(segment: str) -> bool:
    if len(segment) >= 16:
        return True
    return segment.isdigit() or (segment.count("-") >= 2 and len(segment) > 8) or (
        all(char in "0123456789abcdef" for char in segment.lower()) and len(segment) >= 8
    )


def rate_limit_per_minute() -> int:
    raw = (os.getenv("UAI_RATE_LIMIT") or "600").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 600


def check_rate_limit(client_id: str, now: float | None = None) -> tuple[bool, int, float]:
    """Returns (allowed, remaining, retry_after_seconds)."""

    limit = rate_limit_per_minute()
    if limit <= 0:
        return True, -1, 0.0

    moment = now if now is not None else time.time()
    window = _windows[client_id]
    with _lock:
        while window and moment - window[0] > 60.0:
            window.popleft()
        if len(window) >= limit:
            retry_after = max(0.0, 60.0 - (moment - window[0]))
            return False, 0, round(retry_after, 1)
        window.append(moment)
        remaining = limit - len(window)
    # Bound memory: forget idle clients.
    if len(_windows) > 4096:
        with _lock:
            for key in [k for k, v in _windows.items() if not v][:1024]:
                _windows.pop(key, None)
    return True, remaining, 0.0


def observe(method: str, path: str, status: int, elapsed: float) -> None:
    group = path_group(path)
    bucket = next((str(candidate) for candidate in BUCKETS if elapsed <= candidate), "+Inf")
    with _lock:
        _requests[(method, group, f"{status // 100}xx")] += 1
        _latency_sum[group] += elapsed
        _latency_count[group] += 1
        _latency_buckets[(group, bucket)] += 1


def track_inflight(delta: int) -> None:
    global _inflight, _peak_inflight
    with _lock:
        _inflight += delta
        _peak_inflight = max(_peak_inflight, _inflight)


def snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "uptime_seconds": round(time.time() - STARTED_AT, 1),
            "requests": {" ".join(key): value for key, value in _requests.items()},
            "avg_latency_ms": {
                group: round(1000 * _latency_sum[group] / max(1, _latency_count[group]), 2)
                for group in _latency_count
            },
            "inflight": _inflight,
            "peak_inflight": _peak_inflight,
            "rate_limit_per_minute": rate_limit_per_minute(),
        }


def prometheus() -> str:
    """Prometheus text exposition format (version 0.0.4)."""

    lines = [
        "# HELP uai_up 1 when the process is serving",
        "# TYPE uai_up gauge",
        "uai_up 1",
        "# HELP uai_uptime_seconds Process uptime",
        "# TYPE uai_uptime_seconds gauge",
        f"uai_uptime_seconds {round(time.time() - STARTED_AT, 1)}",
        "# HELP uai_requests_total Requests by method, route group and status class",
        "# TYPE uai_requests_total counter",
    ]
    with _lock:
        for (method, group, status_class), value in sorted(_requests.items()):
            lines.append(f'uai_requests_total{{method="{method}",route="{group}",status="{status_class}"}} {value}')

        lines += [
            "# HELP uai_request_duration_seconds_sum Total seconds spent per route group",
            "# TYPE uai_request_duration_seconds_sum counter",
        ]
        for group, total in sorted(_latency_sum.items()):
            lines.append(f'uai_request_duration_seconds_sum{{route="{group}"}} {round(total, 6)}')
        lines += [
            "# HELP uai_request_duration_seconds_count Number of timed requests per route group",
            "# TYPE uai_request_duration_seconds_count counter",
        ]
        for group, count in sorted(_latency_count.items()):
            lines.append(f'uai_request_duration_seconds_count{{route="{group}"}} {count}')
        lines += [
            "# HELP uai_request_duration_seconds_bucket Latency buckets",
            "# TYPE uai_request_duration_seconds_bucket counter",
        ]
        for (group, bucket), count in sorted(_latency_buckets.items()):
            lines.append(f'uai_request_duration_seconds_bucket{{route="{group}",le="{bucket}"}} {count}')

        lines += [
            "# HELP uai_inflight_requests Requests being handled right now",
            "# TYPE uai_inflight_requests gauge",
            f"uai_inflight_requests {_inflight}",
        ]
    return "\n".join(lines) + "\n"


def reset() -> None:
    """Testing helper."""

    global _inflight, _peak_inflight
    with _lock:
        _requests.clear()
        _latency_sum.clear()
        _latency_count.clear()
        _latency_buckets.clear()
        _windows.clear()
        _inflight = 0
        _peak_inflight = 0
