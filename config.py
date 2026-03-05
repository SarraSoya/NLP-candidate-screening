import os
from dotenv import load_dotenv

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")   # keep empty if not set
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "recruitment")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "__default__")
# Ollama models
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "gemma:7b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")# Paths
CV_FOLDER = os.getenv("CV_FOLDER", "./cvs")
CANDIDATES_DB = os.getenv("CANDIDATES_DB", "./candidates.json")
CHAT_HISTORY_DB = os.getenv("CHAT_HISTORY_DB", "./chat_history.json")

# Job Description (edit this directly or load from file)
JOB_DESCRIPTION = os.getenv("JOB_DESCRIPTION", """
Position: Senior Python Backend Engineer

Requirements:
- 5+ years of Python development experience
- Strong knowledge of FastAPI or Django REST Framework
- Experience with PostgreSQL and Redis
- Familiarity with Docker and Kubernetes
- Experience with cloud platforms (AWS, GCP, or Azure)
- Strong understanding of microservices architecture
- Experience with CI/CD pipelines (GitHub Actions, Jenkins)
- Knowledge of message queues (RabbitMQ, Kafka)
- Strong problem-solving skills and communication abilities
- Experience with unit testing and TDD practices
- Bonus: experience with ML model serving or data pipelines
""")

# Screening thresholds
SHORTLIST_THRESHOLD = float(os.getenv("SHORTLIST_THRESHOLD", "0.5"))
TOP_K_CHUNKS = int(os.getenv("TOP_K_CHUNKS", "5"))