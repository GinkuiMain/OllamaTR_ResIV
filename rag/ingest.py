from pathlib import Path
import requests
import chromadb
from chromadb.config import Settings
import json

from utils.loaders import load_text, extract_outline, extract_table_columns

OLLAMA_BASE = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"
CHROMA_DIR = "data/chroma"
COLLECTION = "termos_referencia"
TEMPLATES_DIR = Path("data/templates")


def chunk_text(text: str, max_chars=1000, overlap=150):
    text = " ".join(text.replace("\r", " ").split())
    i = 0
    while i < len(text):
        yield text[i:i+max_chars]
        i += max_chars - overlap


def ollama_embed(texts: list[str]) -> list[list[float]]:
    resp = requests.post(
        f"{OLLAMA_BASE}/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=180
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def _client():
    return chromadb.PersistentClient(
        path=CHROMA_DIR,
        settings=Settings(anonymized_telemetry=False)
    )

def get_collection():
    return _client().get_or_create_collection(COLLECTION)


def reset_collection():
    c = _client()
    try:
        c.delete_collection(COLLECTION)
    except Exception:
        pass
    return c.get_or_create_collection(COLLECTION)


def _save_template(source_name: str, raw_text: str):
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    tpl = {
        "source": source_name,
        "outline": extract_outline(raw_text),
        "table_columns": extract_table_columns(raw_text),
        "style_sample": raw_text[:1200]
    }
    (TEMPLATES_DIR / f"{source_name}.json").write_text(
        json.dumps(tpl, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def index_docs(folder="data/docs", reset: bool = False):
    folder = Path(folder)
    col = reset_collection() if reset else get_collection()

    docs = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in [".pdf", ".docx", ".txt", ".doc"]]
    if not docs:
        return {"ok": False, "msg": "Nenhum arquivo encontrado em data/docs"}

    added = 0

    for doc_path in docs:
        raw = load_text(doc_path)

        # salva template do TR (padronização)
        _save_template(doc_path.name, raw)

        chunks = list(chunk_text(raw))
        embs = ollama_embed(chunks)

        ids = []
        metadatas = []
        for idx in range(len(chunks)):
            ids.append(f"{doc_path.name}::chunk::{idx}")
            metadatas.append({"source": doc_path.name, "chunk": idx})

        col.add(ids=ids, documents=chunks, embeddings=embs, metadatas=metadatas)
        added += len(chunks)

    return {"ok": True, "files": len(docs), "chunks_added": added, "reset": reset}