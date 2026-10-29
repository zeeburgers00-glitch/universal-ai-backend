from scripts.preflight import inspect_backend, inspect_worker_env, is_placeholder


def _valid_backend_env():
    values = {
        "BACKEND_API_KEY": "s" * 48,
        "CORS_ORIGINS": "https://app.example.com",
        "AI_API_KEY": "provider-token-placeholder-is-not-checked-as-secret",
        "WORKER_ALLOW_INSECURE_HTTP": "false",
    }
    for url_name, key_name in (
        ("VOICE_WORKER_URL", "VOICE_WORKER_API_KEY"),
        ("MEDIA_WORKER_URL", "MEDIA_WORKER_API_KEY"),
        ("AUTOMATION_WORKER_URL", "AUTOMATION_WORKER_API_KEY"),
        ("AGENT_WORKER_URL", "AGENT_WORKER_API_KEY"),
        ("DESKTOP_AGENT_URL", "DESKTOP_AGENT_API_KEY"),
        ("YOUTUBE_WORKER_URL", "YOUTUBE_WORKER_API_KEY"),
        ("CHANNEL_WORKER_URL", "CHANNEL_WORKER_API_KEY"),
    ):
        values[url_name] = ""
        values[key_name] = ""
    return values


def test_placeholder_detection_is_case_insensitive():
    assert is_placeholder("Replace-With-a-real-secret")
    assert is_placeholder("")
    assert not is_placeholder("s" * 48)


def test_production_backend_preflight_accepts_https_and_strong_key():
    errors, _warnings = inspect_backend(_valid_backend_env(), production=True, strict_workers=False)
    assert errors == []


def test_production_backend_preflight_rejects_local_cors_and_http_worker():
    values = _valid_backend_env()
    values["CORS_ORIGINS"] = "http://localhost:3000"
    values["VOICE_WORKER_URL"] = "http://worker.example.com"
    values["VOICE_WORKER_API_KEY"] = "w" * 32
    errors, _warnings = inspect_backend(values, production=True, strict_workers=False)
    assert any("localhost" in item for item in errors)
    assert any("HTTPS" in item for item in errors)


def test_backend_preflight_rejects_partial_worker_configuration():
    values = _valid_backend_env()
    values["MEDIA_WORKER_URL"] = "https://media.example.com"
    errors, _warnings = inspect_backend(values, production=False, strict_workers=False)
    assert any("MEDIA_WORKER_URL" in item and "MEDIA_WORKER_API_KEY" in item for item in errors)


def test_worker_preflight_rejects_placeholders_and_accepts_random_secrets():
    from scripts.preflight import WORKER_SECRET_NAMES

    placeholder_values = {name: "replace-with-a-real-secret" for name in WORKER_SECRET_NAMES}
    errors, _warnings = inspect_worker_env(placeholder_values, strict_workers=True)
    assert errors

    valid_values = {name: (name + "-") + ("x" * 40) for name in WORKER_SECRET_NAMES}
    errors, warnings = inspect_worker_env(valid_values, strict_workers=True)
    assert errors == []
    assert warnings == []
