import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from config import (
    CV_FOLDER,
    JOB_DESCRIPTION,
    OLLAMA_BASE_URL,
    OLLAMA_EMBED_MODEL,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE,
    SHORTLIST_THRESHOLD,
    TOP_K_CHUNKS,
)
from store import get_candidate, save_candidate


# -----------------------------
# Helpers
# -----------------------------

def _embeddings():
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(model=OLLAMA_EMBED_MODEL, base_url=OLLAMA_BASE_URL)


def _namespace_key() -> str:
    """
    Keep namespace consistent with Pinecone semantics:
    - Many SDKs treat "" as the default namespace
    - Your metadata and UI showed "__default__"
    We'll normalize to "__default__" for display/storage, but query with "".
    """
    if PINECONE_NAMESPACE in ("", "__default__", None):
        return ""  # Pinecone default namespace
    return PINECONE_NAMESPACE


def _normalize_display_namespace() -> str:
    return "__default__" if PINECONE_NAMESPACE in ("", "__default__", None) else PINECONE_NAMESPACE


def _safe_get_metadata(match) -> dict:
    if hasattr(match, "metadata"):
        return match.metadata or {}
    return match.get("metadata", {}) or {}


def _safe_get_score(match) -> float:
    if hasattr(match, "score"):
        return float(match.score)
    return float(match.get("score", 0.0))


def _safe_get_id(match) -> str:
    if hasattr(match, "id"):
        return str(match.id)
    return str(match.get("id", ""))


# -----------------------------
# Candidate discovery (fast)
# -----------------------------

def get_all_candidate_ids_from_pinecone(progress_callback: Optional[Callable[[str], None]] = None) -> List[str]:
    """
    Best-effort candidate listing.
    Pinecone doesn't always support scanning all vectors efficiently depending on plan.
    We try list+fetch; if it fails, we do a few broad queries with random vectors.
    """
    from pinecone import Pinecone

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    ns = _namespace_key()

    seen = set()

    try:
        if progress_callback:
            progress_callback("Reading vector IDs (list+fetch)...")

        for id_batch in index.list(namespace=ns):
            ids = id_batch if isinstance(id_batch, list) else [id_batch]
            if not ids:
                continue
            fetch_result = index.fetch(ids=ids, namespace=ns)
            vectors = fetch_result.vectors if hasattr(fetch_result, "vectors") else fetch_result.get("vectors", {})
            for _, vec in vectors.items():
                md = vec.metadata if hasattr(vec, "metadata") else vec.get("metadata", {})
                cid = md.get("candidate_id") if isinstance(md, dict) else getattr(md, "candidate_id", None)
                if cid:
                    seen.add(cid)

        if seen:
            return sorted(seen)
    except Exception as exc:
        if progress_callback:
            progress_callback(f"list+fetch failed ({exc}). Using fallback sampling...")

    import random

    dims = 768  # nomic-embed-text
    for _ in range(4):
        dummy = [random.uniform(-0.01, 0.01) for _ in range(dims)]
        try:
            res = index.query(
                vector=dummy,
                top_k=200,
                namespace=ns,
                include_metadata=True,
            )
            matches = res.matches if hasattr(res, "matches") else res.get("matches", [])
            for match in matches:
                md = _safe_get_metadata(match)
                cid = md.get("candidate_id")
                if cid:
                    seen.add(cid)
        except Exception:
            continue

    return sorted(seen)


# -----------------------------
# Pinecone scoring
# -----------------------------

def fetch_candidate_matches(candidate_id: str, jd_embedding: List[float]) -> List:
    from pinecone import Pinecone

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    ns = _namespace_key()

    res = index.query(
        vector=jd_embedding,
        top_k=TOP_K_CHUNKS,
        namespace=ns,
        include_metadata=True,
        filter={"candidate_id": {"$eq": candidate_id}},
    )
    return res.matches if hasattr(res, "matches") else res.get("matches", [])


def aggregate_similarity(matches: List) -> Tuple[float, Dict[str, float]]:
    """
    Convert chunk-level Pinecone scores into a single candidate score.

    Logical approach:
    - take top chunk scores
    - compute a weighted average favoring the best chunks (more representative)
    - clamp to [0, 1]
    """
    scores = sorted((_safe_get_score(m) for m in matches), reverse=True)
    if not scores:
        return 0.0, {"max": 0.0, "avg_top": 0.0}

    top = scores[: min(10, len(scores))]

    weights = []
    weight = 1.0
    for _ in top:
        weights.append(weight)
        weight *= 0.85

    weighted = sum(score * w for score, w in zip(top, weights)) / max(1e-9, sum(weights))
    max_s = top[0]
    avg_top = sum(top) / len(top)

    score = float(max(0.0, min(1.0, weighted)))
    return score, {"max": float(max_s), "avg_top": float(avg_top)}


# -----------------------------
# Fast profile + requirement logic
# -----------------------------

_STOPWORDS = {
    "and", "or", "the", "a", "an", "to", "of", "in", "for", "with", "on", "at", "by",
    "as", "is", "are", "be", "this", "that", "from", "it", "you", "we", "our", "your",
}

_SKILL_TERMS = [
    "python", "fastapi", "django", "flask", "rest", "graphql",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform",
    "postgres", "mysql", "mongodb", "redis",
    "ci/cd", "github actions", "gitlab ci", "jenkins",
    "microservices", "distributed systems", "event-driven", "kafka", "rabbitmq",
    "testing", "tdd", "pytest",
    "react", "typescript", "node", "java", "go",
    "linux", "bash",
]

_ROLE_KEYWORDS = [
    "engineer", "developer", "architect", "lead", "manager", "consultant",
    "analyst", "specialist", "intern", "backend", "software", "full stack",
    "data engineer", "devops", "ml engineer",
]

_EDUCATION_KEYWORDS = [
    "bachelor", "master", "phd", "university", "school", "institute",
    "computer science", "engineering", "degree",
]

_DISPLAY_SKILLS = {
    "python": "Python",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "rest": "REST APIs",
    "graphql": "GraphQL",
    "aws": "AWS",
    "gcp": "GCP",
    "azure": "Azure",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "terraform": "Terraform",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "ci/cd": "CI/CD",
    "github actions": "GitHub Actions",
    "gitlab ci": "GitLab CI",
    "jenkins": "Jenkins",
    "microservices": "Microservices",
    "distributed systems": "Distributed Systems",
    "event-driven": "Event-Driven Systems",
    "kafka": "Kafka",
    "rabbitmq": "RabbitMQ",
    "testing": "Testing",
    "tdd": "TDD",
    "pytest": "Pytest",
    "react": "React",
    "typescript": "TypeScript",
    "node": "Node.js",
    "java": "Java",
    "go": "Go",
    "linux": "Linux",
    "bash": "Bash",
}

_GROUPED_REQUIREMENTS = [
    {
        "key": "backend_framework",
        "terms": ["fastapi", "django", "flask"],
        "requirement": "Python backend framework (FastAPI or Django)",
        "min_terms": 1,
    },
    {
        "key": "cloud_platform",
        "terms": ["aws", "gcp", "azure"],
        "requirement": "Cloud platform experience (AWS, GCP, or Azure)",
        "min_terms": 1,
    },
    {
        "key": "message_queue",
        "terms": ["rabbitmq", "kafka"],
        "requirement": "Message queue experience (RabbitMQ or Kafka)",
        "min_terms": 1,
    },
    {
        "key": "ci_cd_tooling",
        "terms": ["github actions", "gitlab ci", "jenkins"],
        "requirement": "CI/CD tooling (GitHub Actions, GitLab CI, or Jenkins)",
        "min_terms": 1,
    },
]


def _normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\+\#\/\.\-\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _contains_term(text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(part) for part in normalized_term.split()) + r"(?![a-z0-9])"
    return bool(re.search(pattern, text))


def _title_from_candidate_id(candidate_id: str) -> str:
    return candidate_id.replace("_", " ").replace("-", " ").title()


def _extract_skill_mentions(cv_text: str, max_items: int = 10) -> List[str]:
    text = _normalize_text(cv_text)
    found = []
    for skill in _SKILL_TERMS:
        if _contains_term(text, skill):
            found.append(_DISPLAY_SKILLS.get(skill, skill.title()))
    return found[:max_items]


def _extract_years_of_experience(cv_text: str) -> Optional[int]:
    matches = re.findall(r"(\d{1,2})\+?\s+years?", cv_text, flags=re.IGNORECASE)
    if not matches:
        return None
    return max(int(match) for match in matches)


def _extract_role_lines(cv_text: str, max_items: int = 4) -> List[str]:
    roles = []
    seen = set()
    for line in cv_text.splitlines():
        cleaned = " ".join(line.strip().split())
        if len(cleaned) < 4 or len(cleaned) > 80:
            continue
        lowered = cleaned.lower()
        if not any(keyword in lowered for keyword in _ROLE_KEYWORDS):
            continue
        if "@" in cleaned or "www" in lowered:
            continue
        if lowered not in seen:
            roles.append(cleaned)
            seen.add(lowered)
        if len(roles) >= max_items:
            break
    return roles


def _extract_education_lines(cv_text: str, max_items: int = 2) -> List[str]:
    education = []
    seen = set()
    for line in cv_text.splitlines():
        cleaned = " ".join(line.strip().split())
        if len(cleaned) < 6 or len(cleaned) > 120:
            continue
        lowered = cleaned.lower()
        if not any(keyword in lowered for keyword in _EDUCATION_KEYWORDS):
            continue
        if lowered not in seen:
            education.append(cleaned)
            seen.add(lowered)
        if len(education) >= max_items:
            break
    return education


def _extract_preview(cv_text: str, max_chars: int = 420) -> str:
    preview = " ".join(cv_text.split())
    return preview[:max_chars].strip()


def build_candidate_profile(candidate_id: str, cv_text: str, source_file: str = "") -> dict:
    years = _extract_years_of_experience(cv_text)
    skills = _extract_skill_mentions(cv_text)
    roles = _extract_role_lines(cv_text)
    education = _extract_education_lines(cv_text)
    preview = _extract_preview(cv_text)

    summary_parts = []
    if years is not None:
        summary_parts.append(f"{years}+ years of experience mentioned")
    if roles:
        summary_parts.append(f"recent roles include {', '.join(roles[:2])}")
    if skills:
        summary_parts.append(f"skills include {', '.join(skills[:5])}")

    return {
        "name": _title_from_candidate_id(candidate_id),
        "years_of_experience": years,
        "skills": skills,
        "past_roles": roles,
        "education": education,
        "summary": ". ".join(summary_parts).strip(". ") + ("." if summary_parts else ""),
        "source_file": source_file,
        "cv_excerpt": preview,
    }


def _candidate_cv_path(candidate_id: str, source_file: str = "") -> Optional[Path]:
    cv_dir = Path(CV_FOLDER).resolve()
    if source_file:
        candidate_path = (cv_dir / source_file).resolve()
        if candidate_path.is_file() and cv_dir in candidate_path.parents:
            return candidate_path

    normalized_id = re.sub(r"[^a-z0-9_]", "", candidate_id.lower())
    for pdf_path in cv_dir.glob("*.pdf"):
        stem = re.sub(r"[^a-z0-9_]", "", pdf_path.stem.lower().replace(" ", "_"))
        if stem == normalized_id:
            return pdf_path.resolve()
    return None


def _load_full_cv_text(candidate_id: str, source_file: str = "") -> Tuple[str, str]:
    cv_path = _candidate_cv_path(candidate_id, source_file)
    if not cv_path:
        existing = get_candidate(candidate_id) or {}
        fallback_path = _candidate_cv_path(candidate_id, existing.get("source_file", ""))
        cv_path = fallback_path
    if not cv_path:
        return source_file, ""

    try:
        from langchain_community.document_loaders import PyPDFLoader

        pages = PyPDFLoader(str(cv_path)).load()
        full_text = "\n".join(page.page_content for page in pages).strip()
        return cv_path.name, full_text
    except Exception:
        return cv_path.name, ""


def fetch_candidate_cv_context(candidate_id: str, jd: str = None) -> Tuple[str, str]:
    if jd is None:
        jd = JOB_DESCRIPTION

    emb = _embeddings()
    jd_embedding = emb.embed_query(jd)
    matches = fetch_candidate_matches(candidate_id, jd_embedding)

    texts = []
    source_file = ""
    for match in matches:
        md = _safe_get_metadata(match)
        if not source_file:
            source_file = md.get("source_file", "")
        txt = md.get("text", "")
        if txt:
            texts.append(txt)

    full_source_file, full_text = _load_full_cv_text(candidate_id, source_file)
    if full_text:
        return full_source_file or source_file, full_text
    return source_file, "\n\n".join(texts)


def _requirement_level(line: str) -> Tuple[str, float]:
    lowered = _normalize_text(line)
    if "bonus" in lowered or "nice to have" in lowered:
        return "bonus", 0.35
    if "familiarity" in lowered or "knowledge" in lowered or "understanding" in lowered:
        return "important", 0.75
    return "critical", 1.0


def _jd_lines(jd: str) -> List[str]:
    lines = []
    for raw_line in jd.splitlines():
        cleaned = raw_line.strip().lstrip("-").strip()
        if not cleaned:
            continue
        if cleaned.lower().startswith("position:"):
            continue
        if cleaned.lower() == "requirements:":
            continue
        lines.append(cleaned)
    return lines


def extract_structured_requirements_from_jd(jd: str, max_items: int = 12) -> List[dict]:
    requirements = []
    seen_keys = set()
    consumed_terms = set()

    for line in _jd_lines(jd):
        severity, weight = _requirement_level(line)
        line_n = _normalize_text(line)

        years_match = re.search(r"(\d{1,2})\+?\s+years?", line, flags=re.IGNORECASE)
        if years_match:
            years = int(years_match.group(1))
            key = f"years_{years}"
            if key not in seen_keys:
                requirements.append(
                    {
                        "key": key,
                        "requirement": f"{years}+ years of relevant experience",
                        "severity": severity,
                        "weight": weight,
                        "type": "years",
                        "min_years": years,
                    }
                )
                seen_keys.add(key)

        for group in _GROUPED_REQUIREMENTS:
            if group["key"] in seen_keys:
                continue
            matched_terms = [term for term in group["terms"] if _contains_term(line_n, term)]
            if not matched_terms:
                continue
            requirements.append(
                {
                    "key": group["key"],
                    "requirement": group["requirement"],
                    "severity": severity,
                    "weight": weight,
                    "type": "skill_group",
                    "terms": group["terms"],
                    "min_terms": group["min_terms"],
                }
            )
            seen_keys.add(group["key"])
            consumed_terms.update(group["terms"])

        for term in _SKILL_TERMS:
            if term in consumed_terms or not _contains_term(line_n, term):
                continue
            key = f"skill_{term}"
            if key in seen_keys:
                continue
            requirements.append(
                {
                    "key": key,
                    "requirement": _DISPLAY_SKILLS.get(term, term.title()),
                    "severity": severity,
                    "weight": weight,
                    "type": "skill",
                    "terms": [term],
                    "min_terms": 1,
                }
            )
            seen_keys.add(key)

        if len(requirements) >= max_items:
            break

    return requirements[:max_items]


def extract_requirements_from_jd(jd: str, max_items: int = 12) -> List[str]:
    return [req["requirement"] for req in extract_structured_requirements_from_jd(jd, max_items=max_items)]


def _evaluate_requirement(requirement: dict, cv_n: str, profile_json: Optional[dict] = None) -> dict:
    profile_json = profile_json or {}

    if requirement.get("type") == "years":
        candidate_years = profile_json.get("years_of_experience")
        required_years = int(requirement.get("min_years", 0))
        matched = candidate_years is not None and candidate_years >= required_years
        score = 1.0 if matched else (min(1.0, candidate_years / required_years) if candidate_years else 0.0)
        if matched:
            evidence = f"CV indicates {candidate_years} years of experience."
        elif candidate_years is None:
            evidence = "No reliable years-of-experience evidence found in the CV."
        else:
            evidence = f"CV indicates {candidate_years} years vs required {required_years}."
        return {
            "matched": matched,
            "score": round(score, 4),
            "matched_terms": [],
            "evidence": evidence,
        }

    terms = requirement.get("terms", [])
    matched_terms = [term for term in terms if _contains_term(cv_n, term)]
    required_matches = int(requirement.get("min_terms", 1))
    matched = len(matched_terms) >= required_matches
    denominator = max(required_matches, len(terms) if required_matches > 1 else 1)
    score = min(1.0, len(matched_terms) / denominator) if denominator else 0.0

    if matched_terms:
        evidence = f"Found evidence for: {', '.join(_DISPLAY_SKILLS.get(term, term) for term in matched_terms)}."
    else:
        evidence = "No direct evidence found in the full CV text."

    return {
        "matched": matched,
        "score": round(score, 4),
        "matched_terms": matched_terms,
        "evidence": evidence,
    }


def _compute_requirement_coverage(requirements: List[dict], cv_text: str, profile_json: Optional[dict] = None) -> Tuple[float, List[dict]]:
    if not requirements:
        return 1.0, []

    cv_n = _normalize_text(cv_text)
    weighted_total = 0.0
    weighted_hits = 0.0
    evaluations = []

    for requirement in requirements:
        weight = float(requirement.get("weight", 1.0))
        evaluation = _evaluate_requirement(requirement, cv_n, profile_json=profile_json)
        weighted_total += weight
        weighted_hits += weight * evaluation["score"]
        evaluations.append(
            {
                "requirement": requirement["requirement"],
                "severity": requirement["severity"],
                "weight": round(weight, 3),
                "matched": evaluation["matched"],
                "score": evaluation["score"],
                "matched_terms": [
                    _DISPLAY_SKILLS.get(term, term.title())
                    for term in evaluation.get("matched_terms", [])
                ],
                "evidence": evaluation["evidence"],
            }
        )

    if weighted_total <= 0:
        return 1.0, evaluations
    return round(weighted_hits / weighted_total, 4), evaluations


def _compute_seniority_match(requirements: List[dict], profile_json: Optional[dict] = None) -> float:
    profile_json = profile_json or {}
    years_reqs = [req for req in requirements if req.get("type") == "years" and req.get("min_years")]
    if not years_reqs:
        return 1.0

    candidate_years = profile_json.get("years_of_experience")
    if candidate_years is None:
        return 0.4

    required_years = max(int(req["min_years"]) for req in years_reqs)
    return round(max(0.0, min(1.0, candidate_years / required_years)), 4)


def compute_hybrid_screening_score(matches: List, cv_text: str, profile_json: Optional[dict], jd: str) -> Tuple[float, dict]:
    semantic_similarity, semantic_details = aggregate_similarity(matches)
    requirements = extract_structured_requirements_from_jd(jd, max_items=20)
    requirement_coverage, requirement_evaluations = _compute_requirement_coverage(
        requirements,
        cv_text,
        profile_json=profile_json,
    )
    seniority_match = _compute_seniority_match(requirements, profile_json=profile_json)

    score = (
        (0.55 * semantic_similarity)
        + (0.30 * requirement_coverage)
        + (0.15 * seniority_match)
    )

    return round(max(0.0, min(1.0, score)), 4), {
        "semantic_similarity": round(semantic_similarity, 4),
        "requirement_coverage": round(requirement_coverage, 4),
        "seniority_match": round(seniority_match, 4),
        "max": semantic_details["max"],
        "avg_top": semantic_details["avg_top"],
        "requirements": requirement_evaluations[:8],
        "weights": {
            "semantic_similarity": 0.55,
            "requirement_coverage": 0.30,
            "seniority_match": 0.15,
        },
    }


def detect_gaps_fast(jd: str, cv_text: str, profile_json: Optional[dict] = None, max_gaps: int = 5) -> List[dict]:
    requirements = extract_structured_requirements_from_jd(jd, max_items=20)
    if not requirements:
        return []

    cv_n = _normalize_text(cv_text)
    gaps = []

    for requirement in requirements:
        evaluation = _evaluate_requirement(requirement, cv_n, profile_json=profile_json)
        if evaluation["matched"]:
            continue
        gaps.append(
            {
                "requirement": requirement["requirement"],
                "severity": requirement["severity"],
                "weight": round(float(requirement.get("weight", 1.0)), 3),
                "reason": evaluation["evidence"],
                "status": "unanswered",
            }
        )

    severity_rank = {"critical": 0, "important": 1, "bonus": 2}
    gaps.sort(key=lambda gap: (severity_rank.get(gap.get("severity", "important"), 3), -float(gap.get("weight", 0.0))))
    return gaps[:max_gaps]


# -----------------------------
# Main
# -----------------------------

def run_screening(jd: str = None, progress_callback=None) -> List[dict]:
    """
    Optimized screening:
    - embed JD once
    - fetch top matching chunks from Pinecone
    - combine semantic similarity with requirement coverage and seniority match
    - detect gaps from the full CV text when available
    - save results to the local candidates store
    """
    if jd is None:
        jd = JOB_DESCRIPTION

    emb = _embeddings()

    if progress_callback:
        progress_callback("Embedding Job Description (once)...")
    jd_embedding = emb.embed_query(jd)

    if progress_callback:
        progress_callback("Fetching candidate list from Pinecone...")
    candidate_ids = get_all_candidate_ids_from_pinecone(progress_callback=progress_callback)

    if not candidate_ids:
        raise RuntimeError("No candidates found in Pinecone. Run ingestion first.")

    if progress_callback:
        progress_callback(f"Found {len(candidate_ids)} candidates. Running hybrid scoring...")

    results: List[dict] = []
    display_ns = _normalize_display_namespace()

    for cid in candidate_ids:
        if progress_callback:
            progress_callback(f"  Screening: {cid}")

        try:
            matches = fetch_candidate_matches(cid, jd_embedding)
            if not matches:
                if progress_callback:
                    progress_callback(f"  No matches found for {cid} (namespace/filter?). Skipping.")
                continue

            retrieved_texts = []
            source_file = ""
            for match in matches:
                md = _safe_get_metadata(match)
                if not source_file:
                    source_file = md.get("source_file", "")
                txt = md.get("text", "")
                if txt:
                    retrieved_texts.append(txt)
            retrieved_cv_text = "\n\n".join(retrieved_texts)

            full_source_file, full_cv_text = _load_full_cv_text(cid, source_file)
            if full_cv_text:
                source_file = full_source_file or source_file
            cv_text = full_cv_text or retrieved_cv_text

            profile_json = build_candidate_profile(cid, cv_text, source_file)
            score, diagnostics = compute_hybrid_screening_score(matches, cv_text, profile_json, jd)
            gaps = detect_gaps_fast(jd, cv_text, profile_json=profile_json, max_gaps=5)
            status = "shortlisted" if score >= SHORTLIST_THRESHOLD else "rejected"

            candidate = {
                "candidate_id": cid,
                "source_file": source_file,
                "namespace": display_ns,
                "preview": _extract_preview(cv_text, max_chars=700),
                "profile_json": profile_json,
                "match_score": score,
                "screening_score": score,
                "final_score": None,
                "status": status,
                "gaps": gaps,
                "hr_summary": "",
                "score_details": diagnostics,
                "top_chunk_scores": [
                    round(_safe_get_score(match), 4)
                    for match in sorted(matches, key=_safe_get_score, reverse=True)[:5]
                ],
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            save_candidate(candidate)
            results.append(candidate)

            if progress_callback:
                progress_callback(
                    f"  {cid}: score={candidate['match_score']:.2f} "
                    f"(semantic={diagnostics['semantic_similarity']:.2f}, "
                    f"coverage={diagnostics['requirement_coverage']:.2f}, "
                    f"seniority={diagnostics['seniority_match']:.2f}), "
                    f"gaps={len(gaps)}, status={status}"
                )

        except Exception as exc:
            if progress_callback:
                progress_callback(f"  Error screening {cid}: {exc}")
            continue

    results.sort(key=lambda candidate: candidate["match_score"], reverse=True)
    return results
