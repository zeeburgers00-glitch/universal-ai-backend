"""HTTP surface for the Cursor-style code assistant.

Every route requires the API key: `apply` writes to disk, so these are not public.
No route calls a model provider, so none of them can fail for "missing API key".
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .code_assistant import CodeAssistantError, apply_edit, build_index, commit_message, read_file, tree, write_file
from .code_assistant import outline as file_outline
from .code_assistant import plan as build_plan
from .code_assistant import propose_edit, review as run_review
from .code_assistant import rules as read_rules
from .code_assistant import search as search_code
from .code_assistant import test_scaffold
from .security import require_api_key

router = APIRouter(prefix="/v1/code", tags=["code-assistant"], dependencies=[Depends(require_api_key)])


class IndexRequest(BaseModel):
    root: str | None = Field(default=None, max_length=400, description="Optional sub-directory to index")


class PathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=400, description="Repository-relative file path")


class EditRequest(BaseModel):
    path: str = Field(min_length=1, max_length=400)
    find: str = Field(min_length=1, max_length=20_000)
    replace: str = Field(default="", max_length=20_000)


class ApplyRequest(EditRequest):
    dry_run: bool = Field(default=True, description="False actually writes the file and keeps a .bak")


class ReviewRequest(BaseModel):
    paths: list[str] | None = Field(default=None, max_length=200)


class WriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=400)
    content: str = Field(default="", max_length=400_000)
    dry_run: bool = Field(default=True, description="False actually saves the file")


class PlanRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=500)


def _guard(exc: CodeAssistantError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/index")
def code_index(request: IndexRequest | None = None) -> dict[str, Any]:
    """Walk the repo, extract symbols, persist the index. ~250 files in under a second."""

    try:
        return build_index((request.root if request else None))
    except CodeAssistantError as exc:
        raise _guard(exc)


@router.get("/search")
def code_search(
    q: str = Query(min_length=2, max_length=200),
    kind: str | None = Query(default=None, max_length=20, description="File extension without the dot, e.g. py"),
    limit: int = Query(default=20, ge=1, le=100),
    path_prefix: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    """Ranked symbol + text search across the repository."""

    try:
        return search_code(q, kind=kind, limit=limit, path_prefix=path_prefix)
    except CodeAssistantError as exc:
        raise _guard(exc)


@router.get("/tree")
def code_tree(
    prefix: str | None = Query(default=None, max_length=200),
    max_entries: int = Query(default=3000, ge=1, le=10_000),
) -> dict[str, Any]:
    """File tree for the editor, derived from the index."""

    try:
        return tree(prefix=prefix, max_entries=max_entries)
    except CodeAssistantError as exc:
        raise _guard(exc)


@router.get("/read")
def code_read(path: str = Query(min_length=1, max_length=400)) -> dict[str, Any]:
    """Full file content for the editor pane."""

    try:
        return read_file(path)
    except CodeAssistantError as exc:
        raise _guard(exc)


@router.post("/write")
def code_write(request: WriteRequest) -> dict[str, Any]:
    """Save an editor buffer. Dry-run by default; keeps a .bak when writing."""

    try:
        return write_file(request.path, request.content, dry_run=request.dry_run)
    except CodeAssistantError as exc:
        raise _guard(exc)


@router.post("/outline")
def code_outline(request: PathRequest) -> dict[str, Any]:
    """Classes, functions, imports and TODO count for one file."""

    try:
        return file_outline(request.path)
    except CodeAssistantError as exc:
        raise _guard(exc)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"cannot read file: {exc}")


@router.post("/diff")
def code_diff(request: EditRequest) -> dict[str, Any]:
    """Preview an edit as a unified diff. Writes nothing."""

    try:
        return propose_edit(request.path, request.find, request.replace)
    except CodeAssistantError as exc:
        raise _guard(exc)


@router.post("/apply")
def code_apply(request: ApplyRequest) -> dict[str, Any]:
    """Apply a find/replace edit. Dry-run by default; a .bak is kept when writing."""

    try:
        return apply_edit(request.path, request.find, request.replace, dry_run=request.dry_run)
    except CodeAssistantError as exc:
        raise _guard(exc)


@router.post("/review")
def code_review(request: ReviewRequest | None = None) -> dict[str, Any]:
    """Static review: dead code smells, secrets, bare excepts, long functions."""

    try:
        return run_review(request.paths if request else None)
    except CodeAssistantError as exc:
        raise _guard(exc)


@router.post("/tests")
def code_tests(request: PathRequest) -> dict[str, Any]:
    """Generate a pytest skeleton for the public functions in a module."""

    try:
        return test_scaffold(request.path)
    except CodeAssistantError as exc:
        raise _guard(exc)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"cannot read file: {exc}")


@router.get("/commit-message")
def code_commit_message() -> dict[str, Any]:
    """Draft a conventional commit message from the working diff."""

    try:
        return commit_message()
    except CodeAssistantError as exc:
        raise _guard(exc)


@router.get("/rules")
def code_rules() -> dict[str, Any]:
    """Whatever rule files the repo already carries (.cursorrules, AGENTS.md, …)."""

    return read_rules()


@router.post("/plan")
def code_plan(request: PlanRequest) -> dict[str, Any]:
    """Turn a goal into reviewable steps, with the files that matter."""

    try:
        return build_plan(request.goal)
    except CodeAssistantError as exc:
        raise _guard(exc)
