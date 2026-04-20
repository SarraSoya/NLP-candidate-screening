import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from config import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE,
    OLLAMA_BASE_URL,
    OLLAMA_EMBED_MODEL,
    CV_FOLDER,
    CANDIDATES_DB,
)


def get_pinecone_index():
    """
    Return an existing Pinecone index handle. This code assumes the index
    is already created in Pinecone with the correct dimension.
    """
    from pinecone import Pinecone

    pc = Pinecone(api_key=PINECONE_API_KEY)
    existing = [idx.name for idx in pc.list_indexes()]
    if PINECONE_INDEX_NAME not in existing:
        raise RuntimeError(
            f"Pinecone index '{PINECONE_INDEX_NAME}' does not exist. "
            "Please create it in the Pinecone console first "
            "(dimension=768 for nomic-embed-text)."
        )
    return pc.Index(PINECONE_INDEX_NAME)


def make_chunk_id(candidate_id: str, chunk_index: int) -> str:
    raw = f"{candidate_id}__chunk_{chunk_index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def candidate_id_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    return stem.lower().replace(" ", "_")


def _load_candidates(db_path: str) -> dict:
    p = Path(db_path)
    if not p.exists():
        return {}
    try:
        txt = p.read_text(encoding="utf-8").strip()
        if not txt:
            return {}
        data = json.loads(txt)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        # Corrupted or partially-written file -> reset to empty
        return {}


def _save_candidates(db_path: str, data: dict) -> None:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _source_signature(pdf_file: Path) -> str:
    stat = pdf_file.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _is_unchanged(candidate: dict, pdf_file: Path, namespace: str) -> bool:
    return (
        candidate.get("source_file") == pdf_file.name
        and candidate.get("source_signature") == _source_signature(pdf_file)
        and candidate.get("namespace") == namespace
    )


def ingest_cvs(progress_callback: Optional[Callable[[str], None]] = None) -> list[str]:
    """
    Parse all PDFs in CV_FOLDER, split into chunks, embed with Ollama,
    upsert chunk vectors to Pinecone, and register candidates in candidates.json.

    Optimizations:
    - skip PDFs that have not changed since the last ingestion
    - batch chunk embeddings per CV instead of one request per chunk
    - write candidates.json once at the end instead of once per CV
    """
    cv_path = Path(CV_FOLDER)
    if not cv_path.exists():
        raise FileNotFoundError(f"CV folder not found: {CV_FOLDER}")

    pdf_files = sorted(cv_path.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in {CV_FOLDER}")

    # Ensure namespace is consistent (Pinecone UI shows default as "__default__")
    namespace = PINECONE_NAMESPACE or "__default__"

    from langchain_community.document_loaders import PyPDFLoader
    from langchain_ollama import OllamaEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    embeddings = OllamaEmbeddings(
        model=OLLAMA_EMBED_MODEL,
        base_url=OLLAMA_BASE_URL,
    )

    index = get_pinecone_index()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    ingested: list[str] = []
    candidates = _load_candidates(CANDIDATES_DB)

    for pdf_file in pdf_files:
        candidate_id = candidate_id_from_filename(pdf_file.name)
        source_signature = _source_signature(pdf_file)
        existing_candidate = candidates.get(candidate_id, {})

        if progress_callback:
            progress_callback(f"Processing: {pdf_file.name} -> candidate_id={candidate_id}")

        if _is_unchanged(existing_candidate, pdf_file, namespace):
            if progress_callback:
                progress_callback(f"Skipping unchanged CV: {pdf_file.name}")
            continue

        loader = PyPDFLoader(str(pdf_file))
        pages = loader.load()
        full_text = "\n".join(p.page_content for p in pages).strip()

        if not full_text:
            if progress_callback:
                progress_callback(f"Skipping empty PDF: {pdf_file.name}")
            continue

        chunks = splitter.split_text(full_text)
        if not chunks:
            if progress_callback:
                progress_callback(f"Skipping PDF with no chunks: {pdf_file.name}")
            continue

        # Re-ingesting a changed CV should replace old vectors entirely to avoid stale chunks.
        if existing_candidate:
            index.delete(
                namespace=namespace,
                filter={"candidate_id": {"$eq": candidate_id}},
            )

        chunk_embeddings = embeddings.embed_documents(chunks)

        vectors = []
        for i, (chunk, embedding) in enumerate(zip(chunks, chunk_embeddings)):
            chunk_id = make_chunk_id(candidate_id, i)
            vectors.append(
                {
                    "id": chunk_id,
                    "values": embedding,
                    "metadata": {
                        "candidate_id": candidate_id,
                        "source_file": pdf_file.name,
                        "chunk_index": i,
                        "text": chunk,
                    },
                }
            )

        batch_size = 100
        for start in range(0, len(vectors), batch_size):
            index.upsert(
                vectors=vectors[start : start + batch_size],
                namespace=namespace,
            )

        candidates[candidate_id] = {
            "candidate_id": candidate_id,
            "source_file": pdf_file.name,
            "source_signature": source_signature,
            "namespace": namespace,
            "chunks": len(chunks),
            "ingested_at": datetime.utcnow().isoformat() + "Z",
            "preview": full_text[:500],
            # fields that screening will fill later
            "match_score": None,
            "screening_score": None,
            "final_score": None,
            "status": "pending",
            "gaps": [],
            "hr_summary": "",
        }
        ingested.append(candidate_id)

        if progress_callback:
            progress_callback(f"Ingested {len(chunks)} chunks for {candidate_id}")

    _save_candidates(CANDIDATES_DB, candidates)
    return ingested


if __name__ == "__main__":
    result = ingest_cvs(progress_callback=print)
    print(f"\nDone. Ingested candidates: {result}")
    print(f"Updated candidates DB: {Path(CANDIDATES_DB).resolve()}")
