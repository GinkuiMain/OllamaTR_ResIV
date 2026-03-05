from fastapi import FastAPI
from pydantic import BaseModel
from rag.ingest import index_docs
from rag.rag import rag_answer
# python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
# chroma/chroma.sqlite3 é gerado automaticamente na primeira indexação, não precisa criar manualmente
# Mas se quiser regenerar, só deletar!!!

app = FastAPI(title="RAG + Ollama API")


class AskRequest(BaseModel):
    question: str
    top_k: int = 6


@app.post("/admin/index")
def admin_index():
    return index_docs("data/docs")


@app.post("/chat")
def chat(req: AskRequest):
    return rag_answer(req.question, top_k=req.top_k)


@app.get("/health") # GET: /health
def health():
    return {"ok": True}