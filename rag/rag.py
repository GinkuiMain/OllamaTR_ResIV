import requests
from .ingest import get_collection, OLLAMA_BASE, ollama_embed
from prompts.prompts import SYSTEM_PROMPT



LLM_MODEL = "mistral"  # // Baixem tbm
SYSTEM_PROMPT = SYSTEM_PROMPT


def ollama_generate(prompt: str) -> str:
    resp = requests.post(
        f"{OLLAMA_BASE}/api/generate",
        json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
        timeout=120
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


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

    context_blocks = []
    for i, (txt, md, dist) in enumerate(zip(docs, metas, dists), start=1):
        context_blocks.append(
            f"[Trecho {i} | fonte={md.get('source')} | chunk={md.get('chunk')} | dist={dist:.4f}]\n{txt}"
        )

    context = "\n\n---\n\n".join(context_blocks)

    prompt = f"""{SYSTEM_PROMPT}
    
        CONTEXTO (trechos do termo de referência):
        {context}
        
        PEDIDO DO USUÁRIO:
        {question}
        
        Gere a resposta em formato de documento, com seções (Objetivo, Escopo, Requisitos, Prazo, Garantia/Suporte, Critérios de Aceite, Obrigações, Penalidades, Anexos).
        """

    answer = ollama_generate(prompt)

    return {
        "answer": answer,
        "sources": [
            {"source": m.get("source"), "chunk": m.get("chunk"), "distance": float(d)}
            for m, d in zip(metas, dists)
        ]
    }
