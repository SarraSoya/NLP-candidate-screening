import re
import uuid
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from chatbot import CandidateChatSession
from config import ADMIN_PASSWORD, CV_FOLDER, FLASK_SECRET_KEY, JOB_DESCRIPTION, SHORTLIST_THRESHOLD
from store import get_all_candidates, get_candidate, get_chat_history, update_candidate_fields

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

ACTIVE_CHAT_SESSIONS = {}
ADMIN_PIPELINE_LOGS = {}


def _browser_session_key() -> str:
    if "browser_session_id" not in session:
        session["browser_session_id"] = uuid.uuid4().hex
    return session["browser_session_id"]


def _normalize_candidate_id(raw_value: str) -> str:
    value = (raw_value or "").strip().lower()
    value = re.sub(r"\s+", "_", value)
    return re.sub(r"[^a-z0-9_]", "", value)


def _normalize_candidate_name(raw_value: str) -> str:
    value = (raw_value or "").strip().lower()
    value = re.sub(r"[_\-\s]+", " ", value)
    value = re.sub(r"[^a-z0-9 ]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _candidate_name(candidate: dict) -> str:
    profile = candidate.get("profile_json", {})
    if profile.get("name"):
        return profile["name"]
    fallback = candidate.get("candidate_id", "Candidate").replace("_", " ").strip()
    return fallback.title()


def _candidate_cv_path(candidate: dict | None) -> Path | None:
    if not candidate:
        return None

    cv_dir = Path(CV_FOLDER).resolve()
    source_file = candidate.get("source_file")
    if source_file:
        candidate_path = (cv_dir / source_file).resolve()
        if candidate_path.is_file() and cv_dir in candidate_path.parents:
            return candidate_path

    normalized_id = _normalize_candidate_id(candidate.get("candidate_id", ""))
    for pdf_path in cv_dir.glob("*.pdf"):
        if _normalize_candidate_id(pdf_path.stem) == normalized_id:
            return pdf_path.resolve()
    return None


def _ensure_candidate_profile(candidate: dict | None):
    if not candidate:
        return candidate

    has_profile = bool(candidate.get("profile_json"))
    has_preview = bool(candidate.get("preview"))
    has_source = bool(candidate.get("source_file"))
    if has_profile and has_preview and has_source:
        return candidate

    try:
        from screening import build_candidate_profile, fetch_candidate_cv_context

        source_file, cv_text = fetch_candidate_cv_context(candidate["candidate_id"])
        if not cv_text:
            return candidate

        updates = {
            "source_file": source_file or candidate.get("source_file", ""),
            "preview": " ".join(cv_text.split())[:700].strip(),
            "profile_json": build_candidate_profile(candidate["candidate_id"], cv_text, source_file),
        }
        update_candidate_fields(candidate["candidate_id"], updates)
        return get_candidate(candidate["candidate_id"])
    except Exception:
        return candidate


def _find_candidate_by_name(raw_name: str):
    lookup = _normalize_candidate_name(raw_name)
    if not lookup:
        return None

    candidates = sorted(get_all_candidates().values(), key=_sort_score, reverse=True)

    def candidate_keys(candidate: dict) -> set[str]:
        return {
            key
            for key in {
                _normalize_candidate_name(_candidate_name(candidate)),
                _normalize_candidate_name(candidate.get("candidate_id", "")),
                _normalize_candidate_name(candidate.get("candidate_id", "").replace("_", " ")),
            }
            if key
        }

    for candidate in candidates:
        if candidate.get("status") in ("shortlisted", "in_chat", "ready_for_hr") and lookup in candidate_keys(candidate):
            return candidate

    for candidate in candidates:
        if lookup in candidate_keys(candidate):
            return candidate

    return None


def _screening_score(candidate: dict):
    score = candidate.get("screening_score")
    if score is None:
        score = candidate.get("match_score")
    return score


def _final_score(candidate: dict):
    score = candidate.get("final_score")
    if score is None:
        score = _screening_score(candidate)
    return score


def _sort_score(candidate: dict) -> float:
    return float(_final_score(candidate) or 0.0)


def _status_label(status: str) -> str:
    labels = {
        "pending": "Pending",
        "shortlisted": "Shortlisted",
        "in_chat": "Interview in Progress",
        "ready_for_hr": "Review Ready",
        "rejected": "Rejected",
    }
    return labels.get(status, status.replace("_", " ").title())


def _score_label(score) -> str:
    if score is None:
        return "N/A"
    return f"{round(float(score) * 100)}%"


def _candidate_safe_message(content: str):
    if not content:
        return None

    if "Internal HR Summary" in content:
        return (
            "Thank you - your pre-screening is complete.\n\n"
            "Your answers have been saved for the recruiting team."
        )

    cleaned_lines = []
    for line in content.splitlines():
        if "Score updated" in line or "Initial Score" in line or "Final Score" in line:
            continue
        if line.strip().startswith("### Internal HR Summary"):
            continue
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned or None


def _candidate_messages(candidate_id: str) -> list[dict]:
    visible_messages = []
    for message in get_chat_history(candidate_id):
        safe_content = _candidate_safe_message(message.get("content", ""))
        if safe_content:
            visible_messages.append(
                {
                    "role": message.get("role", "assistant"),
                    "content": safe_content,
                    "timestamp": message.get("timestamp"),
                }
            )
    return visible_messages


def _eligible_candidates() -> list[dict]:
    candidates = list(get_all_candidates().values())
    return sorted(
        [c for c in candidates if c.get("status") in ("shortlisted", "in_chat", "ready_for_hr")],
        key=_sort_score,
        reverse=True,
    )


def _candidate_dashboard_payload(candidate_id: str) -> dict:
    candidate = get_candidate(candidate_id)
    unanswered = [g for g in candidate.get("gaps", []) if g.get("status") != "answered"]
    answered = [g for g in candidate.get("gaps", []) if g.get("status") == "answered"]
    browser_key = _browser_session_key()
    active_session = ACTIVE_CHAT_SESSIONS.get(browser_key)
    chat_active = bool(active_session and active_session.candidate_id == candidate_id)

    return {
        "candidate": candidate,
        "candidate_name": _candidate_name(candidate),
        "status_label": _status_label(candidate.get("status", "pending")),
        "messages": _candidate_messages(candidate_id),
        "answered_count": len(answered),
        "remaining_count": min(len(unanswered), 3),
        "can_interview": candidate.get("status") in ("shortlisted", "in_chat"),
        "interview_complete": candidate.get("status") == "ready_for_hr" or not unanswered,
        "chat_active": chat_active,
        "question_limit": 3,
    }


def candidate_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        candidate_id = session.get("candidate_id")
        if not candidate_id or not get_candidate(candidate_id):
            flash("Please identify yourself as a candidate first.", "error")
            return redirect(url_for("landing", role="candidate"))
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_authenticated"):
            flash("Please sign in as admin to access the dashboard.", "error")
            return redirect(url_for("landing", role="admin"))
        return fn(*args, **kwargs)

    return wrapper


@app.context_processor
def inject_helpers():
    return {
        "score_label": _score_label,
        "status_label": _status_label,
        "candidate_name": _candidate_name,
    }


@app.route("/")
def landing():
    return render_template(
        "landing.html",
        active_role=request.args.get("role", "candidate"),
        candidate_name_value=request.args.get("name", ""),
    )


@app.route("/candidate/login", methods=["GET", "POST"])
def candidate_login():
    if request.method == "GET":
        return redirect(url_for("landing", role="candidate", name=request.args.get("name", "")))

    if request.method == "POST":
        raw_name = request.form.get("candidate_name", "")
        candidate = _find_candidate_by_name(raw_name)

        if not candidate:
            flash("Candidate name not found. Please enter the same name used for the application.", "error")
            return redirect(url_for("landing", role="candidate", name=raw_name))

        if candidate.get("status") == "pending":
            flash("Your application has not been screened yet. Please come back after the admin runs screening.", "error")
            return redirect(url_for("landing", role="candidate", name=raw_name))

        session["candidate_id"] = candidate["candidate_id"]
        session.pop("admin_authenticated", None)
        return redirect(url_for("candidate_portal"))


@app.route("/candidate")
@candidate_required
def candidate_portal():
    payload = _candidate_dashboard_payload(session["candidate_id"])
    return render_template("candidate_portal.html", **payload)


@app.post("/candidate/start")
@candidate_required
def candidate_start():
    candidate_id = session["candidate_id"]
    candidate = get_candidate(candidate_id)
    unanswered = [g for g in candidate.get("gaps", []) if g.get("status") != "answered"]

    if candidate.get("status") not in ("shortlisted", "in_chat"):
        flash("This interview is not available right now.", "error")
        return redirect(url_for("candidate_portal"))

    if not unanswered:
        flash("Your pre-screening has already been completed.", "info")
        return redirect(url_for("candidate_portal"))

    browser_key = _browser_session_key()
    chat_session = CandidateChatSession(candidate_id)
    chat_session.start()
    ACTIVE_CHAT_SESSIONS[browser_key] = chat_session
    flash("Your interview has started. Answer the question below.", "success")
    return redirect(url_for("candidate_portal"))


@app.post("/candidate/message")
@candidate_required
def candidate_message():
    answer = (request.form.get("answer") or "").strip()
    if not answer:
        flash("Please enter an answer before sending.", "error")
        return redirect(url_for("candidate_portal"))

    browser_key = _browser_session_key()
    chat_session = ACTIVE_CHAT_SESSIONS.get(browser_key)

    if not chat_session or chat_session.candidate_id != session["candidate_id"]:
        flash("The interview session expired. Please start or resume it again.", "error")
        return redirect(url_for("candidate_portal"))

    response = chat_session.handle_answer(answer)
    if "Pre-screening complete" in response:
        ACTIVE_CHAT_SESSIONS.pop(browser_key, None)
        flash("Your interview is complete. Thank you.", "success")

    return redirect(url_for("candidate_portal"))


@app.post("/candidate/logout")
@candidate_required
def candidate_logout():
    ACTIVE_CHAT_SESSIONS.pop(_browser_session_key(), None)
    session.pop("candidate_id", None)
    flash("You have been signed out of the candidate portal.", "info")
    return redirect(url_for("landing"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET":
        return redirect(url_for("landing", role="admin"))

    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_authenticated"] = True
            session.pop("candidate_id", None)
            flash("Admin access granted.", "success")
            return redirect(url_for("admin_dashboard"))

        flash("Incorrect admin password.", "error")
        return redirect(url_for("landing", role="admin"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    browser_key = _browser_session_key()
    all_candidates = sorted(get_all_candidates().values(), key=_sort_score, reverse=True)
    selected_candidate_id = request.args.get("candidate_id") or (all_candidates[0]["candidate_id"] if all_candidates else None)
    selected_candidate = get_candidate(selected_candidate_id) if selected_candidate_id else None
    selected_candidate = _ensure_candidate_profile(selected_candidate)

    shortlisted = [c for c in all_candidates if c.get("status") in ("shortlisted", "in_chat")]
    ready = [c for c in all_candidates if c.get("status") == "ready_for_hr"]
    rejected = [c for c in all_candidates if c.get("status") == "rejected"]

    return render_template(
        "admin_dashboard.html",
        candidates=all_candidates,
        selected_candidate=selected_candidate,
        selected_candidate_name=_candidate_name(selected_candidate) if selected_candidate else None,
        selected_messages=get_chat_history(selected_candidate_id) if selected_candidate_id else [],
        stats={
            "total": len(all_candidates),
            "shortlisted": len(shortlisted),
            "ready": len(ready),
            "rejected": len(rejected),
            "threshold": f"{round(SHORTLIST_THRESHOLD * 100)}%",
        },
        screening_score=_screening_score,
        final_score=_final_score,
        candidate_name=_candidate_name,
        admin_logs=ADMIN_PIPELINE_LOGS.get(browser_key, []),
        job_description=JOB_DESCRIPTION.strip(),
    )


@app.get("/admin/cv/<candidate_id>")
@admin_required
def admin_candidate_cv(candidate_id: str):
    candidate = get_candidate(candidate_id)
    if not candidate:
        abort(404)

    candidate = _ensure_candidate_profile(candidate)
    cv_path = _candidate_cv_path(candidate)
    if not cv_path or not cv_path.exists():
        abort(404)

    return send_file(cv_path, mimetype="application/pdf", as_attachment=False, download_name=cv_path.name)


@app.post("/admin/ingest")
@admin_required
def admin_ingest():
    from ingest import ingest_cvs

    browser_key = _browser_session_key()
    logs = []

    def callback(message: str):
        logs.append(message)

    try:
        ingested = ingest_cvs(progress_callback=callback)
        flash(f"Ingestion finished. {len(ingested)} candidate CV(s) were indexed.", "success")
    except Exception as exc:
        flash(f"Ingestion failed: {exc}", "error")

    ADMIN_PIPELINE_LOGS[browser_key] = logs
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/screen")
@admin_required
def admin_screen():
    from screening import run_screening

    browser_key = _browser_session_key()
    logs = []

    def callback(message: str):
        logs.append(message)

    try:
        results = run_screening(progress_callback=callback)
        flash(f"Screening finished. {len(results)} candidate record(s) were updated.", "success")
    except Exception as exc:
        flash(f"Screening failed: {exc}", "error")

    ADMIN_PIPELINE_LOGS[browser_key] = logs
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/logout")
@admin_required
def admin_logout():
    ADMIN_PIPELINE_LOGS.pop(_browser_session_key(), None)
    session.pop("admin_authenticated", None)
    flash("Admin session closed.", "info")
    return redirect(url_for("landing"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
