# AI Recruitment Pre-Screening System

This project now runs as a small Flask web app with two separate experiences:

- `Candidate portal`: candidates identify themselves by candidate ID and answer LLM-generated follow-up questions based on screening gaps.
- `Admin dashboard`: admins ingest CVs, run screening, and review private scores, answers, and HR summaries.

Candidate-facing pages do not expose screening or final scores.

## Prerequisites

1. Python 3.11+
2. Ollama running locally with the required models:

```bash
ollama pull gemma:7b
ollama pull nomic-embed-text
ollama serve
```

3. Pinecone index configured for your environment:
   - Index name: `recruitment` or the value from `.env`
   - Dimension: `768`
   - Metric: `cosine`

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Add your config values in `.env`, especially:

- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `ADMIN_PASSWORD` (optional, defaults to `hr1234`)
- `FLASK_SECRET_KEY` (optional for local use, recommended to change)

Put candidate CV PDFs in `./cvs/`.

## Run

```bash
python app.py
```

Then open `http://127.0.0.1:5000`.

## Workflow

1. Log in as admin.
2. Click `Ingest CVs` to parse local PDFs and register candidates.
3. Click `Run Screening` to compute scores and detect gaps.
4. Share the candidate ID with the candidate.
5. The candidate logs into the candidate portal and completes the interview.
6. The admin reviews candidate scores, answers, transcript, and saved HR summary.

## Output Files

- `candidates.json`: candidate records, screening/final scores, gaps, and HR summary
- `chat_history.json`: interview transcript per candidate

## Notes

- Screening score is preserved separately from final interview score.
- Candidate pages intentionally hide all scores and admin-only summaries.
- Existing Chainlit files can remain in the repo, but the active app entrypoint is now `app.py` with Flask.
