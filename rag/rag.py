import requests
from collections import Counter
from pathlib import Path
import json

from .ingest import get_collection, OLLAMA_BASE, ollama_embed
from prompts.prompts import SYSTEM_PROMPT

LLM_MODEL = "mistral"
TEMPLATES_DIR = Path("data/templates")


def ollama_generate(prompt: str) -> str:
    resp = requests.post(
        f"{OLLAMA_BASE}/api/generate",
        json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
        timeout=1000
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def _load_template(source_name: str) -> dict:
    p = TEMPLATES_DIR / f"{source_name}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"source": source_name, "outline": [], "table_columns": [], "style_sample": ""}


def rag_answer(question: str, top_k: int = 6) -> dict:
    col = get_collection()
    q_emb = ollama_embed([question])[0]

    res = col.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    # escolhe o TR base (mais recorrente no top-k)
    sources = [m.get("source") for m in metas if m.get("source")]
    base_source = Counter(sources).most_common(1)[0][0] if sources else ""
    tpl = _load_template(base_source) if base_source else {"outline": [], "table_columns": [], "style_sample": ""}

    outline_txt = "\n".join(tpl.get("outline") or [])
    table_cols = tpl.get("table_columns") or []
    table_hint = ""
    if table_cols:
        table_hint = (
            "COLUNAS DE TABELA (seção de itens):\n"
            + " | ".join(table_cols)
            + "\nVocê deve produzir uma tabela Markdown (pipes) com estas colunas.\n"
        )

    context_blocks = []
    for i, (txt, md, dist) in enumerate(zip(docs, metas, dists), start=1):
        context_blocks.append(
            f"[Trecho {i} | fonte={md.get('source')} | chunk={md.get('chunk')} | dist={dist:.4f}]\n{txt}"
        )
    context = "\n\n---\n\n".join(context_blocks)

    prompt = f"""{SYSTEM_PROMPT}

TR BASE ESCOLHIDO: {base_source}

PADRÃO DE SEÇÕES (use exatamente estes títulos/numeração quando existirem):
{outline_txt if outline_txt else "(não encontrado; use um TR padrão com seções numeradas)"}

{table_hint}

AMOSTRA DE ESTILO DO TR BASE (apenas para imitar a escrita, não copie literalmente):
{(tpl.get("style_sample") or "")}

CONTEXTO (trechos oficiais recuperados):
{context}

PEDIDO:
{question}

Agora redija um TERMO DE REFERÊNCIA completo, seguindo o padrão acima.
"""

    answer = ollama_generate(prompt)

    return {
        "answer": answer,
        "base_source": base_source,
        "sources": [
            {"source": m.get("source"), "chunk": m.get("chunk"), "distance": float(d)}
            for m, d in zip(metas, dists)
        ]
    }