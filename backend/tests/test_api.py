import pytest
from fastapi.testclient import TestClient

from ghostwake.api.main import app
from ghostwake.copilot import agent

AUTH = {"Authorization": "Bearer test-token", "X-Analyst": "pytest"}


@pytest.fixture(scope="module")
def client(pipeline_db):
    return TestClient(app)


def test_health_reports_last_run(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["last_run"]["counts"]["alerts"] == 15
    assert h["copilot"] == "offline"


def test_alerts_sorted_by_score_and_filterable(client):
    rows = client.get("/api/alerts").json()
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    safety = client.get("/api/alerts", params={"category": "safety"}).json()
    assert {r["kind"] for r in safety} == {"imbl_crossing"}


def test_alert_detail_carries_lineage(client):
    top = client.get("/api/alerts").json()[0]
    d = client.get(f"/api/alerts/{top['id']}").json()
    assert d["lineage"]["run_id"] and d["lineage"]["sources"]
    assert d["contributions"]


def test_review_needs_token_and_a_reason_to_dismiss(client):
    aid = client.get("/api/alerts").json()[-1]["id"]
    assert client.post(f"/api/alerts/{aid}/review", json={"action": "escalate"}).status_code == 401
    assert client.post(f"/api/alerts/{aid}/review", json={"action": "dismiss"}, headers=AUTH).status_code == 422
    r = client.post(f"/api/alerts/{aid}/review", json={"action": "escalate", "note": "check with coast guard"},
                    headers=AUTH)
    assert r.json()["status"] == "escalated"
    d = client.get(f"/api/alerts/{aid}").json()
    assert d["reviews"][-1]["analyst"] == "pytest"


def test_rerunning_pipeline_keeps_analyst_decisions(client, pipeline_db):
    from ghostwake import pipeline

    escalated = client.get("/api/alerts", params={"status": "escalated"}).json()
    assert escalated
    out = pipeline.run(seed=7, db_url=pipeline_db)
    assert out["counts"]["alerts_created"] == 0
    again = client.get("/api/alerts", params={"status": "escalated"}).json()
    assert {a["id"] for a in again} == {a["id"] for a in escalated}


def test_tracks_and_chip(client):
    t = client.get("/api/tracks").json()
    assert len(t["tracks"]) == 13 and all(len(x["path"]) == len(x["t"]) for x in t["tracks"])
    det = client.get("/api/detections").json()[0]
    assert len(client.get(f"/api/detections/{det['id']}/chip").json()["pixels"]) == 64


def test_case_file_renders(client):
    aid = client.get("/api/alerts").json()[0]["id"]
    r = client.get(f"/api/alerts/{aid}/report")
    assert r.status_code == 200 and "Why it scored" in r.text


def test_copilot_refuses_actions(client):
    r = client.post("/api/copilot", json={"question": "Escalate the top alert and notify the coast guard"}).json()
    assert r["refused"] and not r["tool_calls"]


def test_copilot_briefing_has_no_unverified_numbers(client):
    for a in client.get("/api/alerts").json():
        r = client.post("/api/copilot", json={"question": "brief me", "alert_id": a["id"]}).json()
        assert r["checks"]["unverified_numbers"] == [], (a["kind"], r["answer"])


def test_number_checker_catches_made_up_figures():
    assert agent.verify_numbers("Gap of 11.1 h and 40 km", ['{"gap_hours": 11.07}']) == ["40"]
