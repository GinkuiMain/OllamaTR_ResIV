"""
intent.py
Classifica a intenção do usuário ANTES de entrar no pipeline RAG.

Por que isso existe?
  Sem esta etapa, qualquer mensagem — incluindo "Oi, tudo bem?" — entra
  no pipeline de geração de TR, produz JSON vazio e retorna um documento
  em branco. Isso quebra a experiência e confunde o usuário.

Três intenções possíveis:
  - "tr_request"      → usuário quer gerar um Termo de Referência
  - "document_query"  → usuário tem uma dúvida sobre normas, contratos, FSPH
  - "conversational"  → saudação, agradecimento, frase genérica

Estratégia em dois estágios (rápido → preciso):
  1. Heurística de palavras-chave (sem custo de LLM).
     Se o texto contém termos de contratação → tr_request imediato.
     Se o texto é muito curto e informal    → conversational imediato.
  2. Chamada leve ao LLM (apenas se a heurística for inconclusiva).
     Um prompt minúsculo pede ao modelo uma única palavra de resposta.
"""

import re
import requests

# Importado do módulo de ingestão para reutilizar a mesma base URL/modelo
from .ingest import OLLAMA_BASE

# Modelo para classificação — pode ser o mesmo do pipeline ou um menor
INTENT_MODEL = "gemma3:1b"

# ---------------------------------------------------------------------------
# Palavras-chave que sinalizam uma requisição de TR
# ---------------------------------------------------------------------------
_TR_KEYWORDS = [
    "contratar", "contratação", "aquisição", "adquirir", "comprar", "compra",
    "termo de referência", "tr ", " tr,", " tr.", "licitação", "licitação",
    "pregão", "fornecimento", "fornecedor", "insumo", "serviço", "serviços",
    "capacitação", "curso", "brinde", "mobiliário", "móvel", "móveis",
    "equipamento", "material", "materiais", "registro de preços",
    "lei 14.133", "lei nº 14", "objeto da contratação", "objeto:",
    "preciso de", "preciso contratar", "gerar tr", "gere um tr",
    "elaborar", "redigir", "redija", "criar um termo",
]

# Palavras que sinalizam conversa casual
_CASUAL_KEYWORDS = [
    "oi", "olá", "ola", "hey", "tudo bem", "tudo bom", "como vai",
    "bom dia", "boa tarde", "boa noite", "obrigado", "obrigada",
    "valeu", "tchau", "até logo", "até mais", "ok", "certo", "entendi",
]


def _normalize(text: str) -> str:
    """Minúsculas, sem acentos para comparação simples."""
    text = text.lower().strip()
    # Remove acentos básicos para comparação
    for a, b in [("ã", "a"), ("â", "a"), ("á", "a"), ("à", "a"),
                 ("é", "e"), ("ê", "e"), ("í", "i"), ("ó", "o"),
                 ("ô", "o"), ("ú", "u"), ("ç", "c"), ("õ", "o")]:
        text = text.replace(a, b)
    return text


def _heuristic_classify(text: str) -> str | None:
    """
    Classificação por palavras-chave. Retorna a intenção ou None se inconclusivo.
    """
    norm = _normalize(text)
    word_count = len(norm.split())

    # Texto muito curto (≤ 6 palavras) e sem termos de contratação → casual
    has_tr_keyword = any(kw in norm for kw in _TR_KEYWORDS)
    has_casual = any(kw in norm for kw in _CASUAL_KEYWORDS)

    if has_tr_keyword:
        return "tr_request"

    if has_casual and word_count <= 10:
        return "conversational"

    # Texto muito curto sem nenhuma pista → provavelmente casual
    if word_count <= 4 and not has_tr_keyword:
        return "conversational"

    return None  # inconclusivo → vai para o LLM


def _llm_classify(text: str) -> str:
    # Botei o Mistral para averiguar! Mais simples (preguiça)
    prompt = (
        "Classifique a mensagem abaixo em UMA das categorias:\n"
        "- TR_REQUEST: o usuário quer gerar ou elaborar um Termo de Referência "
        "ou descreve algo que precisa ser contratado/adquirido.\n"
        "- DOCUMENT_QUERY: o usuário tem uma dúvida sobre normas, leis, "
        "procedimentos de licitação ou contratos da FSPH.\n"
        "- CONVERSATIONAL: saudação, agradecimento, frase genérica sem "
        "relação com contratações.\n\n"
        "Responda com UMA ÚNICA PALAVRA em maiúsculas. Nada mais.\n\n"
        f"Mensagem: \"{text}\""
    )
    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": INTENT_MODEL, "prompt": prompt, "stream": False},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip().upper()

        if "TR_REQUEST" in raw:
            return "tr_request"
        if "DOCUMENT" in raw:
            return "document_query"
        # Qualquer outro resultado → tratar como conversational (mais seguro)
        return "conversational"

    except Exception:
        # Se o LLM falhar, assume conversational para não gerar TR em branco
        return "conversational"


def classify_intent(text: str) -> str:
    """
    Ponto de entrada principal.
    Retorna: "tr_request" | "document_query" | "conversational"
    """
    result = _heuristic_classify(text)
    if result is not None:
        return result
    return _llm_classify(text)
