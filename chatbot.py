import json

from config import OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL
from store import (
    append_chat_message,
    get_candidate,
    get_unanswered_gaps,
    mark_gap_answered,
    update_candidate_fields,
)

MAX_QUESTIONS = 3

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
    from langchain_ollama import OllamaLLM

    return OllamaLLM(
        model=OLLAMA_CHAT_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.2,
        num_predict=300,
    )


def _normalized_requirement(gap: dict) -> str:
    return (gap.get("requirement") or "").strip().lower()


def generate_question(gap: dict) -> str:
    requirement = (gap.get("requirement") or "this requirement").strip()
    normalized = _normalized_requirement(gap)

    if "years of relevant experience" in normalized:
        return (
            "Could you summarize your most relevant backend experience and mention roughly how many years "
            "you have worked with Python in production?"
        )

    if "python backend framework" in normalized:
        return (
            "Can you describe a project where you used FastAPI or Django for backend work? "
            "Please mention what you built and your role."
        )

    if "rest" in normalized:
        return (
            "Can you describe your experience designing or building REST APIs? "
            "Please mention one concrete API or service you worked on."
        )

    if "message queue" in normalized or "rabbitmq" in normalized or "kafka" in normalized:
        return (
            "Can you describe any hands-on experience you have with RabbitMQ or Kafka? "
            "Please mention the use case and what you implemented."
        )

    if "cloud platform" in normalized or normalized in {"aws", "gcp", "azure"}:
        return (
            f"Can you describe your hands-on experience with {requirement}? "
            "Please mention the cloud services you used and in what project."
        )

    if any(term in normalized for term in ["docker", "kubernetes", "terraform", "jenkins", "github actions", "ci/cd"]):
        return (
            f"Can you describe your practical experience with {requirement}? "
            "Please mention the environment, tools, and what you personally handled."
        )

    if any(term in normalized for term in ["postgres", "redis", "mongodb", "mysql"]):
        return (
            f"Can you describe your experience with {requirement} in production? "
            "Please mention the type of system and how you used it."
        )

    if "microservices" in normalized or "distributed systems" in normalized or "event-driven" in normalized:
        return (
            f"Can you give a concrete example of work you did with {requirement}? "
            "Please mention the architecture and your responsibilities."
        )

    if "testing" in normalized or "tdd" in normalized or "pytest" in normalized:
        return (
            f"Can you describe your experience with {requirement}? "
            "Please mention how you applied it in a real project."
        )

    if "communication" in normalized or "problem-solving" in normalized:
        return (
            f"Can you share an example that demonstrates your {requirement.lower()}? "
            "Please describe the situation, what you did, and the outcome."
        )

    if "data pipelines" in normalized or "ml model serving" in normalized:
        return (
            f"Do you have experience with {requirement.lower()}? "
            "Please mention one relevant project and what you worked on."
        )

    return (
        f"Can you describe any hands-on experience you have with {requirement}? "
        "Please mention a concrete project, your role, and the tools you used."
    )


def _classify_answer(answer: str) -> str:
    text = answer.lower().strip()
    word_count = len(text.split())

    if word_count <= 4:
        if any(kw in text for kw in ["yes", "yeah", "absolutely", "sure"]):
            return "neutral"
        return "strong_negative"

    strong_neg = [
        "no experience",
        "never used",
        "never worked",
        "no exposure",
        "not familiar",
        "unfamiliar",
        "don't know",
        "no knowledge",
        "haven't used",
        "havent used",
        "not at all",
        "i have no",
        "i don't have",
        "i dont have",
        "never done",
        "no idea",
        "limited experience",
        "basic only",
        "beginner",
        "just started",
        "not really",
        "not much",
    ]
    if any(kw in text for kw in strong_neg):
        return "strong_negative"

    moderate_neg = [
        "no",
        "nope",
        "haven't",
        "havent",
        "don't",
        "dont",
        "limited",
        "minimal",
        "little",
        "rarely",
        "seldom",
        "only basic",
        "some exposure",
        "heard of",
    ]
    neg_count = sum(1 for kw in moderate_neg if kw in text)

    strong_pos = [
        "years of experience",
        "years experience",
        "production",
        "deployed",
        "built",
        "architected",
        "led",
        "designed",
        "expert",
        "extensive",
        "proficient",
        "advanced",
        "multiple projects",
        "several projects",
        "in-depth",
    ]
    if any(kw in text for kw in strong_pos) and neg_count == 0:
        return "strong_positive"

    moderate_pos = [
        "yes",
        "yeah",
        "have experience",
        "i've used",
        "ive used",
        "i have",
        "familiar",
        "worked with",
        "used it",
        "solid",
        "comfortable",
        "good understanding",
        "hands-on",
    ]
    pos_count = sum(1 for kw in moderate_pos if kw in text)

    if pos_count > neg_count:
        return "positive"
    if neg_count > pos_count:
        return "negative"
    return "neutral" if word_count > 20 else "negative"


def update_score_from_answer(gap: dict, answer: str, current_score: float, initial_score: float):
    classification = _classify_answer(answer)

    base_delta_map = {
        "strong_positive": +0.05,
        "positive": +0.03,
        "neutral": +0.00,
        "negative": -0.05,
        "strong_negative": -0.09,
    }
    severity_scale = {
        "critical": 1.0,
        "important": 0.7,
        "bonus": 0.4,
    }

    delta = base_delta_map.get(classification, 0.0) * severity_scale.get(gap.get("severity"), 0.7)

    gap_weight = float(gap.get("weight", 1.0) or 1.0)
    normalized_weight = max(0.35, min(1.0, gap_weight))
    delta *= normalized_weight

    # Keep the interview influential, but prevent a few answers from swinging
    # the overall score too far away from the initial screening result.
    lower_bound = max(0.0, initial_score - 0.15)
    upper_bound = min(1.0, initial_score + 0.15)

    new_score = round(min(upper_bound, max(lower_bound, current_score + delta)), 4)
    return new_score, classification, round(delta, 4)


def generate_hr_summary(candidate_id: str) -> str:
    candidate = get_candidate(candidate_id)
    if not candidate:
        return "Candidate not found."

    profile = candidate.get("profile_json", {})
    skills = (profile.get("skills", []) + profile.get("technologies", []))[:12]
    answered = [g for g in candidate.get("gaps", []) if g.get("status") == "answered"]

    try:
        return _llm().invoke(
            HR_SUMMARY_PROMPT.format(
                candidate_id=candidate_id,
                profile=json.dumps(
                    {
                        "name": profile.get("name"),
                        "skills": skills,
                        "years": profile.get("years_of_experience"),
                        "roles": profile.get("past_roles", []),
                    },
                    indent=2,
                ),
                initial_score=candidate.get("screening_score", candidate.get("match_score", 0)),
                final_score=candidate.get(
                    "final_score",
                    candidate.get("screening_score", candidate.get("match_score", 0)),
                ),
                gaps_with_answers=json.dumps(answered, indent=2),
            )
        ).strip()
    except Exception:
        strengths = []
        if skills:
            strengths.append(f"- Relevant skills mentioned: {', '.join(skills[:5])}")
        if profile.get("years_of_experience"):
            strengths.append(f"- Reported experience: {profile.get('years_of_experience')} years")
        if not strengths:
            strengths.append("- CV metadata is limited, so the review relies mostly on the screening output")

        concerns = []
        unanswered_gaps = [g for g in candidate.get("gaps", []) if g.get("status") != "answered"]
        if answered:
            concerns.extend(
                f"- Gap discussed: {g.get('requirement', 'requirement')} -> {g.get('answer', 'no answer')}"
                for g in answered[:3]
            )
        elif unanswered_gaps:
            concerns.extend(
                f"- Unresolved gap: {g.get('requirement', 'requirement')}"
                for g in unanswered_gaps[:3]
            )

        if not concerns:
            concerns.append("None")

        final_score = candidate.get(
            "final_score",
            candidate.get("screening_score", candidate.get("match_score", 0)),
        ) or 0
        recommendation = "HIRE" if final_score >= 0.75 else "HOLD" if final_score >= 0.5 else "REJECT"

        return "\n".join(
            [
                "1. Candidate Overview",
                (
                    f"{profile.get('name', candidate_id)} is being reviewed for the Senior Python Backend Engineer role. "
                    f"The profile includes {len(answered)} answered interview gap question(s)."
                ),
                "",
                "2. Key Strengths",
                *strengths[:3],
                "",
                "3. Remaining Concerns",
                *concerns[:3],
                "",
                "4. Recommendation",
                f"{recommendation} based on the available screening evidence and interview answers.",
            ]
        )


class CandidateChatSession:
    def __init__(self, candidate_id: str):
        self.candidate_id = candidate_id
        self.candidate = get_candidate(candidate_id)
        if not self.candidate:
            raise ValueError(f"Candidate {candidate_id} not found")

        self.current_gap_index = None
        self.questions_asked = 0
        self.initial_score = self.candidate.get("screening_score")
        if self.initial_score is None:
            self.initial_score = self.candidate.get("match_score", 0)

        existing_final = self.candidate.get("final_score")
        self.running_score = existing_final if existing_final is not None else self.initial_score

    def start(self) -> str:
        profile = self.candidate.get("profile_json", {})
        name = profile.get("name", self.candidate_id)

        update_candidate_fields(
            self.candidate_id,
            {
                "status": "in_chat",
                "screening_score": self.initial_score,
                "final_score": self.running_score,
                "hr_summary": "",
            },
        )

        gaps = get_unanswered_gaps(self.candidate_id)
        if not gaps:
            return self._finish()

        total_q = min(len(gaps), MAX_QUESTIONS)
        greeting = (
            f"Hello {name}!\n\n"
            f"You have {total_q} follow-up question(s) based on the job requirements.\n\n"
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
        self.questions_asked += 1
        question = generate_question(gap)
        append_chat_message(self.candidate_id, "assistant", question)
        return f"Question {self.questions_asked}: {question}"

    def handle_answer(self, answer: str) -> str:
        if self.current_gap_index is None:
            return "Please wait for the next question before answering."

        append_chat_message(self.candidate_id, "user", answer)
        mark_gap_answered(self.candidate_id, self.current_gap_index, answer)

        self.candidate = get_candidate(self.candidate_id)
        gap = self.candidate["gaps"][self.current_gap_index]

        new_score, classification, delta = update_score_from_answer(
            gap,
            answer,
            self.running_score,
            self.initial_score,
        )
        self.running_score = new_score
        self.candidate["gaps"][self.current_gap_index]["answer_classification"] = classification
        self.candidate["gaps"][self.current_gap_index]["score_delta"] = delta

        update_candidate_fields(
            self.candidate_id,
            {
                "gaps": self.candidate["gaps"],
                "screening_score": self.initial_score,
                "final_score": self.running_score,
            },
        )

        self.candidate = get_candidate(self.candidate_id)
        self.current_gap_index = None

        ack = self._make_acknowledgment(classification)
        next_q = self._ask_next_gap()
        return f"{ack}\n\n{next_q}"

    def _make_acknowledgment(self, classification: str) -> str:
        acks = {
            "strong_positive": "Thanks, that gives me good context.",
            "positive": "Thanks for sharing that.",
            "neutral": "Noted, thank you.",
            "negative": "Understood, thank you for clarifying.",
            "strong_negative": "Thanks, that is helpful to know.",
        }
        return acks.get(classification, "Noted, thank you.")

    def _finish(self) -> str:
        summary = generate_hr_summary(self.candidate_id)
        update_candidate_fields(
            self.candidate_id,
            {
                "status": "ready_for_hr",
                "screening_score": self.initial_score,
                "final_score": self.running_score,
                "hr_summary": summary,
            },
        )

        result = (
            "Thank you - your pre-screening is complete.\n\n"
            "Your answers have been saved for the recruiting team.\n\n"
            "We will contact you if there is a next step.\n\n"
            "Pre-screening complete"
        )
        append_chat_message(self.candidate_id, "assistant", result)
        return result
