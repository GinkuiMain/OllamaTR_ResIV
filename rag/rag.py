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

import re
import json
import requests
from collections import Counter
from pathlib import Path

from .ingest import get_collection, OLLAMA_BASE, ollama_embed
from .template_profiles import TEMPLATE_PROFILES, choose_profile
from .intent import classify_intent
from prompts.prompts import build_prompt, _col_to_key
from prompts.prompts import build_conversational_prompt, build_document_query_prompt
from rag.templates_renderer import render_tr_html

import docx as _docx

LLM_MODEL = "mistral"
DOCS_DIR = Path("data/docs")


# ---------------------------------------------------------------------------
# Geração via Ollama (texto livre)
# ---------------------------------------------------------------------------
def ollama_generate(prompt: str) -> str:
    resp = requests.post(
        f"{OLLAMA_BASE}/api/generate",
        json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
        timeout=1000,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


# ---------------------------------------------------------------------------
# Extração de colunas reais do DOCX
# ---------------------------------------------------------------------------
def _extract_table_columns_from_docx(source_name: str) -> list:
    """
    Abre o DOCX pelo nome e retorna as colunas da primeira tabela com
    'ITEM' e 'DESCRIÇÃO' no cabeçalho. Retorna [] se não encontrar.
    """
    doc_path = DOCS_DIR / source_name
    if not doc_path.exists():
        return []
    try:
        doc = _docx.Document(str(doc_path))
        for table in doc.tables:
            if not table.rows:
                continue
            header = [c.text.strip().upper() for c in table.rows[0].cells]
            if "ITEM" in header and any("DESCRI" in h for h in header):
                seen, cols = set(), []
                for h in header:
                    if h and h not in seen:
                        seen.add(h)
                        cols.append(table.rows[0].cells[header.index(h)].text.strip())
                return cols
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Parse do JSON devolvido pelo LLM
# ---------------------------------------------------------------------------
def _parse_llm_json(raw: str) -> dict:
    """
    Remove cercas de markdown e parseia o JSON.
    Tenta encontrar o bloco { } raiz se o parse direto falhar.
    """
    clean = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", clean, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


# ---------------------------------------------------------------------------
# Montagem das seções para o template HTML
# ---------------------------------------------------------------------------
def _assemble_sections(llm_data: dict, profile_name: str, table_columns: list) -> list:
    """
    Transforma o dict JSON do LLM na lista de seções que tr_fsph.html espera.
    """
    profile = TEMPLATE_PROFILES.get(profile_name, TEMPLATE_PROFILES["servico_padrao"])
    col_keys = {col: _col_to_key(col) for col in table_columns}

    sections = []
    for sec in profile["sections"]:
        sid = sec["id"]
        kind = sec["kind"]

        if kind == "opening_with_table":
            paragraphs = llm_data.get("opening_paragraphs", ["A definir"])
            raw_rows = llm_data.get("table_rows", [])
            table_rows = []
            for raw_row in raw_rows:
                row = {}
                for col, key in col_keys.items():
                    row[col] = raw_row.get(key, raw_row.get(col, "A definir"))
                table_rows.append(row)

            sections.append({
                "id": sid,
                "title": sec["title"],
                "kind": kind,
                "paragraphs": paragraphs,
                "table_columns": table_columns,
                "table_rows": table_rows,
            })
        else:
            key = f"section_{sid}_paragraphs"
            paragraphs = llm_data.get(key, ["A definir"])
            sections.append({
                "id": sid,
                "title": sec["title"],
                "kind": kind,
                "paragraphs": paragraphs,
            })

    return sections


# ---------------------------------------------------------------------------
# Handlers por intenção
# ---------------------------------------------------------------------------
def _handle_conversational(question: str) -> dict:
    """Resposta amigável sem RAG nem geração de TR."""
    prompt = build_conversational_prompt(question)
    message = ollama_generate(prompt)
    return {
        "type": "conversational",
        "message": message,
    }


def _handle_document_query(question: str, top_k: int) -> dict:
    """Dúvida técnica: faz RAG mas responde em texto livre, não gera TR."""
    col = get_collection()
    q_emb = ollama_embed([question])[0]
    res = col.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    docs  = res["documents"][0]
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
            {"source": m.get("source"), "chunk": m.get("chunk"), "distance": float(d)}
            for m, d in zip(metas, dists)
        ],
    }


def _handle_tr_request(question: str, top_k: int) -> dict:
    """Pipeline completo de geração de TR."""
    # Busca semântica
    col = get_collection()
    q_emb = ollama_embed([question])[0]
    res = col.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    docs  = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    # Vota no TR base mais recorrente
    sources = [m.get("source") for m in metas if m.get("source")]
    base_source = Counter(sources).most_common(1)[0][0] if sources else ""

    # Perfil HTML e colunas reais
    profile_name = choose_profile(base_source)
    table_columns = _extract_table_columns_from_docx(base_source)

    # Contexto
    context_blocks = [
        f"[Trecho {i} | fonte={md.get('source')} | chunk={md.get('chunk')} | dist={dist:.4f}]\n{txt}"
        for i, (txt, md, dist) in enumerate(zip(docs, metas, dists), start=1)
    ]
    context = "\n\n---\n\n".join(context_blocks)

    # Prompt → LLM → parse → seções → HTML
    prompt = build_prompt(
        profile_name=profile_name,
        table_columns=table_columns,
        base_source=base_source,
        context=context,
        question=question,
    )
    raw_answer = ollama_generate(prompt)
    llm_data = _parse_llm_json(raw_answer)
    sections = _assemble_sections(llm_data, profile_name, table_columns)

    html = render_tr_html({
        "document_title": "TERMO DE REFERÊNCIA",
        "sections": sections,
        "footer_text": (
            "Fundação de Saúde Parreiras Horta – FSPH | "
            "Documento gerado automaticamente para revisão técnica e jurídica."
        ),
    })

    return {
        "type": "tr",
        "html": html,
        "profile": profile_name,
        "base_source": base_source,
        "table_columns": table_columns,
        "llm_raw": raw_answer,
        "sources": [
            {"source": m.get("source"), "chunk": m.get("chunk"), "distance": float(d)}
            for m, d in zip(metas, dists)
        ],
    }


# ---------------------------------------------------------------------------
# Ponto de entrada único
# ---------------------------------------------------------------------------
def rag_answer(question: str, top_k: int = 6) -> dict:
    """
    Classifica a intenção e roteia para o handler correto.
    Sempre retorna um dict com o campo 'type' indicando o que foi gerado.
    """
    intent = classify_intent(question)

    if intent == "conversational":
        return _handle_conversational(question)

    if intent == "document_query":
        return _handle_document_query(question, top_k)

    # tr_request (default)
    return _handle_tr_request(question, top_k)
