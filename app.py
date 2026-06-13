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
  POST /chat             → interface conversacional (autenticada, persistida no banco)
  GET  /chats            → lista os chats do usuário logado (título + data)
  GET  /chats/{conversation_id} → histórico de mensagens + TR ativo de um chat
  PATCH  /chats/{conversation_id} → renomeia o chat
  DELETE /chats/{conversation_id} → exclui o chat (e seu histórico)
  POST /chats/{conversation_id}/contexto → anexa arquivo como contexto da sessão
  GET  /health           → status da API
"""

from fastapi import FastAPI, HTTPException, Query, Depends, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

import os
import shutil
import tempfile
from pathlib import Path

from rag.ingest import index_docs
from rag.rag import rag_answer
from rag.conversation_store import STORE
from auth.auth import login, require_auth, require_admin, hash_password
from auth.schemas import LoginRequest, TokenResponse, TokenData
from utils.upload_funcs.upload_documento import processar_upload
from utils.list_funcs.listar_documento import listar_documentos
from utils.remove_funcs.remover_documento import remover_documento
from utils.loaders import load_text

app = FastAPI(
    title="FSPH - RAG + Ollama API",
    description=(
        "API de geração de Termos de Referência com RAG voltada para a FSPH.\n\n"
        "Pipeline: autenticação JWT → classificação de intenção → busca semântica "
        "→ escolha de perfil HTML → prompt dinâmico → LLM → parse JSON → Jinja2."
    ),
    version="3.2.0",
    openapi_tags=[
        {"name": "Autenticação", "description": "Login e verificação de identidade."},
        {"name": "Administração", "description": "Ingestão e indexação da base documental."},
        {"name": "Geração de TR", "description": "Geração completa de Termos de Referência."},
        {"name": "Chat", "description": "Chat conversacional persistido (multi-chat por usuário)."},
        {"name": "Documentos", "description": "Upload, listagem e remoção de documentos."},
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
    question: str = Field(
        ...,
        description="Qualquer mensagem: saudação, dúvida técnica ou pedido de TR.",
        examples=["Oi, tudo bem?", "Preciso contratar 300 cadeiras ergonômicas."],
    )
    top_k: int = Field(6, ge=1, le=20)
    conversation_id: str | None = Field(
        default=None,
        description=(
            "Identificador do chat (inteiro em texto, ex.: \"12\"). Omita na primeira "
            "mensagem — o backend cria o chat, vincula ao usuário logado e devolve o id. "
            "Reenvie esse id nas mensagens seguintes para manter o contexto do TR e poder "
            "editá-lo depois. O chat fica salvo no banco e sobrevive ao reinício do servidor."
        ),
        examples=["12"],
    )


class RenameChatRequest(BaseModel):
    titulo: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Novo título do chat.",
        examples=["Cadeiras ergonômicas - almoxarifado"],
    )


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
# Helpers de chat
# ---------------------------------------------------------------------------
def _require_owned_chat(conversation_id: str, user_id: int) -> dict:
    """Carrega o chat e garante que ele pertence ao usuário logado.

    404 se não existir; 403 se for de outro usuário.
    """
    convo = STORE.get(conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Chat não encontrado.")
    if convo.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Este chat pertence a outro usuário.")
    return convo


# ---------------------------------------------------------------------------
# Chat endpoint (interagir com a IA)
# ---------------------------------------------------------------------------
@app.post(
    "/chat",
    tags=["Chat"],
    summary="Interagir com a IA (conversacional, persistido)",
    description=(
        "Aceita qualquer mensagem e roteia pela intenção detectada. **Requer login** "
        "(`Authorization: Bearer <token>`).\n\n"
        "O chat é salvo no banco e vinculado ao usuário. Ao gerar um TR, ele fica "
        "guardado sob o `conversation_id` devolvido. Reenvie esse `conversation_id` nas "
        "próximas mensagens para editar tópicos (ex.: \"No tópico 7, troque o fiscal\") "
        "ou pedir explicações — inclusive em outra sessão, depois de reiniciar o servidor. "
        "Toda geração e edição de TR continua passando pela LLM.\n\n"
        "Omita `conversation_id` para abrir um chat novo; o título é derivado da primeira "
        "mensagem (estilo ChatGPT).\n\n"
        "`?format=json` (padrão) → JSON com `type`, `conversation_id`, `html`, etc.\n"
        "`?format=html` → HTML renderizado direto (sem o `conversation_id`; "
        "para o fluxo conversacional use `format=json`).\n\n"
        "Valores de `type`: `conversational`, `document_query`, `tr`, "
        "`tr_update`, `tr_explain`, `error`."
    ),
)
def chat(
    req: ChatRequest,
    format: str = Query(default="json", pattern="^(json|html)$"),
    current_user: TokenData = Depends(require_auth),
):
    try:
        result = rag_answer(
            req.question,
            top_k=req.top_k,
            conversation_id=req.conversation_id,
            user_id=current_user.user_id,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Este chat pertence a outro usuário.")
    except LookupError:
        raise HTTPException(status_code=404, detail="Chat não encontrado.")

    if format == "html":
        if result.get("type") in ("tr", "tr_update"):
            return HTMLResponse(content=result.get("html", "<p>Erro ao gerar TR.</p>"))
        return HTMLResponse(content=f"<p>{result.get('message', '')}</p>")

    return result


# ---------------------------------------------------------------------------
# Gestão de chats (multi-chat por usuário)
# ---------------------------------------------------------------------------
@app.get(
    "/chats",
    tags=["Chat"],
    summary="Listar chats do usuário",
    description=(
        "Retorna os chats do usuário logado, mais recentes primeiro. Cada item traz "
        "`conversation_id`, `titulo`, datas de criação/atualização e `has_tr` (se já há "
        "um TR ativo na conversa). Alimenta a barra lateral estilo ChatGPT."
    ),
)
def list_chats(current_user: TokenData = Depends(require_auth)):
    return {"chats": STORE.list_for_user(current_user.user_id)}


@app.get(
    "/chats/{conversation_id}",
    tags=["Chat"],
    summary="Detalhes de um chat",
    description=(
        "Recupera todo o histórico de mensagens da conversa e o TR atualmente ativo "
        "(`current_document`). Use para restaurar a sessão ao abrir um chat antigo."
    ),
)
def get_chat(conversation_id: str, current_user: TokenData = Depends(require_auth)):
    return _require_owned_chat(conversation_id, current_user.user_id)


@app.patch(
    "/chats/{conversation_id}",
    tags=["Chat"],
    summary="Renomear um chat",
    description="Atualiza o título do chat (o que aparece na barra lateral).",
)
def rename_chat(
    conversation_id: str,
    req: RenameChatRequest,
    current_user: TokenData = Depends(require_auth),
):
    _require_owned_chat(conversation_id, current_user.user_id)
    STORE.set_title(conversation_id, req.titulo)
    return {"ok": True, "conversation_id": conversation_id, "titulo": req.titulo}


@app.delete(
    "/chats/{conversation_id}",
    tags=["Chat"],
    summary="Excluir um chat",
    description="Remove o chat e, em cascata, todo o seu histórico de mensagens e contextos.",
)
def delete_chat(conversation_id: str, current_user: TokenData = Depends(require_auth)):
    _require_owned_chat(conversation_id, current_user.user_id)
    STORE.delete(conversation_id)
    return {"ok": True, "conversation_id": conversation_id}


@app.post(
    "/chats/{conversation_id}/contexto",
    tags=["Chat"],
    summary="Anexar contexto à conversa (upload)",
    description=(
        "Recebe um arquivo (PDF, DOCX, TXT ou DOC) via upload, extrai o texto e o vincula "
        "como **contexto exclusivo daquela conversa**. A partir daí, a geração e a edição "
        "de TR daquele chat priorizam o conteúdo enviado. Pensado para o 'drag and drop' "
        "do frontend."
    ),
)
async def upload_contexto(
    conversation_id: str,
    arquivo: UploadFile = File(...),
    current_user: TokenData = Depends(require_auth),
):
    _require_owned_chat(conversation_id, current_user.user_id)

    ext = Path(arquivo.filename or "").suffix.lower()
    if ext not in {".pdf", ".docx", ".txt", ".doc"}:
        raise HTTPException(
            status_code=400,
            detail="Formato não suportado. Envie PDF, DOCX, TXT ou DOC.",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        shutil.copyfileobj(arquivo.file, tmp)
        tmp_path = tmp.name
    try:
        texto = load_text(Path(tmp_path))
    finally:
        os.remove(tmp_path)

    texto = (texto or "").strip()
    if not texto:
        raise HTTPException(
            status_code=422,
            detail="Não foi possível extrair texto do arquivo enviado.",
        )

    STORE.add_context(conversation_id, arquivo.filename or f"arquivo{ext}", texto)
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "arquivo": arquivo.filename,
        "caracteres_extraidos": len(texto),
    }


# Alias retrocompatível (o frontend anterior chamava GET /chat/{id}).
@app.get(
    "/chat/{conversation_id}",
    tags=["Chat"],
    summary="Detalhes de um chat (alias de /chats/{id})",
    description="Mantido por compatibilidade. Prefira `GET /chats/{conversation_id}`.",
)
def get_conversation(conversation_id: str, current_user: TokenData = Depends(require_auth)):
    return _require_owned_chat(conversation_id, current_user.user_id)


# ---------------------------------------------------------------------------
# Document endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/documentos/upload",
    tags=["Documentos"],
    summary="Upload de documento",
    description="Faz upload de um documento (PDF, DOCX, TXT) e o indexa automaticamente.",
)
async def upload_documento(arquivo: UploadFile = File(...)):
    """Upload de um documento para indexação."""
    return await processar_upload(arquivo)


@app.get(
    "/documentos/listar",
    tags=["Documentos"],
    summary="Listar documentos",
    description="Lista todos os documentos disponíveis na base.",
)
def listar_docs():
    """Lista todos os documentos indexados."""
    return listar_documentos()


@app.delete(
    "/documentos/{nome_arquivo}",
    tags=["Documentos"],
    summary="Remover documento",
    description="Remove um documento da base e reindexa.",
)
def remover_doc(nome_arquivo: str):
    """Remove um documento específico."""
    return remover_documento(nome_arquivo)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Sistema"], summary="Verificar saúde da API")
def health():
    return {"ok": True, "version": "3.2.0"}
