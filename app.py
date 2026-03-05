import asyncio
from concurrent.futures import ThreadPoolExecutor
import chainlit as cl
from chainlit import Action

from config import JOB_DESCRIPTION, SHORTLIST_THRESHOLD
from ingest import ingest_cvs
from screening import run_screening
from store import get_all_candidates, get_shortlisted_candidates, get_candidate
from chatbot import CandidateChatSession

executor = ThreadPoolExecutor(max_workers=1)

HR_PASSWORD = "hr1234"

SESSION_MODE = "mode"
SESSION_CHAT = "chat_session"
SESSION_ROLE = "role"

# ─── Helpers ──────────────────────────────────────────────────────────────────

async def run_in_thread(fn, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, lambda: fn(*args, **kwargs))


def score_bar(score: float) -> str:
    pct = int(score * 100)
    filled = int(score * 12)
    bar = "▰" * filled + "▱" * (12 - filled)
    color_icon = "🟢" if score >= 0.75 else "🟡" if score >= 0.5 else "🔴"
    return f"{color_icon} `{bar}` **{pct}%**"


def status_badge(status: str) -> str:
    badges = {
        "shortlisted":  "🔵 Shortlisted",
        "in_chat":      "🟡 Interviewing",
        "ready_for_hr": "🟢 Ready for HR",
        "rejected":     "🔴 Rejected",
    }
    return badges.get(status, status)


def divider() -> str:
    return "\n\n---\n\n"


# ─── Landing Page ─────────────────────────────────────────────────────────────

async def show_landing():
    cl.user_session.set(SESSION_MODE, "landing")
    await cl.Message(
        content=(
            "# 🏢 TalentScout — AI Recruitment Platform\n\n"
            "> **Position Open:** Senior Python Backend Engineer\n\n"
            "| | |\n"
            "|---|---|\n"
            "| 🤖 AI-powered CV screening | ✅ Automated candidate interviews |\n"
            "| 📊 Smart match scoring | 🎯 Top-profile shortlisting |\n\n"
            "---\n\n"
            "**Who are you today?**\n"
            "*Select your role to continue.*"
        ),
        actions=[
            Action(name="role_candidate", payload={"role": "candidate"}, label="👤  I'm a Candidate"),
            Action(name="role_hr",        payload={"role": "hr"},        label="🔐  HR / Admin Login"),
        ],
    ).send()


# ─── Candidate Portal ─────────────────────────────────────────────────────────

async def show_candidate_portal():
    cl.user_session.set(SESSION_MODE, "candidate_menu")
    await cl.Message(
        content=(
            "## 👤 Candidate Portal\n\n"
            "### 📋 Senior Python Backend Engineer\n"
            "*TechCorp · Full-time · Remote-friendly*\n\n"
            "---\n\n"
            "**Follow these steps to complete your application:**\n\n"
            "**Step 1 →** `📤 Submit CV` — Upload your PDF for processing\n\n"
            "**Step 2 →** `🔍 Run AI Screening` — Get scored against the job requirements\n\n"
            "**Step 3 →** `💬 Start Interview` — Answer a few targeted questions\n\n"
            "---\n\n"
            "*What would you like to do?*"
        ),
        actions=[
            Action(name="candidate_ingest", payload={"a": "1"}, label="📤  Submit CV"),
            Action(name="candidate_screen", payload={"a": "1"}, label="🔍  Run AI Screening"),
            Action(name="candidate_chat",   payload={"a": "1"}, label="💬  Start Interview"),
            Action(name="back_landing",     payload={"a": "1"}, label="← Main Menu"),
        ],
    ).send()


@cl.action_callback("role_candidate")
async def on_role_candidate(action: Action):
    cl.user_session.set(SESSION_ROLE, "candidate")
    await show_candidate_portal()


@cl.action_callback("candidate_ingest")
async def on_candidate_ingest(action: Action):
    await cl.Message(content="### 📤 Submitting CVs...\n\n⏳ Parsing and indexing your documents — please wait.").send()
    messages = []
    def cb(t): messages.append(t)
    try:
        ingested = await run_in_thread(ingest_cvs, cb)
        log_lines = "\n".join(f"  {m}" for m in messages)
        await cl.Message(
            content=(
                f"### ✅ Submission Complete\n\n"
                f"**{len(ingested)} CV(s) indexed successfully.**\n\n"
                f"```\n{log_lines}\n```\n\n"
                f"> Next step: click **🔍 Run AI Screening** to score candidates against the job description."
            )
        ).send()
    except Exception as e:
        await cl.Message(content=f"### ❌ Submission Failed\n\n`{e}`\n\nPlease check that your CV folder is correctly configured.").send()
    await show_candidate_portal()


@cl.action_callback("candidate_screen")
async def on_candidate_screen(action: Action):
    await cl.Message(
        content=(
            "### 🔍 AI Screening in Progress...\n\n"
            "⏳ Analyzing CVs against the job requirements.\n"
            "This takes **2–5 minutes** — please do not close this window.\n\n"
            "_Comparing skills, experience, and technologies..._"
        )
    ).send()

    messages = []
    def cb(t): messages.append(t)

    try:
        results = await run_in_thread(run_screening, None, cb)
        results.sort(key=lambda x: x["match_score"], reverse=True)
        shortlisted = [r for r in results if r["status"] in ("shortlisted", "in_chat", "ready_for_hr")]
        rejected    = [r for r in results if r["status"] == "rejected"]

        table  = "### 📊 Screening Results\n\n"
        table += (
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Threshold | {SHORTLIST_THRESHOLD:.0%} |\n"
            f"| ✅ Shortlisted | **{len(shortlisted)}** candidates |\n"
            f"| ❌ Rejected | {len(rejected)} candidates |\n\n"
        )
        table += "---\n\n"
        table += "| # | Candidate | Match Score | Gaps | Status |\n"
        table += "|---|-----------|-------------|------|--------|\n"

        for i, r in enumerate(results, 1):
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
            table += (
                f"| {medal} | `{r['candidate_id']}` "
                f"| {score_bar(r['match_score'])} "
                f"| {len(r['gaps'])} gap(s) "
                f"| {status_badge(r['status'])} |\n"
            )

        top_names = ", ".join(f"`{r['candidate_id']}`" for r in shortlisted[:5]) or "_None_"
        table += f"\n\n> 🏆 **Top candidates eligible for interview:** {top_names}"

        await cl.Message(content=table).send()

    except Exception as e:
        await cl.Message(content=f"### ❌ Screening Failed\n\n`{e}`\n\nEnsure CVs have been submitted first.").send()

    await show_candidate_portal()


@cl.action_callback("candidate_chat")
async def on_candidate_chat(action: Action):
    all_candidates = get_all_candidates()
    ranked = sorted(
        [c for c in all_candidates.values() if c.get("status") in ("shortlisted", "in_chat")],
        key=lambda x: x["match_score"],
        reverse=True,
    )[:5]

    if not ranked:
        await cl.Message(
            content=(
                "### ⚠️ No Shortlisted Candidates\n\n"
                "There are no candidates available for interview yet.\n\n"
                "Please run **🔍 AI Screening** first so that candidates can be evaluated and shortlisted."
            )
        ).send()
        await show_candidate_portal()
        return

    lines = ["### 💬 Select a Candidate to Interview\n\n"]
    lines.append("The following candidates have been shortlisted. Select one to begin the AI interview session:\n")
    lines.append("| # | Name | ID | Score | Gaps |")
    lines.append("|---|------|----|-------|------|")

    actions = []
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, c in enumerate(ranked, 1):
        profile = c.get("profile_json", {})
        name = profile.get("name", c["candidate_id"])
        lines.append(
            f"| {medals[i-1]} | **{name}** | `{c['candidate_id']}` "
            f"| {score_bar(c['match_score'])} | {len(c.get('gaps', []))} |"
        )
        actions.append(Action(
            name="select_candidate",
            payload={"candidate_id": c["candidate_id"]},
            label=f"{medals[i-1]} {name} — {c['match_score']:.0%}",
        ))

    actions.append(Action(name="back_candidate", payload={"a": "1"}, label="← Back"))
    await cl.Message(content="\n".join(lines), actions=actions).send()


@cl.action_callback("select_candidate")
async def on_select_candidate(action: Action):
    candidate_id = action.payload.get("candidate_id")
    candidate = get_candidate(candidate_id)
    if not candidate:
        await cl.Message(content=f"### ❌ Not Found\n\nCandidate `{candidate_id}` could not be retrieved.").send()
        return

    profile = candidate.get("profile_json", {})
    gaps    = [g for g in candidate.get("gaps", []) if g.get("status") != "answered"]
    name    = profile.get("name", candidate_id)
    skills  = (profile.get("skills", []) + profile.get("technologies", []))[:6]

    await cl.Message(
        content=(
            f"### 🎯 Interview Session — {name}\n\n"
            f"| Field | Value |\n"
            f"|-------|-------|\n"
            f"| 👤 Candidate | **{name}** |\n"
            f"| 🆔 ID | `{candidate_id}` |\n"
            f"| 📊 Current Score | **{candidate['match_score']:.0%}** |\n"
            f"| 🛠️ Top Skills | {', '.join(skills) or 'N/A'} |\n"
            f"| ❓ Questions | **{min(len(gaps), 3)}** gap-filling questions |\n\n"
            f"---\n\n"
            f"_The AI interviewer will now begin. Please answer each question in the chat._"
        )
    ).send()

    try:
        session = CandidateChatSession(candidate_id)
        cl.user_session.set(SESSION_CHAT, session)
        cl.user_session.set(SESSION_MODE, "chat")
        opening = await run_in_thread(session.start)
        await cl.Message(content=opening).send()
    except Exception as e:
        await cl.Message(content=f"### ❌ Could Not Start Interview\n\n`{e}`").send()
        await show_candidate_portal()


# ─── HR Dashboard ─────────────────────────────────────────────────────────────

async def show_hr_login():
    cl.user_session.set(SESSION_MODE, "hr_login")
    await cl.Message(
        content=(
            "## 🔐 HR Admin Login\n\n"
            "Please enter the **HR password** to access the recruitment dashboard.\n\n"
            "> 🔑 Default password: `hr1234`\n\n"
            "_Type your password and press Enter._"
        )
    ).send()


async def show_hr_dashboard():
    cl.user_session.set(SESSION_MODE, "hr_dashboard")
    all_candidates = get_all_candidates()

    if not all_candidates:
        await cl.Message(
            content=(
                "## 🏠 HR Dashboard\n\n"
                "### ⚠️ No Data Available\n\n"
                "No candidates have been processed yet. Ask candidates to submit their CVs and run the AI screening first."
            ),
            actions=[
                Action(name="hr_refresh",   payload={"a": "1"}, label="🔄 Refresh"),
                Action(name="back_landing", payload={"a": "1"}, label="← Logout"),
            ]
        ).send()
        return

    ranked       = sorted(all_candidates.values(), key=lambda x: x.get("final_score", x.get("match_score", 0)), reverse=True)
    ready_for_hr = [c for c in ranked if c.get("status") == "ready_for_hr"]
    shortlisted  = [c for c in ranked if c.get("status") in ("shortlisted", "in_chat")]
    rejected     = [c for c in ranked if c.get("status") == "rejected"]
    top3         = (ready_for_hr + shortlisted)[:3]
    medals       = ["🥇", "🥈", "🥉"]

    lines = ["# 🏢 HR Recruitment Dashboard\n"]

    # ── Overview stats ──
    lines.append(
        f"| 📋 Total | ✅ Ready for HR | 🔵 Shortlisted | 🔴 Rejected |\n"
        f"|---------|----------------|----------------|-------------|\n"
        f"| **{len(all_candidates)}** | **{len(ready_for_hr)}** | **{len(shortlisted)}** | **{len(rejected)}** |\n"
    )

    lines.append("---\n")

    # ── Top 3 ──
    lines.append("## 🏆 Top Candidates — Recommended for Final Interview\n")
    if top3:
        lines.append("| Rank | Name | Final Score | Interview | Status |")
        lines.append("|------|------|-------------|-----------|--------|")
        for i, c in enumerate(top3):
            profile     = c.get("profile_json", {})
            name        = profile.get("name", c["candidate_id"])
            score       = c.get("final_score", c.get("match_score", 0))
            interviewed = "✅ Completed" if c.get("status") == "ready_for_hr" else "⏳ Pending"
            lines.append(
                f"| {medals[i]} | **{name}** | {score_bar(score)} | {interviewed} | {status_badge(c['status'])} |"
            )
    else:
        lines.append("_No candidates are ready yet. Run screening and interviews first._\n")

    lines.append("\n---\n")

    # ── Detailed cards ──
    if ready_for_hr:
        lines.append("## 📋 Interview Summaries\n")
        for c in ready_for_hr[:3]:
            profile  = c.get("profile_json", {})
            name     = profile.get("name", c["candidate_id"])
            initial  = c.get("match_score", 0)
            final    = c.get("final_score", initial)
            delta    = final - initial
            delta_s  = (f"📈 +{delta:.2f}" if delta > 0 else f"📉 {delta:.2f}") if delta != 0 else "➡️ unchanged"
            skills   = (profile.get("skills", []) + profile.get("technologies", []))[:6]
            answered = [g for g in c.get("gaps", []) if g.get("status") == "answered"]

            lines.append(f"### {'🥇' if c == top3[0] else '👤'} {name} — `{c['candidate_id']}`\n")
            lines.append(
                f"| Field | Value |\n"
                f"|-------|-------|\n"
                f"| 📊 Initial Score | {initial:.0%} |\n"
                f"| 🎯 Final Score | **{final:.0%}** ({delta_s}) |\n"
                f"| 🛠️ Top Skills | {', '.join(skills)} |\n"
                f"| 💼 Experience | {profile.get('years_of_experience', 'N/A')} years |\n"
            )

            if answered:
                lines.append("\n**Interview Q&A**\n")
                for g in answered:
                    lines.append(f"> ❓ **Q:** {g.get('requirement', '')}")
                    lines.append(f"> 💬 **A:** {g.get('answer', '_No answer recorded_')}\n")

            lines.append("\n---\n")

    # ── All candidates ──
    lines.append("## 📊 All Candidates\n")
    lines.append("| # | Candidate | Final Score | Status | Interviewed |")
    lines.append("|---|-----------|-------------|--------|-------------|")
    for i, c in enumerate(ranked, 1):
        profile      = c.get("profile_json", {})
        name         = profile.get("name", c["candidate_id"])
        score        = c.get("final_score", c.get("match_score", 0))
        interviewed  = "✅" if c.get("status") == "ready_for_hr" else "—"
        lines.append(
            f"| {i} | **{name}** | {score_bar(score)} | {status_badge(c['status'])} | {interviewed} |"
        )

    await cl.Message(
        content="\n".join(lines),
        actions=[
            Action(name="hr_refresh",   payload={"a": "1"}, label="🔄 Refresh Dashboard"),
            Action(name="back_landing", payload={"a": "1"}, label="← Logout"),
        ]
    ).send()


@cl.action_callback("role_hr")
async def on_role_hr(action: Action):
    cl.user_session.set(SESSION_ROLE, "hr")
    await show_hr_login()


@cl.action_callback("hr_refresh")
async def on_hr_refresh(action: Action):
    await show_hr_dashboard()


@cl.action_callback("back_landing")
async def on_back_landing(action: Action):
    await show_landing()


@cl.action_callback("back_candidate")
async def on_back_candidate(action: Action):
    await show_candidate_portal()


# ─── Lifecycle ────────────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_start():
    await show_landing()


@cl.on_message
async def on_message(message: cl.Message):
    mode = cl.user_session.get(SESSION_MODE, "landing")
    text = message.content.strip()

    # ── HR Login ──────────────────────────────────────────────────────────────
    if mode == "hr_login":
        if text == HR_PASSWORD:
            await cl.Message(content="### ✅ Access Granted\n\nWelcome back. Loading your dashboard...").send()
            await show_hr_dashboard()
        else:
            await cl.Message(
                content=(
                    "### ❌ Incorrect Password\n\n"
                    "That password is incorrect. Please try again.\n\n"
                    "> 💡 Hint: default is `hr1234`"
                )
            ).send()
        return

    # ── Candidate Chat ────────────────────────────────────────────────────────
    if mode == "chat":
        session: CandidateChatSession = cl.user_session.get(SESSION_CHAT)
        if not session:
            await cl.Message(content="### ❌ Session Expired\n\nYour session was lost. Please start a new interview.").send()
            await show_candidate_portal()
            return

        async with cl.Step(name="🤖 AI Interviewer is thinking..."):
            response = await run_in_thread(session.handle_answer, text)

        await cl.Message(content=response).send()

        if "Pre-screening complete" in response:
            cl.user_session.set(SESSION_MODE, "candidate_menu")
            await cl.Message(
                content=(
                    "---\n\n"
                    "### ✅ Interview Recorded\n\n"
                    "Your responses have been saved. Our HR team will review your profile within 3–5 business days.\n\n"
                    "_What would you like to do next?_"
                ),
                actions=[
                    Action(name="candidate_chat", payload={"a": "1"}, label="💬 Interview Another Candidate"),
                    Action(name="back_landing",   payload={"a": "1"}, label="← Main Menu"),
                ]
            ).send()
        return

    # ── Default ───────────────────────────────────────────────────────────────
    await cl.Message(
        content="👆 Please use the **buttons above** to navigate the platform."
    ).send()