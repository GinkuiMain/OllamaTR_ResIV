"""
rag/review_store.py
Esteira de Revisão de TRs (Kanban).

Persiste, no PostgreSQL, os TRs GERADOS pela IA que entram no fluxo de revisão
(pending -> approved | rejected) e expõe a orquestração:

  - promover um TR gerado num chat para a esteira (create_from_conversation);
  - aprovar / reprovar (com motivo obrigatório);
  - chat de correção de um TR reprovado, que gera uma nova versão e o devolve
    para a fila — reaproveitando o mesmo editor por LLM usado no chat principal.

As respostas são montadas no formato que o front-end espera (TRDocument, em
camelCase): id, title, category, createdAt, generatedBy, status, version,
preview, fullContent, analysisSummary, sourceDocuments, reviewer, reviewedAt,
rejectionReason.

Tabela: ver tr_review.sql (trGerado). Colunas em minúsculas (convenção do
PostgreSQL para nomes não-aspeados), por isso lemos as chaves em minúsculo.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

VALID_STATUS = {"pending", "approved", "rejected"}

# Diretórios onde os arquivos-fonte PODEM estar (para tentar inferir o tamanho).
_SOURCE_DIRS = [Path("data/docs"), Path("data/templates"), Path("data")]


# ---------------------------------------------------------------------------
# Helpers de serialização (puros)
# ---------------------------------------------------------------------------
def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _markdown_table(columns: list[str], rows: list[dict]) -> str:
    if not columns:
        return ""
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows or []:
        body.append("| " + " | ".join(str(row.get(c, "")) for c in columns) + " |")
    return "\n".join([head, sep] + body)


def document_to_markdown(document: dict) -> str:
    """Converte o documento estruturado (sections) em texto Markdown (fullContent)."""
    if not document:
        return ""
    linhas = []
    titulo = document.get("document_title") or "TERMO DE REFERÊNCIA"
    linhas.append(f"# {titulo}\n")

    for section in document.get("sections", []):
        sid = section.get("id", "")
        stitle = section.get("title", "")
        cabecalho = f"## {sid}. {stitle}".strip().rstrip(".")
        linhas.append(cabecalho)

        for paragrafo in section.get("content", []) or []:
            linhas.append(str(paragrafo))

        tabela = _markdown_table(
            section.get("table_columns", []),
            section.get("table_rows", []),
        )
        if tabela:
            linhas.append("")
            linhas.append(tabela)

        linhas.append("")  # linha em branco entre tópicos

    return "\n".join(linhas).strip()


def make_preview(full_content: str, limit: int = 180) -> str:
    """Resumo curto (1-2 linhas) para o card do Kanban."""
    if not full_content:
        return ""
    # ignora a linha de título (#) e pega o primeiro parágrafo real
    for linha in full_content.splitlines():
        t = linha.strip().lstrip("#").strip()
        if t and not t.startswith("|") and not t.startswith("---"):
            if t == (full_content.splitlines()[0].strip().lstrip("#").strip()):
                continue  # é o título do documento
            return (t[: limit - 1] + "…") if len(t) > limit else t
    # fallback: começo do texto
    flat = " ".join(full_content.split())
    return (flat[: limit - 1] + "…") if len(flat) > limit else flat


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unidade in ("B", "KB", "MB", "GB"):
        if size < 1024 or unidade == "GB":
            return f"{size:.1f} {unidade}".replace(".0 ", " ")
        size /= 1024
    return f"{size:.1f} GB"


def _guess_size(filename: str) -> str:
    """Tenta achar o arquivo-fonte em disco para informar o tamanho. Best-effort."""
    if not filename:
        return ""
    for base in _SOURCE_DIRS:
        candidato = base / filename
        try:
            if candidato.is_file():
                return _human_size(candidato.stat().st_size)
        except OSError:
            pass
    return ""  # arquivos originais podem não ser mantidos após a indexação


def sources_to_documents(sources: list[dict]) -> list[dict]:
    """
    Mapeia as fontes do RAG ([{source, chunk, distance}]) para o formato
    SourceDocument ([{id, name, type, size}]), deduplicando por arquivo.
    """
    vistos: dict[str, dict] = {}
    for src in sources or []:
        nome = src.get("source") or "documento"
        if nome in vistos:
            continue
        ext = Path(nome).suffix.lower().lstrip(".")
        vistos[nome] = {
            "id": nome,                       # identificador estável da fonte
            "name": nome,
            "type": ext.upper() if ext else "DOC",
            "size": _guess_size(nome),
        }
    return list(vistos.values())


def _build_analysis_prompt(document: dict, source_names: list[str]) -> str:
    titulo = document.get("document_title") or "Termo de Referência"
    topicos = "; ".join(
        f'{s.get("id")}. {s.get("title")}' for s in document.get("sections", [])
    )
    fontes = ", ".join(source_names) if source_names else "modelos internos da FSPH"
    return f"""
Você é um analista da FSPH. Com base no Termo de Referência abaixo, produza um
JSON (e SOMENTE o JSON, sem texto antes ou depois) com duas chaves:

- "analysis_summary": um único parágrafo (3 a 5 frases, em português) explicando
  como o documento foi montado: que tipo de contratação ele cobre, em quais
  documentos de referência ele se apoiou e que estrutura/diretrizes foram
  seguidas. Escreva para um gestor entender a rastreabilidade.
- "category": uma categoria curta de classificação (ex.: "Tecnologia da
  Informação", "Mobiliário", "Serviços", "Obras", "Saúde").

Título do TR: {titulo}
Tópicos: {topicos}
Documentos de referência utilizados: {fontes}

JSON:
""".strip()


def generate_analysis(document: dict) -> tuple[str, str]:
    """
    Gera (analysisSummary, category) via LLM. Resiliente: se o LLM estiver
    indisponível ou não retornar JSON válido, devolve um resumo determinístico.
    """
    source_names = [
        s.get("source") for s in (document.get("sources") or []) if s.get("source")
    ]
    # dedup preservando ordem
    source_names = list(dict.fromkeys(source_names))

    fallback_resumo = (
        "Termo de Referência gerado com apoio de "
        f"{len(source_names) or 'documentos'} fonte(s) de referência da FSPH"
        + (f" ({', '.join(source_names)})" if source_names else "")
        + f". O documento segue a estrutura padrão, com "
        f"{len(document.get('sections', []))} tópico(s)."
    )
    fallback_categoria = "Não classificado"

    try:
        from .llm import ollama_generate, parse_llm_json
        prompt = _build_analysis_prompt(document, source_names)
        data = parse_llm_json(ollama_generate(prompt))
        resumo = (data.get("analysis_summary") or "").strip() or fallback_resumo
        categoria = (data.get("category") or "").strip() or fallback_categoria
        return resumo, categoria
    except Exception:
        # Ollama fora do ar, timeout, JSON inválido, etc.
        return fallback_resumo, fallback_categoria


# ---------------------------------------------------------------------------
# Store (PostgreSQL)
# ---------------------------------------------------------------------------
class ReviewStore:
    """Persistência dos TRs sob revisão. Uma conexão por operação."""

    def _connect(self):
        from auth.database import get_connection
        return get_connection()

    def _run(self, query: str, params: tuple = (), *, fetchone=False, fetchall=False):
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone() if fetchone else None
                rows = cur.fetchall() if fetchall else None
            conn.commit()
            if fetchone:
                return row
            if fetchall:
                return rows
            return None
        finally:
            conn.close()

    def _user_name(self, user_id: int) -> str | None:
        if user_id is None:
            return None
        row = self._run(
            "SELECT userName FROM usuario WHERE userId = %s",
            (user_id,),
            fetchone=True,
        )
        return row["username"] if row else None

    # --- serialização para a API (formato TRDocument do front) -------------
    def _row_to_api(self, row: dict, *, full: bool = True) -> dict:
        api = {
            "id": str(row["trid"]),
            "title": row["titulo"],
            "category": row["categoria"],
            "createdAt": _iso(row["criadoem"]),
            "generatedBy": row["geradopor"],
            "status": row["status"],
            "version": row["versao"],
            "preview": row["preview"] or "",
            "reviewer": row.get("revisadopor"),
            "reviewedAt": _iso(row.get("revisadoem")),
            "rejectionReason": row.get("motivoreprovacao"),
        }
        if full:
            api["fullContent"] = row.get("fullcontent") or ""
            api["analysisSummary"] = row.get("analiseresumo") or ""
            api["sourceDocuments"] = row.get("fontes") or []
        return api

    # --- criação -----------------------------------------------------------
    def create(
        self,
        *,
        titulo: str,
        categoria: str,
        preview: str,
        conteudo: dict,
        full_content: str,
        analise_resumo: str,
        fontes: list[dict],
        criado_por_id: int,
        conversa_id: int | None = None,
        gerado_por: str = "ai",
    ) -> dict:
        from psycopg2.extras import Json
        row = self._run(
            """
            INSERT INTO trGerado
                (titulo, categoria, geradoPor, status, versao, preview,
                 conteudo, fullContent, analiseResumo, fontes,
                 criadoPorId, conversaId)
            VALUES (%s, %s, %s, 'pending', 1, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                titulo, categoria, gerado_por, preview,
                Json(conteudo), full_content, analise_resumo, Json(fontes),
                criado_por_id, conversa_id,
            ),
            fetchone=True,
        )
        return self._row_to_api(row, full=True)

    # --- leitura -----------------------------------------------------------
    def _get_row(self, tr_id: int) -> dict | None:
        return self._run(
            "SELECT * FROM trGerado WHERE trId = %s", (tr_id,), fetchone=True
        )

    def get(self, tr_id: int, *, full: bool = True) -> dict | None:
        row = self._get_row(tr_id)
        return self._row_to_api(row, full=full) if row else None

    def list_trs(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        where = []
        params: list = []
        if status:
            where.append("status = %s")
            params.append(status)
        if q:
            where.append("(titulo ILIKE %s OR categoria ILIKE %s)")
            params.extend([f"%{q}%", f"%{q}%"])
        clause = ("WHERE " + " AND ".join(where)) if where else ""

        total_row = self._run(
            f"SELECT COUNT(*) AS total FROM trGerado {clause}",
            tuple(params),
            fetchone=True,
        )
        total = total_row["total"] if total_row else 0

        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        rows = self._run(
            f"""
            SELECT * FROM trGerado
            {clause}
            ORDER BY criadoEm DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params) + (page_size, offset),
            fetchall=True,
        ) or []

        return {
            "trs": [self._row_to_api(r, full=False) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # --- transições de status ---------------------------------------------
    def approve(self, tr_id: int, reviewer_id: int) -> dict | None:
        if self._get_row(tr_id) is None:
            return None
        nome = self._user_name(reviewer_id)
        row = self._run(
            """
            UPDATE trGerado
               SET status = 'approved',
                   revisadoPor = %s,
                   revisadoPorId = %s,
                   revisadoEm = NOW(),
                   motivoReprovacao = NULL
             WHERE trId = %s
            RETURNING *
            """,
            (nome, reviewer_id, tr_id),
            fetchone=True,
        )
        return self._row_to_api(row, full=True)

    def reject(self, tr_id: int, reviewer_id: int, reason: str) -> dict | None:
        if self._get_row(tr_id) is None:
            return None
        nome = self._user_name(reviewer_id)
        row = self._run(
            """
            UPDATE trGerado
               SET status = 'rejected',
                   revisadoPor = %s,
                   revisadoPorId = %s,
                   revisadoEm = NOW(),
                   motivoReprovacao = %s
             WHERE trId = %s
            RETURNING *
            """,
            (nome, reviewer_id, reason, tr_id),
            fetchone=True,
        )
        return self._row_to_api(row, full=True)

    # --- correção (nova versão, volta para a fila) ------------------------
    def save_correction(
        self, tr_id: int, *, conteudo: dict, full_content: str, preview: str
    ) -> dict | None:
        from psycopg2.extras import Json
        if self._get_row(tr_id) is None:
            return None
        row = self._run(
            """
            UPDATE trGerado
               SET conteudo = %s,
                   fullContent = %s,
                   preview = %s,
                   versao = versao + 1,
                   status = 'pending',
                   revisadoPor = NULL,
                   revisadoPorId = NULL,
                   revisadoEm = NULL,
                   motivoReprovacao = NULL
             WHERE trId = %s
            RETURNING *
            """,
            (Json(conteudo), full_content, preview, tr_id),
            fetchone=True,
        )
        return self._row_to_api(row, full=True)

    def get_conteudo(self, tr_id: int) -> dict | None:
        row = self._get_row(tr_id)
        if not row:
            return None
        return row.get("conteudo") or {}


REVIEW_STORE = ReviewStore()


# ---------------------------------------------------------------------------
# Orquestração (usa o chat persistido + o editor por LLM)
# ---------------------------------------------------------------------------
def create_from_conversation(
    conversation_id: str, user_id: int, category: str | None = None
) -> dict:
    """
    Promove o TR atual de um chat para a esteira de revisão (status 'pending').

    Lança LookupError (chat inexistente), PermissionError (chat de outro
    usuário) ou ValueError (chat ainda sem um TR gerado).
    """
    from .conversation_store import STORE

    convo = STORE.get(conversation_id)
    if convo is None:
        raise LookupError("Chat não encontrado.")
    if convo.get("user_id") != user_id:
        raise PermissionError("Este chat pertence a outro usuário.")

    document = convo.get("current_document")
    if not document or document.get("type") != "tr":
        raise ValueError("Este chat ainda não tem um Termo de Referência gerado.")

    full_content = document_to_markdown(document)
    preview = make_preview(full_content)
    fontes = sources_to_documents(document.get("sources") or [])
    analise, categoria_ia = generate_analysis(document)

    try:
        conversa_id_int = int(conversation_id)
    except (TypeError, ValueError):
        conversa_id_int = None

    return REVIEW_STORE.create(
        titulo=document.get("document_title") or "Termo de Referência",
        categoria=(category or categoria_ia),
        preview=preview,
        conteudo=document,
        full_content=full_content,
        analise_resumo=analise,
        fontes=fontes,
        criado_por_id=user_id,
        conversa_id=conversa_id_int,
    )


def apply_correction(tr_id: int, message: str) -> dict | None:
    """
    Chat de correção de um TR: aplica a instrução do usuário ao documento via
    LLM. Se algo mudar, salva uma nova versão e devolve o TR para a fila
    (status 'pending'). Retorna None se o TR não existir.
    """
    from . import document_editor

    document = REVIEW_STORE.get_conteudo(tr_id)
    if document is None:
        return None

    if not document or document.get("type") != "tr":
        return {
            "message": (
                "Este TR não tem conteúdo estruturado para editar. "
                "Gere-o novamente pelo chat antes de corrigir."
            ),
            "changed_sections": [],
            "tr": REVIEW_STORE.get(tr_id, full=True),
        }

    updated, changed = document_editor.apply_edit(message, document)

    if not changed:
        return {
            "message": (
                "Não consegui identificar qual tópico ajustar. Diga o número da "
                'seção — por exemplo: "No tópico 3, detalhe as horas e os perfis técnicos".'
            ),
            "changed_sections": [],
            "tr": REVIEW_STORE.get(tr_id, full=True),
        }

    full_content = document_to_markdown(updated)
    preview = make_preview(full_content)
    tr = REVIEW_STORE.save_correction(
        tr_id, conteudo=updated, full_content=full_content, preview=preview
    )
    return {
        "message": (
            "Atualizei o(s) tópico(s): "
            + ", ".join(str(c) for c in changed)
            + f". Gerei a versão {tr['version']} e o TR voltou para a fila de revisão."
        ),
        "changed_sections": changed,
        "tr": tr,
    }
