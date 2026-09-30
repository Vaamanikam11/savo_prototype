import os
from types import SimpleNamespace

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["LLM_PROVIDER"] = "mock"

import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.db import Base, engine
from app.framework import ADAPTABILITY
from app.guard import limiter
from app.llm import OpenAILLM, get_llm
from app.schemas import Turn


@pytest.fixture()
def client(monkeypatch):
    for k in ("ACCESS_CODE", "ADMIN_TOKEN", "MAX_SESSIONS_PER_DAY"):
        monkeypatch.delenv(k, raising=False)
    Base.metadata.drop_all(engine)
    limiter.reset()
    with TestClient(main.app) as c:
        yield c


def test_access_code_required_when_set(client, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "s3cret")
    assert client.get("/api/config").json()["access_code_required"] is True
    assert client.post("/api/sessions").status_code == 401
    assert client.post("/api/sessions", headers={"x-access-code": "wrong"}).status_code == 401
    assert client.post("/api/sessions", headers={"x-access-code": "s3cret"}).status_code == 200


def test_daily_session_cap(client, monkeypatch):
    monkeypatch.setenv("MAX_SESSIONS_PER_DAY", "2")
    assert client.post("/api/sessions").status_code == 200
    assert client.post("/api/sessions").status_code == 200
    assert client.post("/api/sessions").status_code == 429


def test_per_ip_rate_limit(client):
    codes = [client.post("/api/sessions").status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_admin_disabled_without_token(client):
    assert client.get("/api/admin/sessions").status_code == 404


def test_admin_lists_sessions_with_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "adm")
    sid = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{sid}/turns", json={"text": "I immediately re-planned the sprint."})
    assert client.get("/api/admin/sessions").status_code == 401
    rows = client.get("/api/admin/sessions", headers={"x-admin-token": "adm"}).json()
    assert rows[0]["id"] == sid
    assert any(t["role"] == "participant" for t in rows[0]["turns"])


def test_model_outage_does_not_break_interview(client, monkeypatch):
    class Boom:
        def next_question(self, *a, **k): raise RuntimeError("api down")
        def extract(self, *a, **k): raise RuntimeError("api down")

    monkeypatch.setattr(main, "_llm", Boom())
    sid = client.post("/api/sessions").json()["id"]
    r = client.post(f"/api/sessions/{sid}/turns", json={"text": "Something changed at work."})
    assert r.status_code == 200 and r.json()["next_question"]  # falls back to fixed follow-up
    for _ in range(4):
        client.post(f"/api/sessions/{sid}/turns", json={"text": "Another answer here."})
    assert client.post(f"/api/sessions/{sid}/score").status_code == 502


def test_missing_key_fails_loudly(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        get_llm()


class FakeOpenAI:
    """Stands in for the OpenAI client so the provider can be tested without network or key."""

    def __init__(self, tool_args=None, text="What did you do next?"):
        self.tool_args, self.text, self.calls = tool_args, text, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if "tools" in kw:
            msg = SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(self.tool_args)))], content=None)
        else:
            msg = SimpleNamespace(tool_calls=None, content=self.text)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


TURNS = [Turn(index=0, role="interviewer", text="q"), Turn(index=1, role="participant", text="I told the team right away.")]


def test_openai_provider_parses_tool_call_and_question():
    args = {"dimensions": [{"dimension": "collaboration_under_change", "score": 3,
                            "rationale": "x", "quotes": ["I told the team right away."]}]}
    llm = OpenAILLM(model="m", client=FakeOpenAI(args))
    raw = llm.extract(ADAPTABILITY, TURNS)
    assert raw.dimensions[0].score == 3
    assert llm.next_question(ADAPTABILITY, TURNS) == "What did you do next?"
    assert llm.client.calls[0]["tool_choice"]["function"]["name"] == "record_signals"
