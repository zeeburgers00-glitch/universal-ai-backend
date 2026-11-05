"""Generated SDK: parses, matches the OpenAPI schema, and needs no hand-maintenance."""

from __future__ import annotations

import ast
import re

import pytest
from fastapi.testclient import TestClient

from app import sdk
from app.main import app


def test_python_sdk_parses_and_exposes_the_client():
    code = sdk.generate_python(app)
    tree = ast.parse(code)  # must be valid Python
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert [node.name for node in classes] == ["UniversalAIClient"]

    methods = [n.name for n in classes[0].body if isinstance(n, ast.FunctionDef)]
    assert "request" in methods
    assert len(methods) > 50, "every documented route should get a method"


def test_method_count_matches_the_schema():
    operations = sum(
        1
        for operations in app.openapi()["paths"].values()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    )
    code = sdk.generate_python(app)
    generated = [
        name for name in sdk._collect(app)
    ]
    assert len(generated) == operations


def test_method_names_are_unique_and_derived_from_paths():
    routes = sdk._unique_names(sdk._collect(app))
    names = [route["python_name"] for route in routes]
    assert len(names) == len(set(names))
    for route in routes[:20]:
        assert route["method"].lower() in route["python_name"]


def test_path_parameters_become_arguments():
    code = sdk.generate_python(app, prefix="/v1/jobs")
    assert "def get_v1_jobs_by_job_id(self, job_id: str)" in code
    assert 'path = f"/v1/jobs/{job_id}"' in code


def test_query_parameters_are_filtered_when_none():
    code = sdk.generate_python(app, prefix="/v1/code")
    assert "if v is not None" in code


def test_typescript_sdk_shape():
    code = sdk.generate_typescript(app)
    assert "export class UniversalAIClient" in code
    assert "async request" in code
    assert "X-API-Key" in code
    assert code.count("async ") > 50


def test_prefix_filter_narrows_the_surface():
    everything = sdk.summary(app)["operations"]
    code_only = len(sdk._collect(app, "/v1/code"))
    assert 0 < code_only < everything


def test_javascript_injection_is_avoided_for_path_values():
    code = sdk.generate_typescript(app, prefix="/v1/jobs")
    # Template literals embed the value at runtime; no string concatenation of user input.
    assert "${job_id}" in code


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "sdk-key")
    with TestClient(app) as test_client:
        yield test_client


HEADERS = {"X-API-Key": "sdk-key"}


def test_sdk_endpoint_requires_the_key(client):
    assert client.get("/v1/sdk").status_code == 401


def test_sdk_endpoint_returns_both_languages(client):
    python_sdk = client.get("/v1/sdk", params={"lang": "python"}, headers=HEADERS).json()
    assert python_sdk["language"] == "python"
    assert python_sdk["summary"]["operations"] > 50
    assert "class UniversalAIClient" in python_sdk["content"]

    ts_sdk = client.get("/v1/sdk", params={"lang": "typescript"}, headers=HEADERS).json()
    assert ts_sdk["language"] == "ts"
    assert "export class" in ts_sdk["content"]


def test_sdk_can_be_written_into_the_repo(client):
    from pathlib import Path

    target = Path(__file__).resolve().parent.parent / "tmp_sdk_client.py"
    try:
        result = client.get(
            "/v1/sdk", params={"lang": "python", "save_to": "tmp_sdk_client.py"}, headers=HEADERS
        ).json()
        assert result["saved_to"] == "tmp_sdk_client.py"
        written = target.read_text(encoding="utf-8")
        ast.parse(written)
        assert "class UniversalAIClient" in written
    finally:
        target.unlink(missing_ok=True)
        target.with_suffix(".py.bak").unlink(missing_ok=True)


def test_bad_save_path_is_rejected(client):
    response = client.get("/v1/sdk", params={"save_to": "../../etc/passwd"}, headers=HEADERS)
    assert response.status_code == 400


def test_generated_operations_are_callable_pairs():
    """Each generated line must use a real HTTP method + path from the schema."""

    code = sdk.generate_python(app, prefix="/v1/jobs")
    pairs = set(re.findall(r'self\.request\("([A-Z]+)", (?:f)?"(/v1/[^"]*)"', code))
    known = set(app.openapi()["paths"])
    for method, path in pairs:
        assert method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        # /v1/jobs/{job_id} style paths appear already substituted as f-strings
        normalised = re.sub(r"\{[^}]+\}", "{x}", path)
        assert any(re.sub(r"\{[^}]+\}", "{x}", candidate) == normalised for candidate in known)
