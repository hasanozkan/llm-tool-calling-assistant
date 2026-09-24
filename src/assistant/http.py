"""The assistant over HTTP — what a mobile or web client talks to.

One conversation = one session. A turn returns the reply *and* the proposed
writes; a write runs only through the confirm endpoint (ADR-0002), so the
client can show a confirmation card — with the `suspicious` warning when the
user never asked for a change.

    uvicorn assistant.http:app --reload
"""

import json
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from assistant.config import router_from_env
from assistant.engine import Assistant
from assistant.library.memory import InMemoryLibrary
from assistant.tools.library_tools import library_tools


class SessionOut(BaseModel):
    session_id: str


class TurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class PendingActionOut(BaseModel):
    action_id: str
    tool: str
    arguments: dict[str, Any]
    suspicious: bool
    reasons: list[str]


class TurnOut(BaseModel):
    reply: str
    tool_calls: list[str]
    pending: list[PendingActionOut]
    flagged: list[str] = Field(description="Tools whose output looked like an instruction")
    total_tokens: int


class ConfirmOut(BaseModel):
    action_id: str
    outcome: dict[str, Any]


def create_app() -> FastAPI:
    app = FastAPI(title="Library assistant", version="0.1.0")
    # A demo API for local clients (Expo web, simulators): any origin, no credentials.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    # Each session gets its own demo library, so a demo (or a live test) always
    # starts from the same shelf instead of whatever the previous visitor borrowed.
    sessions: dict[str, Assistant] = {}

    @app.exception_handler(HTTPException)
    def problem(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            {"type": "about:blank", "status": exc.status_code, "code": exc.detail},
            status_code=exc.status_code,
            media_type="application/problem+json",
        )

    def session(session_id: str) -> Assistant:
        if session_id not in sessions:
            raise HTTPException(404, "session_not_found")
        return sessions[session_id]

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/sessions", status_code=201)
    def open_session() -> SessionOut:
        sid = f"s_{uuid.uuid4().hex[:10]}"
        sessions[sid] = Assistant(router_from_env(), library_tools(InMemoryLibrary()))
        return SessionOut(session_id=sid)

    @app.post("/v1/sessions/{session_id}/turns")
    def turn(session_id: str, body: TurnIn) -> TurnOut:
        r = session(session_id).turn(body.text)
        return TurnOut(
            reply=r.reply,
            tool_calls=r.tool_calls,
            pending=[
                PendingActionOut(
                    action_id=p.action_id,
                    tool=p.tool,
                    arguments=p.arguments,
                    suspicious=p.suspicious,
                    reasons=p.reasons,
                )
                for p in r.pending
            ],
            flagged=r.flagged,
            total_tokens=r.usage.total,
        )

    @app.post("/v1/sessions/{session_id}/actions/{action_id}/confirm")
    def confirm(session_id: str, action_id: str) -> ConfirmOut:
        bot = session(session_id)
        if action_id not in bot.pending:
            raise HTTPException(404, "action_not_found")
        return ConfirmOut(action_id=action_id, outcome=json.loads(bot.confirm(action_id)))

    return app


app = create_app()
