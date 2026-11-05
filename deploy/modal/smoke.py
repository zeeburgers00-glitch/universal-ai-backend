"""Smoke-test a deployed Modal stack.

    python deploy/modal/smoke.py --api https://<workspace>--uai-api.modal.run

Modal names each web endpoint `<workspace>--<app-slug>-<function>-<hash>.modal.run`,
so worker URLs are derived from the API URL by swapping the function name. Use
`modal app list` / the deploy output if the derived URL 404s.

Every check prints PASS/FAIL; exit code is 1 if anything failed.
"""

from __future__ import annotations

import argparse
import sys

import httpx

WORKERS = ("voice", "media", "youtube", "channel", "agent", "automation", "rea")


def derive(api_url: str, name: str) -> str:
    """Derive a sibling endpoint URL from the API URL.

    Modal web endpoints look like:
        https://<workspace>--<app-slug>-<function>-<hash>.modal.run
    so swapping the function token is enough:
        https://ws--uai-api.modal.run        -> https://ws--uai-voice.modal.run
        https://ws--uai-api-abc123.modal.run -> https://ws--uai-voice-abc123.modal.run
    """

    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(api_url)
    labels = (parsed.hostname or "").split(".")
    if "--" not in labels[0]:
        return api_url.rstrip("/") + f"/{name}"

    workspace, slug = labels[0].split("--", 1)
    tokens = slug.split("-")
    if "api" in tokens:
        tokens[tokens.index("api")] = name
    else:
        tokens.append(name)
    labels[0] = f"{workspace}--" + "-".join(tokens)
    return urlunparse(parsed._replace(netloc=".".join(labels), path="", params="", query="", fragment=""))


def check(client: httpx.Client, label: str, url: str, api_key: str | None) -> bool:
    try:
        health = client.get(f"{url}/health", timeout=90)
    except Exception as exc:  # network, cold start timeout, DNS
        print(f"FAIL {label:<12} {url}/health -> {type(exc).__name__}")
        return False

    if health.status_code != 200:
        print(f"FAIL {label:<12} {url}/health -> HTTP {health.status_code}")
        return False

    detail = ""
    if api_key:
        probe = client.post(f"{url}/v1/{label}/jobs", timeout=60) if label == "media" else None
        if probe is not None:
            detail = f" | unauthenticated POST -> HTTP {probe.status_code}"
            if probe.status_code not in (401, 403, 422):
                print(f"WARN {label:<12} protected route answered {probe.status_code} without a key")
    print(f"PASS {label:<12} {url}{detail}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True, help="Deployed control-plane URL")
    parser.add_argument("--key", default=None, help="BACKEND_API_KEY value (to test auth)")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    failures = 0

    with httpx.Client(follow_redirects=True) as client:
        print(f"control plane: {api}")
        try:
            capabilities = client.get(f"{api}/v1/runtime/capabilities", timeout=120)
            print(f"     runtime capabilities -> HTTP {capabilities.status_code}")
        except Exception as exc:
            print(f"     runtime capabilities -> {type(exc).__name__}")

        if not check(client, "api", api, args.key):
            failures += 1

        for worker in WORKERS:
            if not check(client, worker, derive(api, worker), args.key):
                failures += 1

    print()
    if failures:
        print(f"{failures} endpoint(s) failed. Cold starts can take ~60s on the first hit — re-run.")
        return 1
    print("All endpoints healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
