#!/usr/bin/env python3
"""Connect Universal AI Backend to the user's Base44 app(s) safely.

Reads credentials strictly from environment variables and never logs secret values.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.base44_integration import (  # noqa: E402
    Base44Client,
    build_base44_backend_function_code,
    build_base44_frontend_sdk_code,
    build_base44_hub_page_code,
)


async def verify_live_backend(backend_url: str, api_key: str) -> dict[str, Any]:
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        health = await client.get(f"{backend_url}/health")
        health.raise_for_status()
        stats = await client.get(f"{backend_url}/v1/catalog/stats")
        stats.raise_for_status()
        provs = await client.get(f"{backend_url}/v1/models/providers")
        provs.raise_for_status()
        b44_st = await client.get(f"{backend_url}/v1/integrations/base44/status")
        b44_st.raise_for_status()

        stats_json = stats.json()
        provs_json = provs.json()
        return {
            "health_status": health.json().get("status"),
            "total_tools": stats_json.get("total_tools"),
            "categories_count": len(stats_json.get("categories", {})),
            "rea_mcp_tools": stats_json.get("separate_manifests", {}).get("rea_mcp_tools"),
            "providers_total": provs_json.get("total"),
            "base44_route_configured": b44_st.json().get("configured"),
            "api_key_length": len(api_key),
        }


async def wire_pages_config_if_present(client: Base44Client, app_id: str) -> dict[str, Any]:
    """Safely register UniversalAiHub in src/pages.config.js if the app uses it and build passes."""
    read_res = await client.sandbox_call(
        app_id,
        "read_file",
        {"paths": ["src/pages.config.js"]},
        timeout_s=60.0,
    )
    files = read_res.get("files") or []
    if not files or files[0].get("error") or not files[0].get("content"):
        return {"pages_config": "not_present"}

    original = str(files[0]["content"])
    if "UniversalAiHub" in original:
        return {"pages_config": "already_registered"}

    if "export const PAGES = {" not in original:
        return {"pages_config": "unrecognized_format_skipped"}

    updated = (
        "import UniversalAiHub from './pages/UniversalAiHub';\n"
        + original.replace(
            "export const PAGES = {",
            'export const PAGES = {\n    "UniversalAiHub": UniversalAiHub,',
            1,
        )
    )
    await client.sandbox_call(
        app_id,
        "write_file",
        {"path": "src/pages.config.js", "content": updated, "overwrite": True},
        timeout_s=60.0,
    )
    build_res = await client.sandbox_call(
        app_id,
        "run_command",
        {"command": "npm run build", "timeout_ms": 180000},
        timeout_s=210.0,
    )
    exit_code = build_res.get("exit_code", build_res.get("exitCode", 1))
    if exit_code != 0:
        # Revert cleanly so the app never stays in a broken build state
        await client.sandbox_call(
            app_id,
            "write_file",
            {"path": "src/pages.config.js", "content": original, "overwrite": True},
            timeout_s=60.0,
        )
        return {
            "pages_config": "reverted_on_build_warning",
            "exit_code": exit_code,
            "stderr_tail": str(build_res.get("stderr") or "")[-400:],
        }
    return {"pages_config": "registered_and_build_verified", "exit_code": 0}


async def connect_all() -> int:
    token = (os.getenv("BASE44_ACCESS_TOKEN") or "").strip()
    backend_url = (os.getenv("UNIVERSAL_AI_BACKEND_URL") or "https://universal-ai-backend.vercel.app").strip().rstrip("/")
    backend_api_key = (os.getenv("BACKEND_API_KEY") or "").strip()
    target_app_id = (os.getenv("BASE44_TARGET_APP_ID") or "").strip()

    if not token:
        print("Skipping Base44 sync: BASE44_ACCESS_TOKEN is not set.")
        return 0
    if not backend_api_key:
        print("ERROR: BACKEND_API_KEY is required when connecting Base44.", file=sys.stderr)
        return 1

    print(f"1. Verifying live Universal AI Backend at {backend_url} ...")
    live_summary = await verify_live_backend(backend_url, backend_api_key)
    print("   Live backend verified:", json.dumps(live_summary))

    client = Base44Client(access_token=token)
    print("2. Discovering Base44 apps for authenticated user ...")
    apps = await client.list_apps(limit=50)
    print(f"   Found {len(apps)} Base44 app(s):")
    for idx, app_item in enumerate(apps, 1):
        print(f"   [{idx}] id={app_item['id']} | name={app_item['name']!r} | desc={app_item['description'][:80]!r}")

    if not apps:
        print("No Base44 apps found in this account.")
        return 0

    selected = [a for a in apps if a["id"] == target_app_id] if target_app_id else apps
    if target_app_id and not selected:
        print(f"ERROR: Target app_id {target_app_id} not found in user's Base44 apps.", file=sys.stderr)
        return 1

    fn_code = build_base44_backend_function_code(default_backend_url=backend_url)
    sdk_code = build_base44_frontend_sdk_code()
    hub_code = build_base44_hub_page_code()

    results: list[dict[str, Any]] = []
    for app_item in selected:
        aid = app_item["id"]
        aname = app_item["name"]
        print(f"\n3. Connecting Base44 app: {aname!r} ({aid}) ...")
        summary: dict[str, Any] = {"app_id": aid, "app_name": aname}

        pub_url = await client.get_published_url(aid)
        summary["published_url"] = pub_url

        try:
            sec_res = await client.set_secrets(
                aid,
                {
                    "UNIVERSAL_AI_BACKEND_URL": backend_url,
                    "UNIVERSAL_AI_BACKEND_API_KEY": backend_api_key,
                },
            )
            summary["secrets_set"] = sec_res["updated_keys"]
        except Exception as exc:
            summary["secrets_error"] = str(getattr(exc, "detail", exc))

        try:
            fn_res = await client.deploy_backend_function(aid, "universalAiBackend", fn_code)
            summary["backend_function"] = fn_res
        except Exception as exc:
            summary["backend_function_error"] = str(getattr(exc, "detail", exc))

        # Also attempt sandbox file sync + build check if token includes sandbox access
        try:
            ls_res = await client.sandbox_call(
                aid,
                "list_directory",
                {"path": "src", "recursive": False},
                timeout_s=90.0,
            )
            entries = [e.get("name") for e in (ls_res.get("entries") or [])]
            summary["src_entries"] = entries

            # Write backend function file in sandbox too (Base44 sandbox convention)
            await client.sandbox_call(
                aid,
                "write_file",
                {
                    "path": "base44/functions/universalAiBackend/entry.ts",
                    "content": fn_code,
                    "overwrite": True,
                },
                timeout_s=60.0,
            )
            await client.sandbox_call(
                aid,
                "write_file",
                {
                    "path": "src/lib/universalAiBackend.js",
                    "content": sdk_code,
                    "overwrite": True,
                },
                timeout_s=60.0,
            )
            await client.sandbox_call(
                aid,
                "write_file",
                {
                    "path": "src/pages/UniversalAiHub.jsx",
                    "content": hub_code,
                    "overwrite": True,
                },
                timeout_s=60.0,
            )
            pages_res = await wire_pages_config_if_present(client, aid)
            summary["pages_wiring"] = pages_res

            cp_res = await client.sandbox_call(
                aid,
                "create_checkpoint",
                {"name": "Connected Universal AI Backend v0.6 (6,120+ tools, REA, 45 LLM providers)"},
                timeout_s=60.0,
            )
            summary["checkpoint"] = cp_res
        except Exception as exc:
            summary["sandbox_note"] = str(getattr(exc, "detail", exc))

        print("   Result:", json.dumps(summary))
        results.append(summary)

    print("\n=== BASE44 CONNECTION COMPLETE ===")
    print(json.dumps({"connected_apps": len(results), "apps": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(connect_all()))
