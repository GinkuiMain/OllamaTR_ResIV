from fastapi import FastAPI
from pydantic import BaseModel, Field
from rag.ingest import index_docs
from rag.rag import rag_answer

# python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
# chroma/chroma.sqlite3 é gerado automaticamente na primeira indexação, não precisa criar manualmente
# Mas se quiser regenerar, só deletar!!!

app = FastAPI(
    title="FSPH - RAG + Ollama API",
    description=(
        "API de perguntas e respostas com RAG voltada para a FSPH "
        "(Fundação de Saúde Parreiras Horta).\n\n"
    ),
    version="1.0.0",
    openapi_tags=[
        {
            "name": "Administração",
            "description": "Operações de ingestão e indexação da base documental.",
        },
        {
            "name": "Atendimento",
            "description": "Consulta de informações institucionais da FSPH via RAG.",
        },
        {
            "name": "Sistema",
            "description": "Endpoints de status e verificação operacional.",
        },
    ],
)


class AskRequest(BaseModel):
    """Payload de entrada para o endpoint de consulta `/chat`."""

    question: str = Field(
        ...,
        description="Pergunta em linguagem natural sobre documentos e processos da FSPH.",
        examples=["Qual é o fluxo de manutenção de TIC da FSPH?"],
    )
    top_k: int = Field(
        6,
        ge=1,
        le=20,
        description=(
            "Quantidade de trechos recuperados na busca semântica para compor o contexto "
            "da resposta."
        ),
        examples=[6],
    )


@app.post(
    "/admin/index",
    tags=["Administração"],
    summary="Indexar documentos da FSPH",
    description=(
        "Executa a ingestão e indexação dos arquivos do diretório `data/docs`. "
        "Use este endpoint sempre que novos documentos forem adicionados, removidos "
        "ou alterados."
    ),
)
def admin_index():
    """Atualiza a base vetorial usada pelo mecanismo RAG."""
    return index_docs("data/docs")


@app.post(
    "/chat",
    tags=["Atendimento"],
    summary="Responder perguntas com contexto documental",
    description=(
        "Recebe uma pergunta e retorna uma resposta gerada pelo pipeline RAG com base "
        "nos documentos institucionais da FSPH indexados na base vetorial."
    ),
)
def chat(req: AskRequest):
    """Endpoint principal de consulta dos usuários da FSPH."""
    return rag_answer(req.question, top_k=req.top_k)


@app.get(
    "/health",
    tags=["Sistema"],
    summary="Verificar saúde da API",
    description="Endpoint de health check para confirmar que a API está disponível.",
)  # GET: /health
def health():
    """Retorna o status básico de disponibilidade da aplicação."""
    return {"ok": True}
