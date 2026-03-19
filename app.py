"""
app.py
API FastAPI da FSPH — RAG + Ollama + geração de TR em HTML.

Endpoints:
  POST /admin/index     → indexa/reindexar os docs de data/docs
  POST /generate-tr     → gera o Termo de Referência completo (HTML + JSON)
  POST /generate-tr/html → Gera o HTML puro do TR
  POST /chat            → mantido por compatibilidade; retorna texto + fontes
  GET  /health          → status da API
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from rag.ingest import index_docs
from rag.rag import rag_answer

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
        {
            "name": "Administração",
            "description": "Operações de ingestão e indexação da base documental.",
        },
        {
            "name": "Geração de TR",
            "description": "Geração completa de Termos de Referência em HTML.",
        },
        {
            "name": "Sistema",
            "description": "Endpoints de status e verificação operacional.",
        },
    ],
)


# ---------------------------------------------------------------------------
# Schemas de entrada
# ---------------------------------------------------------------------------
class IndexRequest(BaseModel):
    reset: bool = Field(
        False,
        description="Se True, apaga a coleção antes de reindexar.",
    )


class GenerateTRRequest(BaseModel):
    """Payload para geração de um Termo de Referência."""

    question: str = Field(
        ...,
        description=(
            "Descreva o que precisa ser contratado. Quanto mais detalhes "
            "(objeto, quantidade, finalidade), melhor o TR gerado."
        ),
        examples=[
            "Preciso contratar confecção de brindes para o Dia do Doador de Sangue: "
            "250 sacolas ecobag, 250 canetas e 500 copos de bambu personalizados."
        ],
    )
    top_k: int = Field(
        6,
        ge=1,
        le=20,
        description="Quantidade de trechos recuperados na busca semântica (RAG).",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/admin/index",
    tags=["Administração"],
    summary="Indexar documentos da FSPH",
    description=(
        "Executa a ingestão e indexação dos arquivos do diretório `data/docs`. "
        "Use `reset=true` para limpar a base antes de reindexar."
    ),
)
def admin_index(reset: bool = False):
    """Atualiza ou reinicia a base vetorial usada pelo mecanismo RAG."""
    return index_docs("data/docs", reset=reset)


@app.post(
    "/generate-tr",
    tags=["Geração de TR"],
    summary="Gerar Termo de Referência completo",
    description=(
        "Recebe uma descrição da contratação e retorna:\n"
        "- `html`: o TR renderizado em HTML, pronto para exibição ou impressão\n"
        "- `profile`: perfil de template utilizado (servico_padrao | bens | evento_curto)\n"
        "- `base_source`: TR histórico usado como base de estilo\n"
        "- `table_columns`: colunas da tabela de itens detectadas\n"
        "- `sources`: trechos recuperados pelo RAG com suas distâncias\n\n"
        "O campo `llm_raw` contém a saída bruta do LLM (útil para debug)."
    ),
)
def generate_tr(req: GenerateTRRequest):
    """Endpoint principal de geração de TRs da FSPH."""
    return rag_answer(req.question, top_k=req.top_k)


@app.post(
    "/generate-tr/html",
    tags=["Geração de TR"],
    summary="Gerar TR e retornar diretamente como HTML",
    description=(
        "Igual ao `/generate-tr`, mas retorna o HTML renderizado diretamente "
        "como `text/html`, facilitando a visualização no browser."
    ),
    response_class=HTMLResponse,
)
def generate_tr_html(req: GenerateTRRequest):
    """Retorna o TR como página HTML navegável."""
    result = rag_answer(req.question, top_k=req.top_k)
    return HTMLResponse(content=result.get("html", "<p>Erro ao gerar TR.</p>"))


@app.post(
    "/chat",
    tags=["Geração de TR"],
    summary="[Legado] Responder perguntas com contexto documental",
    description=(
        "Mantido por compatibilidade. Internamente chama o mesmo pipeline "
        "de `/generate-tr`. Retorna o HTML gerado no campo `answer`."
    ),
)
def chat(req: GenerateTRRequest):
    """Endpoint legado — use /generate-tr para a resposta estruturada."""
    result = rag_answer(req.question, top_k=req.top_k)
    return {
        "answer": result.get("html", ""),
        "base_source": result.get("base_source", ""),
        "sources": result.get("sources", []),
    }


@app.get(
    "/health",
    tags=["Sistema"],
    summary="Verificar saúde da API",
    description="Confirma se a API está online e operacional.",
)
def health():
    """Retorna o status básico de disponibilidade da aplicação."""
    return {"ok": True, "version": "2.0.0"}
