"""
rag.py
Pipeline completo: busca semântica → escolha de perfil → prompt dinâmico
→ geração pelo LLM → parse do JSON → montagem da estrutura de seções
→ renderização HTML via Jinja2.

Fluxo:
  1. Embedda a pergunta e busca top-k chunks no ChromaDB
  2. Vota no TR base mais recorrente entre os resultados
  3. choose_profile() mapeia o TR base para um dos 3 perfis HTML
  4. Extrai colunas reais da tabela do DOCX (via python-docx)
  5. build_prompt() monta o prompt com seções e keys corretas para o perfil
  6. LLM devolve JSON
  7. _parse_llm_json() tenta limpar e parsear (LLMs às vezes adicionam ```json)
  8. _assemble_sections() transforma o JSON nas seções que o template HTML espera
  9. render_tr_html() gera o HTML final
"""

import re
import json
import requests
from collections import Counter
from pathlib import Path

from .ingest import get_collection, OLLAMA_BASE, ollama_embed
from .template_profiles import TEMPLATE_PROFILES, choose_profile
from prompts.prompts import build_prompt, _col_to_key
from rag.templates_renderer import render_tr_html

import docx as _docx

LLM_MODEL = "mistral"
TEMPLATES_DIR = Path("data/templates")
DOCS_DIR = Path("data/docs")


# ---------------------------------------------------------------------------
# Geração via Ollama
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
# Extração de colunas reais do DOCX (substitui a heurística de texto plano)
# ---------------------------------------------------------------------------
def _extract_table_columns_from_docx(source_name: str) -> list:
    """
    Abre o DOCX pelo nome e retorna as colunas da primeira tabela com
    pelo menos as células 'ITEM' e 'DESCRIÇÃO' no cabeçalho.
    Retorna [] se não encontrar.
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
                # Desduplicar (python-docx repete células de células mescladas)
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
    LLMs às vezes envolvem o JSON em ```json ... ```.
    Tenta extrair e parsear; em último caso devolve dict vazio.
    """
    # Remove cercas de markdown
    clean = re.sub(r"```(?:json)?", "", raw).strip()
    # Tenta parsear direto
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Tenta encontrar o primeiro { ... } de nível raiz
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

    Cada seção tem:
      id, title, kind, paragraphs
    A seção 1 (opening_with_table) também tem:
      table_columns, table_rows
    """
    profile = TEMPLATE_PROFILES.get(profile_name, TEMPLATE_PROFILES["servico_padrao"])
    col_keys = {col: _col_to_key(col) for col in table_columns}

    sections = []
    for sec in profile["sections"]:
        sid = sec["id"]
        kind = sec["kind"]

        if kind == "opening_with_table":
            # Parágrafos de abertura (1.1, 1.2, 1.3 ...)
            paragraphs = llm_data.get("opening_paragraphs", ["A definir"])

            # Linhas da tabela: o LLM retorna keys seguras (sem espaços)
            # O template HTML itera table_columns e faz row.get(col)
            # → precisamos converter as keys de volta para o nome original da coluna
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
# Endpoint principal
# ---------------------------------------------------------------------------
def rag_answer(question: str, top_k: int = 6) -> dict:
    # 1. Busca semântica
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

    # 2. Vota no TR base mais recorrente
    sources = [m.get("source") for m in metas if m.get("source")]
    base_source = Counter(sources).most_common(1)[0][0] if sources else ""

    # 3. Escolhe o perfil HTML
    profile_name = choose_profile(base_source)

    # 4. Colunas reais da tabela (via python-docx, não heurística de texto)
    table_columns = _extract_table_columns_from_docx(base_source)

    # 5. Monta contexto
    context_blocks = []
    for i, (txt, md, dist) in enumerate(zip(docs, metas, dists), start=1):
        context_blocks.append(
            f"[Trecho {i} | fonte={md.get('source')} | chunk={md.get('chunk')} | dist={dist:.4f}]\n{txt}"
        )
    context = "\n\n---\n\n".join(context_blocks)

    # 6. Monta prompt dinâmico
    prompt = build_prompt(
        profile_name=profile_name,
        table_columns=table_columns,
        base_source=base_source,
        context=context,
        question=question,
    )

    # 7. Chama o LLM
    raw_answer = ollama_generate(prompt)

    # 8. Parse do JSON
    llm_data = _parse_llm_json(raw_answer)

    # 9. Monta seções
    sections = _assemble_sections(llm_data, profile_name, table_columns)

    # 10. Renderiza HTML
    html = render_tr_html({
        "document_title": "TERMO DE REFERÊNCIA",
        "sections": sections,
        "footer_text": (
            "Fundação de Saúde Parreiras Horta – FSPH | "
            "Documento gerado automaticamente para revisão técnica e jurídica."
        ),
    })

    return {
        "html": html,
        "profile": profile_name,
        "base_source": base_source,
        "table_columns": table_columns,
        "llm_raw": raw_answer,          # útil para debug; remova em produção
        "sources": [
            {
                "source": m.get("source"),
                "chunk": m.get("chunk"),
                "distance": float(d),
            }
            for m, d in zip(metas, dists)
        ],
    }