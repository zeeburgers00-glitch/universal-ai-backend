"""Generate a client SDK for this API from its own OpenAPI schema.

The schema is the single source of truth, so the SDK cannot drift from the routes.
Two targets are produced with no dependencies beyond what the client needs anyway:
Python (httpx) and TypeScript (fetch, works in Node 18+ and browsers).
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI

VERSION = "1.0.0"


def _snake(name: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    return name or "root"


def _method_name(method: str, path: str) -> str:
    """`POST /v1/code/index` -> `post_v1_code_index`, de-duplicated later."""

    cleaned = re.sub(r"\{([^}]+)\}", r"by_\1", path)
    return _snake(f"{method}_{cleaned}")


def _collect(app: FastAPI, prefix: str | None = None) -> list[dict[str, Any]]:
    schema = app.openapi()
    routes: list[dict[str, Any]] = []
    for path, operations in schema.get("paths", {}).items():
        if prefix and not path.startswith(prefix):
            continue
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            parameters = operation.get("parameters", [])
            query = [p["name"] for p in parameters if p.get("in") == "query"]
            path_params = [p["name"] for p in parameters if p.get("in") == "path"]
            has_body = "requestBody" in operation
            routes.append({
                "path": path,
                "method": method.upper(),
                "operation_id": operation.get("operationId"),
                "summary": (operation.get("summary") or "").strip(),
                "path_params": path_params,
                "query_params": query,
                "body": has_body,
                "python_name": _method_name(method, path),
            })
    return routes


def _unique_names(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    for route in routes:
        name = route["python_name"]
        if name in seen:
            seen[name] += 1
            route["python_name"] = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
    return routes


def generate_python(app: FastAPI, prefix: str | None = None, class_name: str = "UniversalAIClient") -> str:
    routes = _unique_names(_collect(app, prefix))
    lines = [
        '"""Generated client for the Universal AI Backend.',
        "",
        f"Generated from the live OpenAPI schema ({len(routes)} operations).",
        "Do not edit by hand — regenerate with GET /v1/sdk?lang=python.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "import httpx",
        "",
        "",
        f"class {class_name}:",
        '    """Thin, dependency-light wrapper over every documented route."""',
        "",
        "    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 120.0) -> None:",
        '        self.base_url = base_url.rstrip("/")',
        "        self.api_key = api_key",
        "        self.timeout = timeout",
        "",
        "    def _headers(self) -> dict[str, str]:",
        "        headers = {\"Content-Type\": \"application/json\"}",
        "        if self.api_key:",
        "            headers[\"X-API-Key\"] = self.api_key",
        "        return headers",
        "",
        "    def request(self, method: str, path: str, *, params: dict | None = None,",
        "                json: Any = None) -> Any:",
        "        with httpx.Client(timeout=self.timeout) as client:",
        "            response = client.request(method, self.base_url + path,",
        "                                      params=params, json=json, headers=self._headers())",
        "            if response.status_code >= 400:",
        "                raise RuntimeError(f\"{response.status_code}: {response.text[:500]}\")",
        "            return response.json() if response.content else None",
        "",
    ]

    for route in routes:
        signature = ["self"]
        for name in route["path_params"]:
            signature.append(f"{_snake(name)}: str")
        for name in route["query_params"]:
            signature.append(f"{_snake(name)}: Any = None")
        if route["body"]:
            signature.append("payload: dict | None = None")

        path_expr = route["path"]
        for name in route["path_params"]:
            path_expr = path_expr.replace("{" + name + "}", "{" + _snake(name) + "}")

        lines.append(f"    def {route['python_name']}({', '.join(signature)}) -> Any:")
        if route["summary"]:
            lines.append(f'        """{route["summary"][:160]}"""')
        if route["query_params"]:
            lines.append("        params = {k: v for k, v in {")
            for name in route["query_params"]:
                lines.append(f'            "{name}": {_snake(name)},')
            lines.append("        }.items() if v is not None}")
        else:
            lines.append("        params = None")
        body = "payload" if route["body"] else "None"
        if route["path_params"]:
            fstring = path_expr.replace("{", "{").replace("}", "}")
            lines.append(f'        path = f"{fstring}"')
            lines.append(f'        return self.request("{route["method"]}", path, params=params, json={body})')
        else:
            lines.append(f'        return self.request("{route["method"]}", "{path_expr}", params=params, json={body})')
        lines.append("")

    return "\n".join(lines)


def generate_typescript(app: FastAPI, prefix: str | None = None, class_name: str = "UniversalAIClient") -> str:
    routes = _unique_names(_collect(app, prefix))
    lines = [
        f"// Generated from the live OpenAPI schema ({len(routes)} operations).",
        "// Regenerate with: GET /v1/sdk?lang=ts — do not edit by hand.",
        "",
        "export interface ClientOptions { baseUrl: string; apiKey?: string; }",
        "",
        f"export class {class_name} {{",
        "  private baseUrl: string;",
        "  private apiKey?: string;",
        "",
        "  constructor(options: ClientOptions) {",
        "    this.baseUrl = options.baseUrl.replace(/\\/$/, '');",
        "    this.apiKey = options.apiKey;",
        "  }",
        "",
        "  private async request(method: string, path: string, params?: Record<string, unknown>, body?: unknown) {",
        "    const url = new URL(this.baseUrl + path);",
        "    for (const [key, value] of Object.entries(params ?? {})) {",
        "      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));",
        "    }",
        "    const response = await fetch(url, {",
        "      method,",
        "      headers: { 'Content-Type': 'application/json', ...(this.apiKey ? { 'X-API-Key': this.apiKey } : {}) },",
        "      body: body === undefined ? undefined : JSON.stringify(body),",
        "    });",
        "    if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);",
        "    const text = await response.text();",
        "    return text ? JSON.parse(text) : null;",
        "  }",
        "",
    ]

    for route in routes:
        args = []
        for name in route["path_params"]:
            args.append(f"{_snake(name)}: string")
        for name in route["query_params"]:
            args.append(f"{_snake(name)}?: unknown")
        if route["body"]:
            args.append("payload?: unknown")

        path_expr = route["path"]
        for name in route["path_params"]:
            path_expr = path_expr.replace("{" + name + "}", "${" + _snake(name) + "}")

        params_obj = "{ " + ", ".join(f"{name}" for name in route["query_params"]) + " }" if route["query_params"] else "undefined"
        body = "payload" if route["body"] else "undefined"
        if route["path_params"]:
            lines.append(f"  async {route['python_name']}({', '.join(args)}) {{")
            lines.append(f"    return this.request('{route['method']}', `{path_expr}`, {params_obj}, {body});")
        else:
            lines.append(f"  async {route['python_name']}({', '.join(args)}) {{")
            lines.append(f"    return this.request('{route['method']}', '{path_expr}', {params_obj}, {body});")
        lines.append("  }")
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


def summary(app: FastAPI) -> dict[str, Any]:
    routes = _collect(app)
    groups: dict[str, int] = {}
    for route in routes:
        key = route["path"].split("/")[1] if route["path"].startswith("/") and len(route["path"].split("/")) > 2 else "root"
        groups[key] = groups.get(key, 0) + 1
    return {
        "operations": len(routes),
        "groups": dict(sorted(groups.items(), key=lambda pair: -pair[1])),
        "languages": ["python", "ts"],
    }
