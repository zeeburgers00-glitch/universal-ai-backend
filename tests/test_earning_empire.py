import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_earning_fleet_has_120_slots_across_12_departments():
    fleet = json.loads((ROOT / "catalog" / "earning_empire_fleet.json").read_text(encoding="utf-8"))
    assert fleet["agent_slots"] == 120
    assert len(fleet["agents"]) == 120
    assert len(fleet["departments"]) == 12
    assert sum(item["capacity"] for item in fleet["departments"]) == 120
    assert len({item["id"] for item in fleet["agents"]}) == 120


def test_earning_agents_have_approval_policy():
    fleet = json.loads((ROOT / "catalog" / "earning_empire_fleet.json").read_text(encoding="utf-8"))
    for agent in fleet["agents"]:
        assert agent["execution"] == "spawn_on_demand"
        assert "external_messages" in agent["requires_approval_for"]
        assert "payments" in agent["requires_approval_for"]


def test_earning_workflows_are_defined_and_external_actions_are_gated():
    fleet = json.loads((ROOT / "catalog" / "earning_empire_fleet.json").read_text(encoding="utf-8"))
    assert len(fleet["workflows"]) >= 8
    for workflow in fleet["workflows"]:
        if workflow["external_actions"]:
            assert workflow["requires_human_approval"] is True
