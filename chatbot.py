import json
import re

from langchain_ollama import OllamaLLM

from config import OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, JOB_DESCRIPTION
from store import (
    get_candidate,
    get_unanswered_gaps,
    mark_gap_answered,
    update_candidate_field,
    append_chat_message,
)

MAX_QUESTIONS = 3

QUESTION_PROMPT = """You are a professional technical recruiter doing a short pre-screening interview.

Gap to address:
Requirement: {requirement}
Reason it's a gap: {reason}

Generate ONE short, clear, conversational interview question about this gap.
Return ONLY the question. No preamble. No explanation."""

HR_SUMMARY_PROMPT = """Write a concise HR candidate summary.

Job: Senior Python Backend Engineer
Candidate: {candidate_id}
Profile: {profile}
Initial Score: {initial_score}
Final Score: {final_score}
Interview Q&A: {gaps_with_answers}

Write exactly:
1. Candidate Overview (2 sentences)
2. Key Strengths (3 bullet points starting with -)
3. Remaining Concerns (bullet points, or "None")
4. Recommendation: HIRE / HOLD / REJECT with one sentence reason"""


def _llm():
    return OllamaLLM(
        model=OLLAMA_CHAT_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.2,
        num_predict=300,
    )


def generate_question(gap: dict) -> str:
    try:
        return _llm().invoke(QUESTION_PROMPT.format(
            requirement=gap.get("requirement", ""),
            reason=gap.get("reason", ""),
        )).strip()
    except Exception as e:
        # Fallback question if LLM fails
        return f"Could you tell me about your experience with {gap.get('requirement', 'this requirement')}?"


def _classify_answer(answer: str) -> str:
    """
    Returns: 'strong_positive', 'positive', 'neutral', 'negative', 'strong_negative'
    """
    text = answer.lower().strip()
    word_count = len(text.split())

    # Very short answers are usually dismissive / negative
    if word_count <= 4:
        # Check for definitive positives first
        if any(kw in text for kw in ["yes", "yeah", "absolutely", "sure"]):
            # Single-word yes with no detail → neutral at best
            return "neutral"
        return "strong_negative"

    # Strong negative signals
    strong_neg = [
        "no experience", "never used", "never worked", "no exposure",
        "not familiar", "unfamiliar", "don't know", "no knowledge",
        "haven't used", "havent used", "not at all", "i have no",
        "i don't have", "i dont have", "never done", "no idea",
        "limited experience", "basic only", "beginner", "just started",
        "not really", "not much",
    ]
    if any(kw in text for kw in strong_neg):
        return "strong_negative"

    # Moderate negative signals
    moderate_neg = [
        "no", "nope", "haven't", "havent", "don't", "dont",
        "limited", "minimal", "little", "rarely", "seldom",
        "only basic", "some exposure", "heard of",
    ]
    neg_count = sum(1 for kw in moderate_neg if kw in text)

    # Strong positive signals
    strong_pos = [
        "years of experience", "years experience", "production",
        "deployed", "built", "architected", "led", "designed",
        "expert", "extensive", "proficient", "advanced",
        "multiple projects", "several projects", "in-depth",
    ]
    if any(kw in text for kw in strong_pos) and neg_count == 0:
        return "strong_positive"

    # Moderate positive signals
    moderate_pos = [
        "yes", "yeah", "have experience", "i've used", "ive used",
        "i have", "familiar", "worked with", "used it", "solid",
        "comfortable", "good understanding", "hands-on",
    ]
    pos_count = sum(1 for kw in moderate_pos if kw in text)

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    else:
        # Long neutral answer
        return "neutral" if word_count > 20 else "negative"


def update_score_from_answer(gap: dict, answer: str, current_score: float) -> float:
    """
    Adjusts score based on answer quality.
    Penalties are meaningful — bad answers noticeably reduce the score.
    """
    classification = _classify_answer(answer)

    delta_map = {
        "strong_positive": +0.07,
        "positive":        +0.04,
        "neutral":         +0.00,
        "negative":        -0.08,
        "strong_negative": -0.14,
    }

    delta = delta_map.get(classification, 0.0)

    # Extra penalty for critical gaps answered poorly
    if gap.get("severity") == "critical" and classification in ("negative", "strong_negative"):
        delta -= 0.04

    new_score = round(max(0.0, min(1.0, current_score + delta)), 4)
    return new_score, classification


def generate_hr_summary(candidate_id: str) -> str:
    candidate = get_candidate(candidate_id)
    if not candidate:
        return "Candidate not found."
    profile = candidate.get("profile_json", {})
    skills = (profile.get("skills", []) + profile.get("technologies", []))[:12]
    answered = [g for g in candidate.get("gaps", []) if g.get("status") == "answered"]
    try:
        return _llm().invoke(HR_SUMMARY_PROMPT.format(
            candidate_id=candidate_id,
            profile=json.dumps({
                "name": profile.get("name"),
                "skills": skills,
                "years": profile.get("years_of_experience"),
                "roles": profile.get("past_roles", []),
            }, indent=2),
            initial_score=candidate.get("match_score", 0),
            final_score=candidate.get("final_score", candidate.get("match_score", 0)),
            gaps_with_answers=json.dumps(answered, indent=2),
        )).strip()
    except Exception as e:
        return f"_(Summary generation failed: {e})_"


class CandidateChatSession:
    def __init__(self, candidate_id: str):
        self.candidate_id = candidate_id
        self.candidate = get_candidate(candidate_id)
        if not self.candidate:
            raise ValueError(f"Candidate {candidate_id} not found")
        self.current_gap_index = None
        self.questions_asked = 0
        # Lock in the initial score BEFORE any interview changes
        self.initial_score = self.candidate.get("match_score", 0)
        # Track running score separately so we accumulate changes across all answers
        self.running_score = self.initial_score

    def start(self) -> str:
        profile = self.candidate.get("profile_json", {})
        name = profile.get("name", self.candidate_id)
        update_candidate_field(self.candidate_id, "status", "in_chat")
        # Initialize final_score to match_score so it always exists
        update_candidate_field(self.candidate_id, "final_score", self.initial_score)

        gaps = get_unanswered_gaps(self.candidate_id)
        if not gaps:
            return self._finish()

        total_q = min(len(gaps), MAX_QUESTIONS)
        greeting = (
            f"Hello **{name}**! 👋\n\n"
            f"You've been shortlisted for the **Senior Python Backend Engineer** role. "
            f"I have **{total_q} question(s)** to learn more about your background.\n\n"
            f"---\n\n"
        )
        return greeting + self._ask_next_gap()

    def _ask_next_gap(self) -> str:
        if self.questions_asked >= MAX_QUESTIONS:
            return self._finish()
        gaps = get_unanswered_gaps(self.candidate_id)
        if not gaps:
            return self._finish()

        gap = gaps[0]
        self.current_gap_index = gap["index"]
        question = generate_question(gap)
        self.questions_asked += 1

        remaining = min(len(gaps), MAX_QUESTIONS)
        progress = f"**Question {self.questions_asked} of {min(remaining + self.questions_asked - 1, MAX_QUESTIONS)}**\n\n"
        append_chat_message(self.candidate_id, "assistant", question)
        return progress + question

    def handle_answer(self, answer: str) -> str:
        if self.current_gap_index is None:
            return "Please wait for a question before answering."

        append_chat_message(self.candidate_id, "user", answer)
        mark_gap_answered(self.candidate_id, self.current_gap_index, answer)

        # Reload to get latest state
        self.candidate = get_candidate(self.candidate_id)

        gap = self.candidate["gaps"][self.current_gap_index]

        # Apply score delta to the RUNNING score (not re-read from DB each time)
        new_score, classification = update_score_from_answer(gap, answer, self.running_score)
        self.running_score = new_score

        # Persist both fields
        update_candidate_field(self.candidate_id, "match_score", self.running_score)
        update_candidate_field(self.candidate_id, "final_score", self.running_score)

        # Reload again after update
        self.candidate = get_candidate(self.candidate_id)
        self.current_gap_index = None

        # Small acknowledgment before next question (shows the score is live)
        ack = self._make_acknowledgment(classification)
        next_q = self._ask_next_gap()

        return ack + "\n\n" + next_q

    def _make_acknowledgment(self, classification: str) -> str:
        acks = {
            "strong_positive": "✅ Great — that's strong experience.",
            "positive":        "👍 Thanks for that.",
            "neutral":         "📝 Noted.",
            "negative":        "📝 Understood — noted for the review.",
            "strong_negative": "📝 Okay, that's helpful context.",
        }
        score_hint = f"_(Score updated → **{self.running_score:.0%}**)_"
        return f"{acks.get(classification, '📝 Noted.')}  {score_hint}"

    def _finish(self) -> str:
        update_candidate_field(self.candidate_id, "status", "ready_for_hr")
        update_candidate_field(self.candidate_id, "final_score", self.running_score)

        final   = self.running_score
        initial = self.initial_score
        delta   = final - initial

        if delta > 0.02:
            delta_str = f"📈 +{delta:.2f} — improved during interview"
        elif delta < -0.02:
            delta_str = f"📉 {delta:.2f} — gaps confirmed during interview"
        else:
            delta_str = "➡️ unchanged"

        summary = generate_hr_summary(self.candidate_id)

        result = (
            f"✅ **Thank you — your pre-screening is complete.**\n\n"
            f"Our HR team will review your profile and contact you within 3–5 business days.\n\n"
            f"---\n\n"
            f"### 📋 Internal HR Summary\n\n"
            f"| | |\n|---|---|\n"
            f"| **Initial Score** | {initial:.0%} |\n"
            f"| **Final Score** | **{final:.0%}** ({delta_str}) |\n\n"
            f"---\n\n{summary}\n\n"
            f"Pre-screening complete"
        )
        append_chat_message(self.candidate_id, "assistant", result)
        return result