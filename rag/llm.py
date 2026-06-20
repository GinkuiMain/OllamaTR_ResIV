"""
rag/llm.py
Funções utilitárias de acesso ao LLM (Ollama) e parsing de JSON.

Extraído de rag.py para que tanto rag.py quanto document_editor.py possam
reutilizar as mesmas funções sem criar import circular
(rag.py -> document_editor.py -> rag.py).
"""
import re
import json
import requests

from .ingest import OLLAMA_BASE

LLM_MODEL = "qwen2.5:3b" # MUDAR PARA O OUTRO MODELO -- OLHAR CHAT DO GEMINI


def ollama_generate(prompt: str, model: str = LLM_MODEL) -> str:
    """Chama o endpoint de geração do Ollama e devolve o texto da resposta."""
    resp = requests.post(
        f"{OLLAMA_BASE}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=1000,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def parse_llm_json(raw: str) -> dict:
    """
    Tenta extrair um objeto JSON da resposta do LLM.

    LLMs às vezes embrulham o JSON em ```json ... ``` ou adicionam texto antes/depois.
    Esta função limpa o markdown e, se necessário, recorta o primeiro bloco {...}.
    Retorna {} quando não consegue parsear.
    """
    clean = re.sub(r"```(?:json)?", "", raw).strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, re.DOTALL)

        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}

    return {}
