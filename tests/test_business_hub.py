import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_catalog_has_no_connected_claims_by_default():
    data = json.loads((ROOT / "catalog" / "business_plugins.json").read_text(encoding="utf-8"))
    assert len(data["plugins"]) >= 6
    assert all(p["status"] != "connected" for p in data["plugins"])


def test_temp_mail_is_limited_to_testing_and_blocks_bypass():
    source = (ROOT / "app" / "business_hub.py").read_text(encoding="utf-8")
    assert 'Literal["qa_testing", "owned_domain_staging"]' in source
    assert '"allow_account_verification_bypass": False' in source
    assert '"allow_bulk_signup": False' in source


def test_ads_policy_forbids_artificial_interactions():
    data = json.loads((ROOT / "catalog" / "monetization_streams.json").read_text(encoding="utf-8"))
    policy = data["policies"]["ad_traffic"].lower()
    # Wording may change; the prohibitions must not.
    assert "never click" in policy
    assert "incentivize" in policy
    assert "automate ad interactions" in policy
    assert "artificial traffic" in policy or "genuine human traffic" in policy
