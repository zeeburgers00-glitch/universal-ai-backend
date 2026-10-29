#!/usr/bin/env python3
"""Check deployment environment files without ever printing secret values."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from dotenv import dotenv_values

BACKEND_WORKERS = {
    "voice": ("VOICE_WORKER_URL", "VOICE_WORKER_API_KEY"),
    "media": ("MEDIA_WORKER_URL", "MEDIA_WORKER_API_KEY"),
    "automation": ("AUTOMATION_WORKER_URL", "AUTOMATION_WORKER_API_KEY"),
    "agent": ("AGENT_WORKER_URL", "AGENT_WORKER_API_KEY"),
    "desktop": ("DESKTOP_AGENT_URL", "DESKTOP_AGENT_API_KEY"),
    "youtube": ("YOUTUBE_WORKER_URL", "YOUTUBE_WORKER_API_KEY"),
    "channel": ("CHANNEL_WORKER_URL", "CHANNEL_WORKER_API_KEY"),
}
WORKER_SECRET_NAMES = (
    "REDIS_PASSWORD",
    "VOICE_WORKER_API_KEY",
    "MEDIA_WORKER_API_KEY",
    "AUTOMATION_WORKER_API_KEY",
    "AGENT_WORKER_API_KEY",
    "YOUTUBE_WORKER_API_KEY",
    "CHANNEL_WORKER_API_KEY",
)
PLACEHOLDER_MARKERS = ("replace-with", "changeme", "change-me", "your-secret", "example-secret")


def is_placeholder(value: str | None) -> bool:
    if not value or not value.strip():
        return True
    cleaned = value.strip().lower()
    return any(marker in cleaned for marker in PLACEHOLDER_MARKERS) or cleaned.startswith("<")


def inspect_backend(values: dict[str, str | None], production: bool, strict_workers: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if is_placeholder(values.get("BACKEND_API_KEY")):
        errors.append("BACKEND_API_KEY is missing or still a placeholder.")
    elif len((values.get("BACKEND_API_KEY") or "").strip()) < 32:
        errors.append("BACKEND_API_KEY must be at least 32 characters; use a randomly generated secret.")

    origins = [part.strip() for part in (values.get("CORS_ORIGINS") or "").split(",") if part.strip()]
    if production:
        if not origins:
            errors.append("CORS_ORIGINS must contain the exact production app origin(s).")
        elif any("localhost" in origin.lower() or "127.0.0.1" in origin for origin in origins):
            errors.append("Production CORS_ORIGINS still contains a localhost origin.")
        if any(not origin.startswith("https://") for origin in origins):
            errors.append("Production CORS_ORIGINS entries must use HTTPS.")
    elif not origins:
        warnings.append("CORS_ORIGINS is empty; browser requests from an existing app may be blocked.")

    provider_keys = (
        "AI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "TOGETHER_API_KEY",
        "DEEPSEEK_API_KEY", "FIREWORKS_API_KEY", "CEREBRAS_API_KEY", "MISTRAL_API_KEY",
        "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "SILICONFLOW_API_KEY", "SAMBANOVA_API_KEY",
        "NEBIUS_API_KEY", "NOVITA_API_KEY", "HYPERBOLIC_API_KEY", "DASHSCOPE_API_KEY",
        "HUGGINGFACE_API_KEY", "OLLAMA_BASE_URL", "VLLM_BASE_URL", "SGLANG_BASE_URL",
        "LOCALAI_BASE_URL", "LLAMA_CPP_BASE_URL", "LMSTUDIO_BASE_URL", "LITELLM_BASE_URL",
    )
    if not any((values.get(name) or "").strip() for name in provider_keys):
        warnings.append("No model-provider key/base URL is configured; chat and agent planning won't run.")

    for service, (url_name, key_name) in BACKEND_WORKERS.items():
        url = (values.get(url_name) or "").strip()
        key = (values.get(key_name) or "").strip()
        if bool(url) != bool(key):
            errors.append(f"{service} worker has only one of {url_name} and {key_name} configured.")
        if url and not url.startswith("https://"):
            if production or not (
                url.startswith("http://localhost") or url.startswith("http://127.0.0.1")
            ):
                errors.append(f"{url_name} must use HTTPS except explicitly local development.")
            else:
                warnings.append(f"{url_name} uses local HTTP and cannot normally be reached by hosted Vercel.")
        if strict_workers and not (url and key):
            errors.append(f"{service} worker is required by --strict-workers but is not configured.")
        elif not url and not strict_workers:
            warnings.append(f"{service} worker is not configured (okay if that capability is not being used).")

    if production and (values.get("WORKER_ALLOW_INSECURE_HTTP") or "").lower() == "true":
        errors.append("WORKER_ALLOW_INSECURE_HTTP must not be true in production.")
    return errors, warnings


def inspect_worker_env(values: dict[str, str | None], strict_workers: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for name in WORKER_SECRET_NAMES:
        if is_placeholder(values.get(name)):
            message = f"{name} is missing or still a placeholder."
            if strict_workers or name == "REDIS_PASSWORD":
                errors.append(message)
            else:
                warnings.append(message)
        elif len((values.get(name) or "").strip()) < 24:
            errors.append(f"{name} must be at least 24 characters.")
    return errors, warnings


def read_env(path: Path, label: str, errors: list[str], required: bool) -> dict[str, str | None]:
    if not path.is_file():
        message = f"{label} file not found: {path}"
        (errors if required else []).append(message) if required else None
        return {}
    return dict(dotenv_values(path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="backend env file (default: .env)")
    parser.add_argument("--worker-env-file", default="workers/.env.workers", help="worker env file")
    parser.add_argument("--production", action="store_true", help="enforce production HTTPS/CORS checks")
    parser.add_argument("--strict-workers", action="store_true", help="require all worker services and worker secrets")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    backend_path = Path(args.env_file)
    worker_path = Path(args.worker_env_file)
    backend = read_env(backend_path, "Backend environment", errors, required=True)
    backend_errors, backend_warnings = inspect_backend(backend, args.production, args.strict_workers)
    errors.extend(backend_errors)
    warnings.extend(backend_warnings)

    worker_required = args.strict_workers or worker_path.exists()
    worker_values = read_env(worker_path, "Worker environment", errors, required=worker_required)
    if worker_values:
        worker_errors, worker_warnings = inspect_worker_env(worker_values, args.strict_workers)
        errors.extend(worker_errors)
        warnings.extend(worker_warnings)
    elif not worker_required:
        warnings.append("Worker env file not found; run backend-only checks or create workers/.env.workers when deploying workers.")

    print(f"Preflight: {len(errors)} error(s), {len(warnings)} warning(s)")
    for item in warnings:
        print(f"WARN: {item}")
    for item in errors:
        print(f"ERROR: {item}")
    if errors:
        print("Preflight FAILED. Secret values were not displayed.")
        return 1
    print("Preflight PASSED. This validates configuration only, not worker health or external credentials.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
