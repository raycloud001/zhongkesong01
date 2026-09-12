from fastapi import APIRouter, Depends, Header
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.assessment.service import (
    create_assessment,
    current_session,
    record_event,
    save_answer,
    session_detail,
    submit_assessment,
)
from app.auth.service import require_owner
from app.db.session import get_db

router = APIRouter()


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questionVersion: str | None = None
    mode: Literal["evidence_only", "demo"] | None = None


class SaveAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str | list[str] | float | dict
    revision: int


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clientEventId: str
    eventType: str
    metadata: dict[str, str] = Field(default_factory=dict)


@router.post("/sessions", status_code=201)
def create(payload: CreateSession | None = None, owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    return create_assessment(db, owner_id, payload.questionVersion if payload else None, payload.mode if payload else None)


@router.get("/sessions/current")
def current(mode: Literal["evidence_only", "demo"] | None = None, owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    return {"session": current_session(db, owner_id, mode)}


@router.get("/sessions/{session_id}")
def detail(session_id: str, owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    return session_detail(db, owner_id, session_id)


@router.put("/sessions/{session_id}/answers/{question_id}")
def answer(session_id: str, question_id: str, payload: SaveAnswer, owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    revision, count = save_answer(db, owner_id, session_id, question_id, payload.value, payload.revision)
    return {"revision": revision, "answeredCount": count}


@router.post("/sessions/{session_id}/submit", status_code=202)
def submit(session_id: str, idempotency_key: str = Header(alias="Idempotency-Key"), owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    return {"jobId": submit_assessment(db, owner_id, session_id, idempotency_key)}


@router.post("/sessions/{session_id}/events", status_code=204)
def event(session_id: str, payload: EventPayload, owner_id: str = Depends(require_owner), db: Session = Depends(get_db)):
    record_event(db, owner_id, session_id, payload.clientEventId, payload.eventType, payload.metadata)
