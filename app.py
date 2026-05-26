"""
app.py
API FastAPI da FSPH — RAG + Ollama + geração de TR em HTML + Autenticação.

python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000

Endpoints:
  POST /auth/login       → autentica e devolve JWT
  GET  /auth/me          → retorna dados do usuário autenticado (token válido)
  POST /admin/index      → indexa/reindexar os docs de data/docs   [admin]
  POST /generate-tr      → gera o TR completo (HTML + JSON)
  POST /generate-tr/html → retorna o HTML puro do TR
  POST /chat             → interface conversacional unificada
  GET  /health           → status da API
"""

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

from rag.ingest import index_docs
from rag.rag import rag_answer
from auth.auth import login, require_auth, require_admin, hash_password
from auth.schemas import LoginRequest, TokenResponse, TokenData

app = FastAPI(
    title="FSPH - RAG + Ollama API",
    description=(
        "API de geração de Termos de Referência com RAG voltada para a FSPH.\n\n"
        "Pipeline: autenticação JWT → classificação de intenção → busca semântica "
        "→ escolha de perfil HTML → prompt dinâmico → LLM → parse JSON → Jinja2."
    ),
    version="3.0.0",
    openapi_tags=[
        {"name": "Autenticação", "description": "Login e verificação de identidade."},
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
# Schemas (RAG)
# ---------------------------------------------------------------------------
class GenerateTRRequest(BaseModel):
    question: str = Field(
        ...,
        description="Descreva o que precisa ser contratado.",
        examples=["Preciso contratar confecção de brindes para o Dia do Doador."],
    )
    top_k: int = Field(6, ge=1, le=20)


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        description="Qualquer mensagem: saudação, dúvida técnica ou pedido de TR.",
        examples=["Oi, tudo bem?", "Preciso contratar 300 cadeiras ergonômicas."],
    )
    top_k: int = Field(6, ge=1, le=20)


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/auth/login",
    tags=["Autenticação"],
    response_model=TokenResponse,
    summary="Autenticar usuário",
    description=(
        "Recebe email e senha, valida no PostgreSQL e retorna um JWT.\n\n"
        "O campo `role` indica o perfil: `user` ou `admin`.\n"
        "Inclua o token em todas as rotas protegidas como:\n"
        "`Authorization: Bearer <token>`"
    ),
)
def auth_login(req: LoginRequest):
    """Autentica e devolve o token de acesso."""
    return login(req.email, req.password)


@app.get(
    "/auth/me",
    tags=["Autenticação"],
    summary="Dados do usuário autenticado",
    description="Valida o token Bearer e retorna o user_id e role do usuário logado.",
)
def auth_me(current_user: TokenData = Depends(require_auth)):
    """Retorna os dados do token decodificado. Útil para o frontend verificar a sessão."""
    return {"user_id": current_user.user_id, "role": current_user.role}


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/admin/index",
    tags=["Administração"],
    summary="Indexar documentos da FSPH",
    description="Requer role `admin`. Indexa/reindexar os docs de `data/docs`.",
)
def admin_index(reset: bool = False, _: TokenData = Depends(require_admin)):
    """Atualiza ou reinicia a base vetorial usada pelo mecanismo RAG."""
    return index_docs("data/docs", reset=reset)


# ---------------------------------------------------------------------------
# TR endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/generate-tr",
    tags=["Geração de TR"],
    summary="Gerar Termo de Referência completo",
)
def generate_tr(req: GenerateTRRequest):
    result = rag_answer(req.question, top_k=req.top_k)
    if result.get("type") != "tr":
        raise HTTPException(
            status_code=400,
            detail="A mensagem não descreve uma contratação. Use /chat para conversas.",
        )
    return result


@app.post(
    "/generate-tr/html",
    tags=["Geração de TR"],
    summary="Gerar TR e retornar como HTML",
    response_class=HTMLResponse,
)
def generate_tr_html(req: GenerateTRRequest):
    result = rag_answer(req.question, top_k=req.top_k)
    if result.get("type") != "tr":
        return HTMLResponse(content="<p>A mensagem não descreve uma contratação.</p>", status_code=400)
    return HTMLResponse(content=result.get("html", "<p>Erro ao gerar TR.</p>"))


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------
@app.post(
    "/chat",
    tags=["Chat"],
    summary="Interface conversacional unificada",
    description=(
        "Aceita qualquer mensagem e roteia pela intenção detectada.\n\n"
        "`?format=json` (padrão) → JSON com campo `type`\n"
        "`?format=html` → HTML renderizado direto"
    ),
)
def chat(
    req: ChatRequest,
    format: str = Query(default="json", pattern="^(json|html)$"),
):
    result = rag_answer(req.message, top_k=req.top_k)

    if format == "html":
        if result.get("type") == "tr":
            return HTMLResponse(content=result.get("html", "<p>Erro ao gerar TR.</p>"))
        return HTMLResponse(content=f"<p>{result.get('message', '')}</p>")

    return result


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Sistema"], summary="Verificar saúde da API")
def health():
    return {"ok": True, "version": "3.0.0"}
