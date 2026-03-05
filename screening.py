import json
import re
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from langchain_ollama import OllamaEmbeddings
from pinecone import Pinecone

from config import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE,
    OLLAMA_BASE_URL,
    OLLAMA_EMBED_MODEL,
    TOP_K_CHUNKS,
    SHORTLIST_THRESHOLD,
    JOB_DESCRIPTION,
)
from store import save_candidate


# -----------------------------
# Helpers
# -----------------------------

def _embeddings():
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
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    ns = _namespace_key()

    seen = set()

    # Attempt list+fetch (works on many setups)
    try:
        if progress_callback:
            progress_callback("📋 Reading vector IDs (list+fetch)...")

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
    except Exception as e:
        if progress_callback:
            progress_callback(f"⚠️ list+fetch failed ({e}). Using fallback sampling...")

    # Fallback: sampling queries to discover candidate_ids
    import random
    dims = 768  # nomic-embed-text
    for attempt in range(4):
        dummy = [random.uniform(-0.01, 0.01) for _ in range(dims)]
        try:
            res = index.query(
                vector=dummy,
                top_k=200,
                namespace=ns,
                include_metadata=True,
            )
            matches = res.matches if hasattr(res, "matches") else res.get("matches", [])
            for m in matches:
                md = _safe_get_metadata(m)
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

    # Use up to top 10 scores for stability
    top = scores[: min(10, len(scores))]

    # Weighted average: weights decay with rank (1.0, 0.85, 0.72, ...)
    weights = []
    w = 1.0
    for _ in top:
        weights.append(w)
        w *= 0.85

    weighted = sum(s * w for s, w in zip(top, weights)) / max(1e-9, sum(weights))

    # Also compute simple diagnostics
    max_s = top[0]
    avg_top = sum(top) / len(top)

    # Pinecone similarity score is typically already in [0,1] for cosine (depending on config)
    score = float(max(0.0, min(1.0, weighted)))
    return score, {"max": float(max_s), "avg_top": float(avg_top)}


# -----------------------------
# Fast gap detection (no LLM)
# -----------------------------

_STOPWORDS = {
    "and", "or", "the", "a", "an", "to", "of", "in", "for", "with", "on", "at", "by",
    "as", "is", "are", "be", "this", "that", "from", "it", "you", "we", "our", "your",
}

# A small skills dictionary helps a lot. Extend this list for your domain.
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


def _normalize_text(t: str) -> str:
    t = t.lower()
    t = re.sub(r"[^a-z0-9\+\#\/\.\-\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_requirements_from_jd(jd: str, max_items: int = 12) -> List[str]:
    """
    Very fast heuristic: pick known skill terms that appear in JD.
    If you want more advanced extraction later, you can add it,
    but this keeps screening fast and deterministic.
    """
    jd_n = _normalize_text(jd)
    found = []
    for term in _SKILL_TERMS:
        if term in jd_n:
            found.append(term)
    return found[:max_items]


def detect_gaps_fast(jd: str, cv_text: str, max_gaps: int = 5) -> List[dict]:
    reqs = extract_requirements_from_jd(jd, max_items=20)
    if not reqs:
        return []

    cv_n = _normalize_text(cv_text)

    gaps = []
    for r in reqs:
        if r not in cv_n:
            gaps.append({
                "requirement": r,
                "severity": "critical",
                "reason": f"'{r}' not found in retrieved CV text",
                "status": "unanswered",
            })
        if len(gaps) >= max_gaps:
            break
    return gaps


# -----------------------------
# Main
# -----------------------------

def run_screening(jd: str = None, progress_callback=None) -> List[dict]:
    """
    Optimized screening:
    - Embed JD once
    - For each candidate: 1 Pinecone query (filtered by candidate_id)
    - Score = weighted avg of top chunk similarities
    - Gaps = fast keyword gaps (no LLM)
    - Save to candidates store
    """
    if jd is None:
        jd = JOB_DESCRIPTION

    emb = _embeddings()

    if progress_callback:
        progress_callback("🔍 Embedding Job Description (once)...")
    jd_embedding = emb.embed_query(jd)

    if progress_callback:
        progress_callback("📋 Fetching candidate list from Pinecone...")
    candidate_ids = get_all_candidate_ids_from_pinecone(progress_callback=progress_callback)

    if not candidate_ids:
        raise RuntimeError("No candidates found in Pinecone. Run ingestion first.")

    if progress_callback:
        progress_callback(f"👥 Found {len(candidate_ids)} candidates. Scoring with Pinecone...")

    results: List[dict] = []
    display_ns = _normalize_display_namespace()

    for cid in candidate_ids:
        if progress_callback:
            progress_callback(f"  ⚙️  Screening: {cid}")

        try:
            matches = fetch_candidate_matches(cid, jd_embedding)
            if not matches:
                if progress_callback:
                    progress_callback(f"  ⚠️  No matches found for {cid} (namespace/filter?). Skipping.")
                continue

            # Build CV evidence text from the retrieved chunks only
            texts = []
            for m in matches:
                md = _safe_get_metadata(m)
                txt = md.get("text", "")
                if txt:
                    texts.append(txt)
            cv_text = "\n\n".join(texts)

            score, diagnostics = aggregate_similarity(matches)
            gaps = detect_gaps_fast(jd, cv_text, max_gaps=5)

            status = "shortlisted" if score >= SHORTLIST_THRESHOLD else "rejected"

            candidate = {
                "candidate_id": cid,
                "namespace": display_ns,
                "match_score": round(score, 4),
                "status": status,
                "gaps": gaps,
                "score_details": diagnostics,  # useful for debugging/tuning
                "top_chunk_scores": [round(_safe_get_score(m), 4) for m in sorted(matches, key=_safe_get_score, reverse=True)[:5]],
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            save_candidate(candidate)
            results.append(candidate)

            if progress_callback:
                progress_callback(
                    f"  ✅ {cid}: score={candidate['match_score']:.2f} "
                    f"(max={diagnostics['max']:.2f}, avg_top={diagnostics['avg_top']:.2f}), "
                    f"gaps={len(gaps)}, status={status}"
                )

        except Exception as e:
            if progress_callback:
                progress_callback(f"  ❌ Error screening {cid}: {e}")
            continue

    results.sort(key=lambda x: x["match_score"], reverse=True)
    return results