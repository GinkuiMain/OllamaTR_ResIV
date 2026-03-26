"""
app.py
API FastAPI da FSPH — RAG + Ollama + geração de TR em HTML.

Endpoints:
  POST /admin/index      → indexa/reindexar os docs de data/docs
  POST /generate-tr      → gera o Termo de Referência completo (HTML + JSON)
  POST /generate-tr/html → retorna o HTML puro do TR
  POST /chat             → endpoint unificado: responde qualquer tipo de mensagem
  GET  /health           → status da API
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from rag.ingest import index_docs
from rag.rag import rag_answer
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="FSPH - RAG + Ollama API",
    description=(
        "API de geração de Termos de Referência com RAG voltada para a FSPH "
        "(Fundação de Saúde Parreiras Horta).\n\n"
        "Pipeline: classificação de intenção → busca semântica → escolha de perfil "
        "HTML → prompt dinâmico → LLM (Ollama) → parse JSON → renderização Jinja2."
    ),
    version="2.1.0",
    openapi_tags=[
        {"name": "Administração", "description": "Ingestão e indexação da base documental."},
        {"name": "Geração de TR", "description": "Geração completa de Termos de Referência."},
        {"name": "Chat", "description": "Interface conversacional unificada."},
        {"name": "Sistema", "description": "Status e verificação operacional."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8080",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class GenerateTRRequest(BaseModel):
    question: str = Field(
        ...,
        description=(
            "Descreva o que precisa ser contratado. Quanto mais detalhes "
            "(objeto, quantidade, finalidade), melhor o TR gerado."
        ),
        examples=["Preciso contratar confecção de brindes para o Dia do Doador."],
    )
    top_k: int = Field(
        6, ge=1, le=20,
        description="Quantidade de trechos recuperados na busca semântica.",
    )


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        description="Qualquer mensagem: saudação, dúvida técnica ou pedido de TR.",
        examples=["Oi, tudo bem?", "Como funciona o registro de preços?",
                  "Preciso contratar 300 cadeiras ergonômicas."],
    )
    top_k: int = Field(6, ge=1, le=20)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/admin/index", tags=["Administração"],
          summary="Indexar documentos da FSPH")
def admin_index(reset: bool = False):
    """Atualiza ou reinicia a base vetorial usada pelo mecanismo RAG."""
    return index_docs("data/docs", reset=reset)


@app.post("/generate-tr", tags=["Geração de TR"],
          summary="Gerar Termo de Referência completo")
def generate_tr(req: GenerateTRRequest):
    """
    Endpoint direto de geração de TR.
    Lança 400 se o usuário não descreveu uma contratação.
    """
    result = rag_answer(req.question, top_k=req.top_k)
    if result.get("type") != "tr":
        raise HTTPException(
            status_code=400,
            detail=(
                "A mensagem não descreve uma contratação. "
                "Use /chat para conversas ou dúvidas gerais."
            ),
        )
    return result


@app.post("/generate-tr/html", tags=["Geração de TR"],
          summary="Gerar TR e retornar diretamente como HTML",
          response_class=HTMLResponse)
def generate_tr_html(req: GenerateTRRequest):
    """Retorna o TR como página HTML navegável."""
    result = rag_answer(req.question, top_k=req.top_k)
    if result.get("type") != "tr":
        return HTMLResponse(
            content="<p>A mensagem não descreve uma contratação.</p>",
            status_code=400,
        )
    return HTMLResponse(content=result.get("html", "<p>Erro ao gerar TR.</p>"))


@app.post("/chat", tags=["Chat"],
          summary="Interface conversacional unificada")
def chat(req: ChatRequest, format: str = Query(default="json", pattern="^(json|html)$")):
    """
    Aceita qualquer mensagem e roteia pela intenção.

    Parâmetro de query opcional:
      ?format=json  (padrão) → retorna JSON com campo 'type'
      ?format=html           → se for TR, retorna HTML renderizado direto
    """
    result = rag_answer(req.message, top_k=req.top_k)

    if format == "html":
        if result.get("type") == "tr":
            return HTMLResponse(content=result.get("html", "<p>Erro ao gerar TR.</p>"))
        # Para conversational/document_query, HTML simples
        msg = result.get("message", "")
        return HTMLResponse(content=f"<p>{msg}</p>")

    return result


@app.get("/health", tags=["Sistema"], summary="Verificar saúde da API")
def health():
    return {"ok": True, "version": "2.1.0"}
