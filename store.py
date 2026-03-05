import json
import os
from datetime import datetime
from typing import Optional
from config import CANDIDATES_DB, CHAT_HISTORY_DB

CREDENTIALS_DB = "./credentials.json"

def _load(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}

def _save(path: str, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

# ── Candidate CRUD ────────────────────────────────────────────────────────────
def get_all_candidates() -> dict:
    return _load(CANDIDATES_DB)

def get_candidate(candidate_id: str) -> Optional[dict]:
    return _load(CANDIDATES_DB).get(candidate_id)

def save_candidate(candidate: dict):
    db = _load(CANDIDATES_DB)
    db[candidate["candidate_id"]] = candidate
    _save(CANDIDATES_DB, db)

def update_candidate_field(candidate_id: str, field: str, value):
    db = _load(CANDIDATES_DB)
    if candidate_id not in db:
        raise KeyError(f"Candidate {candidate_id} not found")
    db[candidate_id][field] = value
    db[candidate_id]["updated_at"] = datetime.utcnow().isoformat()
    _save(CANDIDATES_DB, db)

def get_shortlisted_candidates() -> list:
    db = _load(CANDIDATES_DB)
    return [c for c in db.values() if c.get("status") in ("shortlisted", "in_chat", "ready_for_hr")]

# ── Chat History ──────────────────────────────────────────────────────────────
def append_chat_message(candidate_id: str, role: str, content: str):
    db = _load(CHAT_HISTORY_DB)
    if candidate_id not in db:
        db[candidate_id] = []
    db[candidate_id].append({
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow().isoformat()
    })
    _save(CHAT_HISTORY_DB, db)

def get_chat_history(candidate_id: str) -> list:
    db = _load(CHAT_HISTORY_DB)
    return db.get(candidate_id, [])

# ── Gap helpers ───────────────────────────────────────────────────────────────
def mark_gap_answered(candidate_id: str, gap_index: int, answer: str):
    db = _load(CANDIDATES_DB)
    candidate = db.get(candidate_id)
    if not candidate:
        raise KeyError(f"Candidate {candidate_id} not found")
    candidate["gaps"][gap_index]["status"] = "answered"
    candidate["gaps"][gap_index]["answer"] = answer
    candidate["updated_at"] = datetime.utcnow().isoformat()
    db[candidate_id] = candidate
    _save(CANDIDATES_DB, db)

def get_unanswered_gaps(candidate_id: str) -> list:
    candidate = get_candidate(candidate_id)
    if not candidate:
        return []
    return [
        {"index": i, **g}
        for i, g in enumerate(candidate.get("gaps", []))
        if g.get("status") != "answered"
    ]

# ── Credentials (candidate passwords) ────────────────────────────────────────
def set_candidate_password(candidate_id: str, password: str):
    db = _load(CREDENTIALS_DB)
    db[candidate_id] = password
    _save(CREDENTIALS_DB, db)

def verify_candidate_password(candidate_id: str, password: str) -> bool:
    db = _load(CREDENTIALS_DB)
    return db.get(candidate_id) == password

def get_all_credentials() -> dict:
    return _load(CREDENTIALS_DB)