"""
app.py
API FastAPI da FSPH — RAG + Ollama + geração de TR em HTML.

Endpoints:
  POST /admin/index               → indexa/reindexar os docs de data/docs
  POST /generate-tr               → gera o Termo de Referência completo (HTML + JSON)
  POST /generate-tr/html          → Gera o HTML puro do TR
  POST /chat                      → mantido por compatibilidade; retorna texto + fontes
  GET  /health                    → status da API
  POST /admin/upload-documento    → Recebe um arquivo e salva em data/docs
"""
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from rag.ingest import index_docs
from rag.rag import rag_answer
from utils.upload_funcs.upload_documento import processar_upload
from utils.list_funcs.listar_documento import listar_documentos
from utils.remove_funcs.remover_documento import remover_documento

app = FastAPI(
    title="FSPH - RAG + Ollama API",
    description=(
        "API de geração de Termos de Referência com RAG voltada para a FSPH "
        "(Fundação de Saúde Parreiras Horta).\n\n"
        "Pipeline: busca semântica → escolha de perfil HTML → prompt dinâmico "
        "→ LLM (Mistral/Ollama) → parse JSON → renderização Jinja2."
    ),
    version="2.0.0",
    openapi_tags=[
        {"name": "Administração", "description": "Operações de ingestão e indexação da base documental."},
        {"name": "Geração de TR", "description": "Geração completa de Termos de Referência em HTML."},
        {"name": "Sistema", "description": "Endpoints de status e verificação operacional."},
    ],
)


# ---------------------------------------------------------------------------
# Schemas de entrada
# ---------------------------------------------------------------------------
class IndexRequest(BaseModel):
    reset: bool = Field(False, description="Se True, apaga a coleção antes de reindexar.")


class GenerateTRRequest(BaseModel):
    question: str = Field(
        ...,
        description="Descreva o que precisa ser contratado.",
        examples=["Preciso contratar confecção de brindes para o Dia do Doador de Sangue."],
    )
    top_k: int = Field(6, ge=1, le=20, description="Quantidade de trechos recuperados no RAG.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/admin/index", tags=["Administração"], summary="Indexar documentos da FSPH")
def admin_index(reset: bool = False):
    return index_docs("data/docs", reset=reset)


@app.post("/generate-tr", tags=["Geração de TR"], summary="Gerar Termo de Referência completo")
def generate_tr(req: GenerateTRRequest):
    return rag_answer(req.question, top_k=req.top_k)


@app.post("/generate-tr/html", tags=["Geração de TR"], summary="Gerar TR como HTML", response_class=HTMLResponse)
def generate_tr_html(req: GenerateTRRequest):
    result = rag_answer(req.question, top_k=req.top_k)
    return HTMLResponse(content=result.get("html", "<p>Erro ao gerar TR.</p>"))


@app.post("/chat", tags=["Geração de TR"], summary="[Legado] Responder com contexto documental")
def chat(req: GenerateTRRequest):
    result = rag_answer(req.question, top_k=req.top_k)
    return {
        "answer": result.get("html", ""),
        "base_source": result.get("base_source", ""),
        "sources": result.get("sources", []),
    }


@app.post("/admin/upload-documento", tags=["Administração"], summary="Fazer upload de um documento")
async def upload_documento(arquivo: UploadFile = File(...)):
    return await processar_upload(arquivo)  # ← delega para a utils


@app.get("/admin/listar-documentos", tags=["Administração"], summary="Listar documentos anexados")
def listar_documentos_endpoint():
    return listar_documentos()


@app.delete("/admin/remover-documento/{nome_arquivo}", tags=["Administração"], summary="Remover documento anexado")
def remover_documento_endpoint(nome_arquivo: str):
    return remover_documento(nome_arquivo)


@app.get("/health", tags=["Sistema"], summary="Verificar saúde da API")
def health():
    return {"ok": True, "version": "2.0.0"}