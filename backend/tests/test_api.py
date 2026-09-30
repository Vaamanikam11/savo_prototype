import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["LLM_PROVIDER"] = "mock"

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


def test_full_interview_flow(client):
    s = client.post("/api/sessions").json()
    sid = s["id"]
    assert s["next_question"]

    answers = [
        "Our priorities flipped mid-quarter. I immediately re-planned the sprint.",
        "I had to learn a new tool and I stopped using the old spreadsheet.",
        "I told the team and we synced every morning.",
        "Looking back, I would flag risks earlier.",
        "That is all.",
    ]
    for i, a in enumerate(answers):
        r = client.post(f"/api/sessions/{sid}/turns", json={"text": a}).json()
        assert r["done"] is (i == len(answers) - 1)

    scored = client.post(f"/api/sessions/{sid}/score").json()
    assert scored["status"] == "scored"
    assert {s["dimension"] for s in scored["signals"]} == {
        "response_to_change", "learning_agility", "collaboration_under_change", "reflection"}
    for sig in scored["signals"]:
        if sig["status"] == "scored":
            assert sig["evidence"], "a score must never exist without evidence"


def test_cannot_score_active_interview(client):
    sid = client.post("/api/sessions").json()["id"]
    assert client.post(f"/api/sessions/{sid}/score").status_code == 409


def test_empty_answer_rejected(client):
    sid = client.post("/api/sessions").json()["id"]
    assert client.post(f"/api/sessions/{sid}/turns", json={"text": ""}).status_code == 422


def test_unknown_session_404(client):
    assert client.get("/api/sessions/nope").status_code == 404
