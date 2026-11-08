from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..ai.llm import DISCLAIMER, get_llm
from ..ai.tools import Toolbox
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..security import audit, require

router = APIRouter(prefix="/ai")
DB = Annotated[Session, Depends(get_db)]
ALLOWED = require("admin", "analyst", "buyer")


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    history: list[dict[str, str]] = []


@router.get("/status")
def status(user: Annotated[User, Depends(ALLOWED)]):
    llm = get_llm()
    return {"mode": llm.mode, "model": llm.model, "provider_configured": get_settings().ai_provider == "anthropic",
            "disclaimer": DISCLAIMER}


def _respond(db: Session, user: User, llm, text: str, tb: Toolbox, action: str, ref: str):
    audit(db, user, action, "ai", ref, None, {"mode": llm.mode, "tools": tb.calls})
    db.commit()
    return {"text": text, "mode": llm.mode, "model": llm.model, "tools_used": tb.calls, "disclaimer": DISCLAIMER}


@router.post("/explain/plot/{plot_ref}")
def explain_plot(plot_ref: str, db: DB, user: Annotated[User, Depends(ALLOWED)]):
    tb = Toolbox(db, user)
    ctx = tb.run("plot_status", {"plot": plot_ref})
    if "error" in ctx:
        raise HTTPException(404, ctx["error"])
    llm = get_llm()
    try:
        text = llm.explain(ctx, "Explain this plot's EUDR cutoff status for a compliance analyst in at most 120 words. "
                                "Say what the evidence is, how confident it is, what is uncertain, and the sensible next step.")
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    return _respond(db, user, llm, text, tb, "ai_explain_plot", plot_ref)


@router.post("/explain/supplier/{name}")
def explain_supplier(name: str, db: DB, user: Annotated[User, Depends(ALLOWED)]):
    tb = Toolbox(db, user)
    ctx = tb.run("supplier_overview", {"supplier": name})
    if "error" in ctx:
        raise HTTPException(404, ctx["error"])
    llm = get_llm()
    try:
        text = llm.explain(ctx, "Write a short due-diligence brief for this supplier (max 150 words): overall picture, "
                                "the plots that need attention and why, and recommended next steps.")
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    return _respond(db, user, llm, text, tb, "ai_explain_supplier", name)


@router.post("/ask")
def ask(body: AskIn, db: DB, user: Annotated[User, Depends(ALLOWED)]):
    tb, llm = Toolbox(db, user), get_llm()
    try:
        text = llm.ask(body.question, body.history, tb)
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    return _respond(db, user, llm, text, tb, "ai_ask", body.question[:60])
