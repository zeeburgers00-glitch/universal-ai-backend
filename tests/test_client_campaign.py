import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_client_campaign_routes_are_api_key_protected_and_do_not_send():
    source = (ROOT / "app" / "client_campaign.py").read_text(encoding="utf-8")
    assert 'Depends(require_api_key)' in source
    assert 'external_contact_sending_enabled": False' in source
    assert 'approval_status": "approved_to_send"' in source
    assert "No message or form was submitted." in source
    assert "smtp" not in source.lower()
    assert "send_email" not in source.lower()


def test_campaign_crm_migration_is_server_only_and_rls_enabled():
    source = (ROOT / "supabase" / "migrations" / "20261104180000_create_client_campaign_crm.sql").read_text(encoding="utf-8")
    assert source.count("enable row level security") == 2
    assert source.count("revoke all on table") == 2
    assert "to service_role" in source
    # Check real statements only: a comment mentioning "anon" is not a grant.
    statements = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("--")
    ).lower()
    assert "to anon" not in statements
    assert "to authenticated" not in statements
    assert not re.search(r"grant\s+[^;]*\bto\s+(anon|authenticated|public)\b", statements)


def test_campaign_models_limit_batch_and_require_https():
    source = (ROOT / "app" / "client_campaign.py").read_text(encoding="utf-8")
    assert "max_length=50" in source
    assert 'value.scheme != "https"' in source
    # The guard may be written as lead.get("lead_status") == "do_not_contact".
    assert re.search(r'==\s*"do_not_contact"', source), "do_not_contact must be blocked"
