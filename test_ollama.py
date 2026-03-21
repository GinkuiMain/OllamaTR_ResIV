#!/usr/bin/env python
"""Script de diagnóstico para verificar a conexão e modelos disponíveis no Ollama."""

import requests
import json
import sys

OLLAMA_BASE = "http://localhost:11434"

def test_connection():
    """Testa se o Ollama está disponível."""
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        resp.raise_for_status()
        return True, "Conectado ao Ollama com sucesso"
    except requests.exceptions.ConnectionError:
        return False, f"Erro: Não conseguiu conectar ao Ollama em {OLLAMA_BASE}"
    except requests.exceptions.Timeout:
        return False, f"Erro: Timeout ao conectar com Ollama"
    except Exception as e:
        return False, f"Erro: {str(e)}"


def get_models():
    """Lista os modelos disponíveis no Ollama."""
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return data.get("models", [])
    except Exception as e:
        return None


def test_embed_model(model_name="nomic-embed-text"):
    """Testa se o modelo de embedding está disponível."""
    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/api/embed",
            json={"model": model_name, "input": ["teste"]},
            timeout=10
        )
        if resp.status_code == 404:
            return False, f"Modelo '{model_name}' não encontrado (404)"
        resp.raise_for_status()
        return True, f"Modelo '{model_name}' OK"
    except requests.exceptions.Timeout:
        return False, f"Timeout ao testar '{model_name}'"
    except Exception as e:
        return False, f"Erro ao testar '{model_name}': {str(e)}"


def test_llm_model(model_name="mistral"):
    """Testa se o modelo LLM está disponível."""
    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": model_name, "prompt": "oi", "stream": False},
            timeout=10
        )
        if resp.status_code == 404:
            return False, f"Modelo '{model_name}' não encontrado (404)"
        resp.raise_for_status()
        return True, f"Modelo '{model_name}' OK"
    except requests.exceptions.Timeout:
        return False, f"Timeout ao testar '{model_name}'"
    except Exception as e:
        return False, f"Erro ao testar '{model_name}': {str(e)}"


def main():
    print("=" * 60)
    print("  Diagnóstico do Ollama")
    print("=" * 60)
    print()

    # 1. Teste de conexão
    print("[1] Testando conexão com Ollama...")
    ok, msg = test_connection()
    status = "✓" if ok else "✗"
    print(f"    {status} {msg}")
    print()

    if not ok:
        print("ERRO: Ollama não está disponível!")
        print("Inicie o Ollama com: ollama serve")
        sys.exit(1)

    # 2. Lista modelos
    print("[2] Modelos disponíveis no Ollama:")
    models = get_models()
    if models:
        for model in models:
            print(f"    - {model.get('name', 'desconhecido')}")
    else:
        print("    Nenhum modelo encontrado!")
    print()

    # 3. Teste de embedding
    print("[3] Testando modelo de embedding (nomic-embed-text)...")
    ok, msg = test_embed_model("nomic-embed-text")
    status = "✓" if ok else "✗"
    print(f"    {status} {msg}")
    if not ok:
        print("    → Baixe com: ollama pull nomic-embed-text")
    print()

    # 4. Teste de LLM
    print("[4] Testando modelo LLM (mistral)...")
    ok, msg = test_llm_model("mistral")
    status = "✓" if ok else "✗"
    print(f"    {status} {msg}")
    if not ok:
        print("    → Baixe com: ollama pull mistral")
    print()

    print("=" * 60)


if __name__ == "__main__":
    main()
