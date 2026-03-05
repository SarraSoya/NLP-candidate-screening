# AI Recruitment Pre-Screening System

## Prerequisites

1. **Ollama** running locally with required models:
```bash
   ollama pull gemma:7b
   ollama pull nomic-embed-text
   ollama serve
```

2. **Pinecone** — Create a free index at https://app.pinecone.io:
   - Index name: `recruitment` (or match your `.env`)
   - Dimension: `768` (for `nomic-embed-text`)
   - Metric: `cosine`

3. **Python 3.11+**

---

## Setup
```bash
# 1. Clone / create project folder
mkdir recruitment_screener && cd recruitment_screener

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env .env.local
# Edit .env and fill in your PINECONE_API_KEY

# 5. Add CV PDFs
mkdir cvs
# Copy your PDF resumes into ./cvs/

# 6. (Optional) Edit the JOB_DESCRIPTION in config.py
```

---

## Run
```bash
chainlit run app.py
```

Open http://localhost:8000 in your browser.

---

## Workflow

1. **📥 Ingest CVs** — Parses PDFs, creates embeddings, upserts to Pinecone
2. **🔍 Run Screening** — Scores each candidate vs JD, detects gaps, saves to `candidates.json`
3. **💬 Chat as Candidate** — Select a shortlisted candidate, bot asks gap-filling questions one by one, generates HR summary at the end

---

## File Outputs

| File | Contents |
|---|---|
| `candidates.json` | All candidate profiles, scores, gaps, answers |
| `chat_history.json` | Full chat logs per candidate |

---

## Pinecone Chunk Metadata Schema
```json
{
  "candidate_id": "john_doe",
  "source_file": "John_Doe.pdf",
  "chunk_index": 0,
  "text": "..."
}
```

---

## Notes

- Re-ingesting the same PDF **overwrites** existing chunks (deterministic SHA256 IDs)
- Pinecone dimension must be **768** for `nomic-embed-text`
- All LLM calls use local Ollama — no OpenAI/cloud LLM calls