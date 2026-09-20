"""Persistent per-session conversation state so a session_id can be resumed across
process invocations (required for the JSONL adapter contract)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config


@dataclass
class Slots:
    product_line: Optional[str] = None  # "home" | "pro"
    device: Optional[str] = None  # e.g. "R1", "N1", "R5 Pro", "N5 Pro"
    connection: Optional[str] = None  # "wireless" | "ethernet"
    symptom: Optional[str] = None
    led_state: Optional[str] = None
    error_code: Optional[str] = None


@dataclass
class Session:
    session_id: str
    turns: List[Dict[str, str]] = field(default_factory=list)
    slots: Slots = field(default_factory=Slots)
    attempted_steps: List[str] = field(default_factory=list)
    pending_confirmation: Optional[str] = None  # description of the action awaiting confirmation
    resolved: bool = False
    escalated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Session":
        slots = Slots(**d.get("slots", {}))
        return Session(
            session_id=d["session_id"],
            turns=d.get("turns", []),
            slots=slots,
            attempted_steps=d.get("attempted_steps", []),
            pending_confirmation=d.get("pending_confirmation"),
            resolved=d.get("resolved", False),
            escalated=d.get("escalated", False),
        )


def _path(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "default"
    return config.DATA_DIR / "sessions" / f"{safe}.json"


def load_session(session_id: str) -> Session:
    path = _path(session_id)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return Session.from_dict(json.load(f))
    return Session(session_id=session_id)


def save_session(session: Session) -> None:
    path = _path(session.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session.to_dict(), f, indent=2)
