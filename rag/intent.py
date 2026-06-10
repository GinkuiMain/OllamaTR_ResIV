"""
intent.py
Classifica a intenção do usuário ANTES de entrar no pipeline RAG.

Por que isso existe?
  Sem esta etapa, qualquer mensagem — incluindo "Oi, tudo bem?" — entra
  no pipeline de geração de TR, produz JSON vazio e retorna um documento
  em branco. Isso quebra a experiência e confunde o usuário.

Três intenções base:
  - "tr_request"      → usuário quer gerar um Termo de Referência
  - "document_query"  → usuário tem uma dúvida sobre normas, contratos, FSPH
  - "conversational"  → saudação, agradecimento, frase genérica

Duas intenções extras, válidas só quando já existe um TR ativo na conversa:
  - "tr_edit_request"    → alterar uma seção do TR já gerado
  - "tr_explain_request" → explicar um tópico do TR já gerado

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

# ---------------------------------------------------------------------------
# Intenções que SÓ fazem sentido quando já existe um TR ativo na conversa
# (todas as listas abaixo já estão sem acento, pois o texto é normalizado).
# ---------------------------------------------------------------------------

# Verbos típicos de edição de um documento existente
_EDIT_KEYWORDS = [
    "troque", "trocar", "altere", "alterar", "mude", "mudar",
    "substitua", "substituir", "acrescente", "acrescentar",
    "adicione", "adicionar", "inclua", "incluir", "remova", "remover",
    "retire", "retirar", "exclua", "excluir", "apague", "apagar",
    "corrija", "corrigir", "ajuste", "ajustar", "atualize", "atualizar",
    "modifique", "modificar", "revise", "revisar", "reescreva", "reescrever",
    "coloque", "ponha", "deixe", "preencha", "preencher",
]

# Palavras que referenciam uma seção/tópico do documento
_SECTION_REF_KEYWORDS = [
    "topico", "secao", "item", "clausula", "paragrafo",
    "ponto", "capitulo",
]

# Verbos/expressões típicos de pedido de explicação
_EXPLAIN_KEYWORDS = [
    "explique", "explica", "explicar", "detalhe", "detalhar",
    "o que significa", "o que quer dizer", "por que", "porque",
    "esclareca", "esclarecer", "me explique", "interprete", "interpretar",
]

# Expressões que indicam pedido de um TR NOVO (mesmo já havendo um ativo)
_NEW_TR_KEYWORDS = [
    "gere um tr", "gerar um tr", "elabore um tr", "elaborar um tr",
    "faca um tr", "novo tr", "outro tr", "gere um termo", "elabore um termo",
    "criar um termo", "crie um termo", "gerar um termo", "elaborar um termo",
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


def _heuristic_classify(text: str, has_active_tr: bool = False) -> str | None:
    """
    Classificação por palavras-chave. Retorna a intenção ou None se inconclusivo.

    Quando `has_active_tr` é True, as intenções de edição/explicação ganham
    prioridade — mas um pedido explícito de TR novo ("gere um TR para...")
    ainda é tratado como tr_request.
    """
    norm = _normalize(text)
    word_count = len(norm.split())

    has_tr_keyword = any(kw in norm for kw in _TR_KEYWORDS)
    has_casual = any(kw in norm for kw in _CASUAL_KEYWORDS)
    has_new_tr = any(kw in norm for kw in _NEW_TR_KEYWORDS)
    has_edit = any(kw in norm for kw in _EDIT_KEYWORDS)
    has_explain = any(kw in norm for kw in _EXPLAIN_KEYWORDS)
    has_section_ref = any(kw in norm for kw in _SECTION_REF_KEYWORDS)
    has_number = bool(re.search(r"\b\d+\b", norm))

    # --- intenções dependentes de contexto (só com um TR já gerado) ---
    if has_active_tr and not has_new_tr:
        # "Explique o tópico 4" / "o que significa a seção 3"
        if has_explain and (has_section_ref or has_number):
            return "tr_explain_request"
        # "No tópico 7, troque o fiscal" / "coloque prazo de 30 dias"
        if has_edit:
            return "tr_edit_request"
        # "no tópico 5, ..." (referência a seção + número, sem verbo explícito)
        if has_section_ref and has_number:
            return "tr_edit_request"

    # --- pedido explícito de TR novo ---
    if has_new_tr:
        return "tr_request"

    # --- heurísticas originais ---
    if has_tr_keyword:
        return "tr_request"

    if has_casual and word_count <= 10:
        return "conversational"

    # Texto muito curto sem nenhuma pista → provavelmente casual
    if word_count <= 4 and not has_tr_keyword:
        return "conversational"

    return None  # inconclusivo → vai para o LLM


def _llm_classify(text: str, has_active_tr: bool = False) -> str:
    # Botei o Mistral para averiguar! Mais simples (preguiça)
    extra = ""
    if has_active_tr:
        extra = (
            "- TR_EDIT: o usuário quer alterar/editar uma seção do TR que já foi "
            "gerado nesta conversa (ex.: trocar, acrescentar, ajustar um tópico).\n"
            "- TR_EXPLAIN: o usuário quer que você explique um tópico do TR atual.\n"
        )

    prompt = (
        "Classifique a mensagem abaixo em UMA das categorias:\n"
        "- TR_REQUEST: o usuário quer gerar ou elaborar um Termo de Referência "
        "ou descreve algo que precisa ser contratado/adquirido.\n"
        "- DOCUMENT_QUERY: o usuário tem uma dúvida sobre normas, leis, "
        "procedimentos de licitação ou contratos da FSPH.\n"
        f"{extra}"
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

        if has_active_tr and "TR_EDIT" in raw:
            return "tr_edit_request"
        if has_active_tr and "TR_EXPLAIN" in raw:
            return "tr_explain_request"
        if "TR_REQUEST" in raw:
            return "tr_request"
        if "DOCUMENT" in raw:
            return "document_query"
        # Qualquer outro resultado → tratar como conversational (mais seguro)
        return "conversational"

    except Exception:
        # Se o LLM falhar, assume conversational para não gerar TR em branco
        return "conversational"


def classify_intent(text: str, has_active_tr: bool = False) -> str:
    """
    Ponto de entrada principal.

    Args:
        text: mensagem do usuário.
        has_active_tr: True se a conversa já tem um TR gerado (habilita as
            intenções tr_edit_request e tr_explain_request).

    Retorna:
        "tr_request" | "document_query" | "conversational"
        | "tr_edit_request" | "tr_explain_request"
    """
    result = _heuristic_classify(text, has_active_tr=has_active_tr)
    if result is not None:
        return result
    return _llm_classify(text, has_active_tr=has_active_tr)
