import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import InterviewSession, SignalRow, TurnRow, get_db, init_db
from .framework import FRAMEWORKS
from .grounding import ground
from .guard import (access_code, client_ip, limiter, max_sessions_per_day, require_access_code,
                    require_admin)
from .llm import LLM, describe_provider, get_llm
from .schemas import DimensionSignal, Evidence, SessionOut, Turn, TurnIn

DEFAULT_FRAMEWORK = "adaptability-v1"
log = logging.getLogger("signal")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Signal Event demo", lifespan=lifespan)
_llm: LLM | None = None


def llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = get_llm()
    return _llm


def _turns(s: InterviewSession) -> list[Turn]:
    return [Turn(index=t.idx, role=t.role, text=t.text) for t in s.turns]


def _signals(s: InterviewSession) -> list[DimensionSignal]:
    order = [d.key for d in FRAMEWORKS[s.framework_id].dimensions]
    rows = sorted(s.signals, key=lambda r: order.index(r.dimension) if r.dimension in order else 99)
    return [DimensionSignal(dimension=r.dimension, score=r.score, status=r.status, rationale=r.rationale,
                            evidence=[Evidence(**e) for e in r.evidence], dropped_quotes=r.dropped_quotes)
            for r in rows]


def _out(s: InterviewSession, next_question: str | None = None, done: bool = False) -> SessionOut:
    return SessionOut(id=s.id, status=s.status, framework_id=s.framework_id, turns=_turns(s),
                      signals=_signals(s), next_question=next_question, done=done)


def _get(db: Session, session_id: str) -> InterviewSession:
    s = db.get(InterviewSession, session_id)
    if s is None:
        raise HTTPException(404, "Session not found")
    return s


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {"access_code_required": bool(access_code()), "scorer": describe_provider()}


@app.get("/api/framework")
def framework(framework_id: str = DEFAULT_FRAMEWORK):
    fw = FRAMEWORKS[framework_id]
    return {"id": fw.id, "title": fw.title, "max_turns": fw.max_participant_turns,
            "dimensions": [{"key": d.key, "label": d.label, "definition": d.definition, "anchors": d.anchors}
                           for d in fw.dimensions]}


@app.post("/api/sessions", response_model=SessionOut, dependencies=[Depends(require_access_code)])
def create_session(request: Request, db: Session = Depends(get_db)):
    limiter.check(f"new:{client_ip(request)}", limit=10, window_s=3600)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count()).select_from(InterviewSession).where(InterviewSession.created_at >= today))
    if used >= max_sessions_per_day():
        raise HTTPException(429, "The demo has reached its daily limit. Please try again tomorrow.")
    fw = FRAMEWORKS[DEFAULT_FRAMEWORK]
    s = InterviewSession(framework_id=fw.id)
    s.turns.append(TurnRow(idx=0, role="interviewer", text=fw.opening_question))
    db.add(s)
    db.commit()
    return _out(s, next_question=fw.opening_question)


@app.get("/api/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, db: Session = Depends(get_db)):
    return _out(_get(db, session_id))


@app.post("/api/sessions/{session_id}/turns", response_model=SessionOut)
def add_turn(session_id: str, body: TurnIn, request: Request, db: Session = Depends(get_db)):
    limiter.check(f"turn:{client_ip(request)}", limit=40, window_s=600)
    s = _get(db, session_id)
    if s.status != "active":
        raise HTTPException(409, "Interview is already complete")
    fw = FRAMEWORKS[s.framework_id]
    s.turns.append(TurnRow(idx=len(s.turns), role="participant", text=body.text.strip()))
    participant_turns = sum(1 for t in s.turns if t.role == "participant")
    if participant_turns >= fw.max_participant_turns:
        s.status = "complete"
        db.commit()
        return _out(s, done=True)
    try:
        question = llm().next_question(fw, _turns(s))
    except Exception:  # model outage or bad key: keep the interview going with the fixed question
        log.exception("next_question failed; using fixed follow-up")
        question = fw.follow_ups[min(participant_turns - 1, len(fw.follow_ups) - 1)]
    s.turns.append(TurnRow(idx=len(s.turns), role="interviewer", text=question))
    db.commit()
    return _out(s, next_question=question)


@app.post("/api/sessions/{session_id}/finish", response_model=SessionOut)
def finish(session_id: str, db: Session = Depends(get_db)):
    """Let a participant end early; scoring will abstain where evidence is thin."""
    s = _get(db, session_id)
    if s.status == "active":
        s.status = "complete"
        db.commit()
    return _out(s, done=True)


@app.post("/api/sessions/{session_id}/score", response_model=SessionOut)
def score(session_id: str, request: Request, db: Session = Depends(get_db)):
    limiter.check(f"score:{client_ip(request)}", limit=10, window_s=600)
    s = _get(db, session_id)
    if s.status == "active":
        raise HTTPException(409, "Finish the interview before scoring")
    fw = FRAMEWORKS[s.framework_id]
    turns = _turns(s)
    if not any(t.role == "participant" for t in turns):
        raise HTTPException(422, "No participant responses to score")
    try:
        raw = llm().extract(fw, turns)
    except Exception:
        log.exception("extract failed")
        raise HTTPException(502, "The scoring model call failed. Please try again in a moment.")
    results = ground(raw, turns, [d.key for d in fw.dimensions])
    s.signals.clear()
    for r in results:
        s.signals.append(SignalRow(dimension=r.dimension, score=r.score, status=r.status,
                                   rationale=r.rationale, dropped_quotes=r.dropped_quotes,
                                   evidence=[e.model_dump() for e in r.evidence]))
    s.status = "scored"
    db.commit()
    return _out(s, done=True)


@app.get("/api/admin/sessions", dependencies=[Depends(require_admin)])
def admin_sessions(limit: int = 100, db: Session = Depends(get_db)):
    """Read candidate sessions. Disabled unless ADMIN_TOKEN is set; send it as X-Admin-Token."""
    rows = db.scalars(select(InterviewSession).order_by(InterviewSession.created_at.desc()).limit(min(limit, 500))).all()
    return [{"created_at": r.created_at.isoformat(), **_out(r).model_dump()} for r in rows]
