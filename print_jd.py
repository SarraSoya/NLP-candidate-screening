from config import JOB_DESCRIPTION, OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL
from langchain_ollama import OllamaEmbeddings
import json

emb = OllamaEmbeddings(model=OLLAMA_EMBED_MODEL, base_url=OLLAMA_BASE_URL)
vec = emb.embed_query(JOB_DESCRIPTION)

print("dim =", len(vec))
print(json.dumps(vec))  # paste this into Pinecone "Search by vector"