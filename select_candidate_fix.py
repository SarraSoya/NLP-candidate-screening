# Replace your existing on_select_candidate with this version.
# The key fix: wrap session.start() in try/except and show the error clearly,
# so you know immediately if Ollama is down or the candidate ID is wrong.

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

    # ── Start session ──────────────────────────────────────────────────────────
    try:
        session = CandidateChatSession(candidate_id)
    except Exception as e:
        await cl.Message(
            content=(
                f"### ❌ Session Error\n\n"
                f"Could not create interview session for `{candidate_id}`:\n\n"
                f"```\n{e}\n```"
            )
        ).send()
        await show_candidate_portal()
        return

    cl.user_session.set(SESSION_CHAT, session)
    cl.user_session.set(SESSION_MODE, "chat")

    # ── Generate opening question ──────────────────────────────────────────────
    try:
        async with cl.Step(name="🤖 AI Interviewer preparing questions..."):
            opening = await run_in_thread(session.start)
        await cl.Message(content=opening).send()
    except Exception as e:
        await cl.Message(
            content=(
                f"### ❌ Could Not Start Interview\n\n"
                f"The AI interviewer failed to generate the first question:\n\n"
                f"```\n{e}\n```\n\n"
                f"**Likely causes:**\n"
                f"- Ollama is not running → start it with `ollama serve`\n"
                f"- Model `{OLLAMA_CHAT_MODEL}` is not pulled → run `ollama pull {OLLAMA_CHAT_MODEL}`\n"
                f"- Candidate has no unanswered gaps left"
            )
        ).send()
        cl.user_session.set(SESSION_MODE, "candidate_menu")
        await show_candidate_portal()
