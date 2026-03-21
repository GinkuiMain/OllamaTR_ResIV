from pathlib import Path
import os
import requests
import chromadb
from chromadb.config import Settings
from utils.loaders import load_text

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CHROMA_DIR = "data/chroma"
COLLECTION = "termos_referencia"


def chunk_text(text: str, max_chars=1000, overlap=150):
    text = " ".join(text.replace("\r", " ").split())
    i = 0
    while i < len(text):
        yield text[i:i+max_chars]
        i += max_chars - overlap


def ollama_embed(texts: list[str]) -> list[list[float]]:
    # /api/embed é a rota do Ollama para gerar embeddings
    resp = requests.post(
        f"{OLLAMA_BASE}/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=120
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def get_collection():
    client = chromadb.PersistentClient(
        path=CHROMA_DIR,
        settings=Settings(anonymized_telemetry=False)
    )
    return client.get_or_create_collection(COLLECTION)


def index_docs(folder="data/docs"):
    folder = Path(folder)
    col = get_collection()

    docs = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in [".pdf", ".docx", ".txt"]]
    if not docs:
        return {"ok": False, "msg": "Nenhum arquivo encontrado em data/docs"}

    added = 0

    for doc_path in docs:
        raw = load_text(doc_path)
        chunks = list(chunk_text(raw))

        # embeddings em lote (melhor que 1 por 1)
        embs = ollama_embed(chunks)

        ids = []
        metadatas = []
        for idx in range(len(chunks)):
            ids.append(f"{doc_path.name}::chunk::{idx}")
            metadatas.append({"source": doc_path.name, "chunk": idx})

        col.add(
            ids=ids,
            documents=chunks,
            embeddings=embs,
            metadatas=metadatas
        )
        added += len(chunks)

    return {"ok": True, "files": len(docs), "chunks_added": added}