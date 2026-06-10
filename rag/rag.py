"""
rag.py
Pipeline completo com classificação de intenção.

Fluxo:
  1. classify_intent() — decide o que o usuário realmente quer
     ├─ "conversational"  → resposta amigável, sem RAG nem TR
     ├─ "document_query"  → RAG + resposta em texto livre
     └─ "tr_request"      → pipeline completo de geração de TR

  Pipeline de TR (apenas para tr_request):
  2. Busca semântica no ChromaDB
  3. Vota no TR base mais recorrente entre os chunks recuperados
  4. choose_profile() mapeia o TR base para um dos 3 perfis HTML
  5. Extrai colunas reais da tabela do DOCX (via python-docx)
  6. build_prompt() monta o prompt com seções e keys corretas para o perfil
  7. LLM devolve JSON
  8. _parse_llm_json() limpa e parseia (LLMs às vezes adicionam ```json)
  9. _assemble_sections() transforma o JSON nas seções que o template HTML espera
 10. render_tr_html() gera o HTML final
"""
import json
from collections import Counter
from pathlib import Path

from .ingest import get_collection, OLLAMA_BASE, ollama_embed
from .intent import classify_intent
from .llm import ollama_generate, parse_llm_json
from .conversation_store import STORE
from . import document_editor
from prompts.prompts import (
    build_prompt,
    _col_to_key,
    build_conversational_prompt,
    build_document_query_prompt,
)
from rag.templates_renderer import render_tr_html

TEMPLATES_DIR = Path("data/templates")

# Alias mantido por compatibilidade com os usos internos deste arquivo.
_parse_llm_json = parse_llm_json


def _load_template(source_name: str) -> dict:
    path = TEMPLATES_DIR / f"{source_name}.json"

    if not path.exists():
        return {
            "source": source_name,
            "document_title": "TERMO DE REFERÊNCIA",
            "sections": [],
            "table_columns": [],
        }

    return json.loads(path.read_text(encoding="utf-8"))


def _choose_base_source(metas: list[dict]) -> str:
    sources = [m.get("source") for m in metas if m.get("source")]

    if not sources:
        return ""

    # O TR de monitoramento pode continuar indexado, mas não deve ser base de formatação
    # quando houver outro TR disponível no resultado.
    non_monitor_sources = [
        s for s in sources
        if "monitor" not in s.lower()
    ]

    chosen_pool = non_monitor_sources or sources

    return Counter(chosen_pool).most_common(1)[0][0]


def _normalize_template_sections(template: dict) -> list[dict]:
    sections = template.get("sections") or []

    normalized = []

    for idx, section in enumerate(sections, start=1):
        normalized.append({
            "id": str(section.get("id") or idx),
            "title": section.get("title") or f"SEÇÃO {idx}",
            "table_columns": section.get("table_columns") or [],
        })

    return normalized


def _get_main_table_columns(template: dict) -> list[str]:
    for section in template.get("sections", []):
        columns = section.get("table_columns") or []

        if columns:
            return columns

    return template.get("table_columns") or []


def _build_error_response(message: str) -> dict:
    html = f"""
    <html lang="pt-BR">
      <head>
        <meta charset="utf-8">
        <title>Assistente FSPH</title>
      </head>
      <body style="font-family: Arial, sans-serif; margin: 40px;">
        <h2>Não foi possível gerar o Termo de Referência</h2>
        <p>{message}</p>
      </body>
    </html>
    """

    return {
        "type": "error",
        "message": message,
        "html": html,
        "sources": [],
    }


def _assemble_sections(
    *,
    template_sections: list[dict],
    llm_data: dict,
    table_columns: list[str],
) -> list[dict]:
    llm_sections = llm_data.get("sections") or {}
    raw_table_rows = llm_data.get("table_rows") or []

    assembled = []

    for section in template_sections:
        section_id = str(section["id"])
        content = llm_sections.get(section_id) or ["A definir"]

        if isinstance(content, str):
            content = [content]

        clean_content = [
            str(item).strip()
            for item in content
            if str(item).strip()
        ]

        if not clean_content:
            clean_content = ["A definir"]

        rendered_section = {
            "id": section_id,
            "title": section["title"],
            "content": clean_content,
            "table_columns": [],
            "table_rows": [],
        }

        section_has_table = bool(section.get("table_columns"))

        if section_has_table:
            rendered_section["table_columns"] = table_columns

            col_map = {
                col: _col_to_key(col)
                for col in table_columns
            }

            rows = []

            for raw_row in raw_table_rows:
                row = {}

                for col, key in col_map.items():
                    row[col] = (
                        raw_row.get(key)
                        or raw_row.get(col)
                        or "A definir"
                    )

                rows.append(row)

            if not rows and table_columns:
                rows.append({
                    col: "A definir"
                    for col in table_columns
                })

            rendered_section["table_rows"] = rows

        assembled.append(rendered_section)

    return assembled


def _handle_conversational(question: str) -> dict:
    prompt = build_conversational_prompt(question)
    message = ollama_generate(prompt)

    return {
        "type": "conversational",
        "message": message,
    }


def _handle_document_query(question: str, top_k: int) -> dict:
    collection = get_collection()

    q_emb = ollama_embed([question])[0]

    res = collection.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    context_blocks = [
        f"[Trecho {i} | fonte={md.get('source')}]\n{txt}"
        for i, (txt, md) in enumerate(zip(docs, metas), start=1)
    ]

    context = "\n\n---\n\n".join(context_blocks)

    prompt = build_document_query_prompt(question, context)
    message = ollama_generate(prompt)

    return {
        "type": "document_query",
        "message": message,
        "sources": [
            {
                "source": m.get("source"),
                "chunk": m.get("chunk"),
                "distance": float(d),
            }
            for m, d in zip(metas, dists)
        ],
    }


def _handle_tr_request(question: str, top_k: int) -> dict:
    collection = get_collection()

    q_emb = ollama_embed([question])[0]

    res = collection.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    base_source = _choose_base_source(metas)
    template = _load_template(base_source)

    template_sections = _normalize_template_sections(template)

    if not template_sections:
        return _build_error_response(
            "O TR base foi encontrado, mas a estrutura do documento ainda não foi extraída. "
            "Reindexe os documentos em /admin/index?reset=true."
        )

    table_columns = _get_main_table_columns(template)

    context_blocks = [
        f"[Trecho {i} | fonte={md.get('source')} | chunk={md.get('chunk')} | dist={dist:.4f}]\n{txt}"
        for i, (txt, md, dist) in enumerate(zip(docs, metas, dists), start=1)
    ]

    context = "\n\n---\n\n".join(context_blocks)

    prompt = build_prompt(
        base_source=base_source,
        sections=template_sections,
        table_columns=table_columns,
        context=context,
        question=question,
    )

    raw_answer = ollama_generate(prompt)
    llm_data = _parse_llm_json(raw_answer)

    if not llm_data:
        return _build_error_response(
            "O modelo não retornou JSON válido. Tente detalhar melhor o objeto da contratação."
        )

    sections = _assemble_sections(
        template_sections=template_sections,
        llm_data=llm_data,
        table_columns=table_columns,
    )

    document_title = template.get("document_title") or "TERMO DE REFERÊNCIA"
    footer_text = (
        "Fundação de Saúde Parreiras Horta – FSPH | "
        "Documento gerado automaticamente para revisão técnica e jurídica."
    )

    html = render_tr_html({
        "document_title": document_title,
        "sections": sections,
        "footer_text": footer_text,
    })

    sources = [
        {
            "source": m.get("source"),
            "chunk": m.get("chunk"),
            "distance": float(d),
        }
        for m, d in zip(metas, dists)
    ]

    return {
        "type": "tr",
        "html": html,
        "document_title": document_title,
        "sections": sections,
        "footer_text": footer_text,
        "base_source": base_source,
        "table_columns": table_columns,
        "llm_raw": raw_answer,
        "sources": sources,
    }


def _document_state_from_result(result: dict) -> dict:
    """Extrai do resultado de _handle_tr_request o que precisa ficar guardado na conversa."""
    return {
        "type": "tr",
        "document_title": result.get("document_title"),
        "sections": result.get("sections", []),
        "base_source": result.get("base_source"),
        "table_columns": result.get("table_columns", []),
        "footer_text": result.get("footer_text", ""),
        "sources": result.get("sources", []),
        "html": result.get("html", ""),
    }


def _no_active_tr_message() -> dict:
    return {
        "type": "conversational",
        "message": (
            "Ainda não há um Termo de Referência nesta conversa. "
            "Descreva primeiro a contratação para eu gerar o TR e, depois, "
            "podemos editá-lo tópico a tópico."
        ),
    }


def _handle_tr_edit(question: str, conversation_id: str) -> dict:
    document = STORE.get_current_document(conversation_id)

    if not document or document.get("type") != "tr":
        return _no_active_tr_message()

    updated, changed = document_editor.apply_edit(question, document)

    if not changed:
        return {
            "type": "tr_update",
            "message": (
                "Não consegui identificar qual tópico você quer alterar. "
                'Diga o número da seção — por exemplo: "No tópico 7, troque o fiscal".'
            ),
            "html": updated.get("html", ""),
            "changed_sections": [],
            "base_source": updated.get("base_source"),
            "sections": updated.get("sections", []),
        }

    STORE.set_current_document(conversation_id, updated)

    return {
        "type": "tr_update",
        "html": updated.get("html", ""),
        "changed_sections": changed,
        "document_title": updated.get("document_title"),
        "base_source": updated.get("base_source"),
        "table_columns": updated.get("table_columns", []),
        "sections": updated.get("sections", []),
        "sources": updated.get("sources", []),
    }


def _handle_tr_explain(question: str, conversation_id: str) -> dict:
    document = STORE.get_current_document(conversation_id)

    if not document or document.get("type") != "tr":
        return _no_active_tr_message()

    message, section_id = document_editor.explain_section(question, document)

    return {
        "type": "tr_explain",
        "message": message,
        "section_id": section_id,
        "base_source": document.get("base_source"),
    }


def rag_answer(question: str, top_k: int = 6, conversation_id: str | None = None) -> dict:
    """
    Ponto de entrada do pipeline.

    Quando `conversation_id` é fornecido (ou criado aqui), o estado da conversa
    é mantido: o último TR gerado fica guardado e mensagens seguintes podem
    editá-lo ou pedir explicações sem reenviar todo o contexto.

    O `conversation_id` usado sempre volta no campo de mesmo nome do resultado.
    """
    conversation_id = STORE.ensure(conversation_id)
    STORE.append_message(conversation_id, "user", question)

    has_active_tr = STORE.has_active_tr(conversation_id)
    intent = classify_intent(question, has_active_tr=has_active_tr)

    if intent == "tr_edit_request":
        result = _handle_tr_edit(question, conversation_id)

    elif intent == "tr_explain_request":
        result = _handle_tr_explain(question, conversation_id)

    elif intent == "conversational":
        result = _handle_conversational(question)

    elif intent == "document_query":
        result = _handle_document_query(question, top_k)

    else:  # tr_request → gera um TR novo e o guarda na conversa
        result = _handle_tr_request(question, top_k)
        if result.get("type") == "tr":
            STORE.set_current_document(conversation_id, _document_state_from_result(result))

    result["conversation_id"] = conversation_id
    result["intent"] = intent
    STORE.append_message(conversation_id, "assistant", result.get("type", ""))

    return result