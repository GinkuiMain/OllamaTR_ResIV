"""
rag/document_editor.py
Edição incremental de um TR já gerado.

Em vez de regenerar o documento inteiro a cada pedido, este módulo:
  1. localiza a seção alvo citada pelo usuário (ex.: "no tópico 7");
  2. pede ao LLM APENAS o novo conteúdo daquela seção;
  3. substitui o conteúdo (e, se houver, a tabela) só daquela seção;
  4. re-renderiza o HTML, mantendo o resto do documento intacto.

Trabalha sobre a estrutura `sections` que rag.py monta na geração inicial:
  [
    {
      "id": "7",
      "title": "...",
      "content": ["parágrafo 1", "parágrafo 2"],
      "table_columns": ["ITEM", "DESCRIÇÃO", ...],   # vazio se a seção não tem tabela
      "table_rows": [{"ITEM": "1", "DESCRIÇÃO": "..."}]
    },
    ...
  ]
"""
import re
import copy
from typing import Optional

from .llm import ollama_generate, parse_llm_json
from .templates_renderer import render_tr_html
from prompts.prompts import (
    _col_to_key,
    build_edit_section_prompt,
    build_explain_section_prompt,
)

# Ordinais por extenso -> número da seção (texto já normalizado, sem acento)
_NUM_WORDS = {
    "primeiro": "1", "primeira": "1",
    "segundo": "2", "segunda": "2",
    "terceiro": "3", "terceira": "3",
    "quarto": "4", "quarta": "4",
    "quinto": "5", "quinta": "5",
    "sexto": "6", "sexta": "6",
    "setimo": "7", "setima": "7",
    "oitavo": "8", "oitava": "8",
    "nono": "9", "nona": "9",
    "decimo": "10", "decima": "10",
}

# Palavras que costumam introduzir a referência a uma seção
_SECTION_WORDS = r"(?:topico|secao|item|clausula|paragrafo|ponto|capitulo|n[º°o]?\.?|numero)"


def _normalize(text: str) -> str:
    """Minúsculas e sem acentos, para casamento simples de termos."""
    text = (text or "").lower().strip()
    for a, b in [("ã", "a"), ("â", "a"), ("á", "a"), ("à", "a"),
                 ("é", "e"), ("ê", "e"), ("í", "i"), ("ó", "o"),
                 ("ô", "o"), ("ú", "u"), ("ç", "c"), ("õ", "o")]:
        text = text.replace(a, b)
    return text


def find_target_section_id(question: str, sections: list[dict]) -> Optional[str]:
    """
    Tenta descobrir a qual seção o usuário se refere.
    Retorna o id da seção (string) ou None se não conseguir identificar.
    """
    if not sections:
        return None

    norm = _normalize(question)
    ids = {str(s.get("id")) for s in sections}

    # 1) número logo após uma palavra de referência ("tópico 7", "seção 5", "item 3")
    m = re.search(rf"{_SECTION_WORDS}\s*0*(\d+)", norm)
    if m and m.group(1) in ids:
        return m.group(1)

    # 2) qualquer número solto que case com um id de seção existente
    for num in re.findall(r"\b0*(\d+)\b", norm):
        if num in ids:
            return num

    # 3) ordinal por extenso ("no quinto tópico")
    for word, num in _NUM_WORDS.items():
        if re.search(rf"\b{word}\b", norm) and num in ids:
            return num

    # 4) casamento por palavras do título (fallback)
    q_words = {w for w in re.findall(r"[a-z0-9]+", norm) if len(w) >= 4}
    best_id = None
    best_score = 0
    for s in sections:
        title_words = {w for w in re.findall(r"[a-z0-9]+", _normalize(s.get("title", ""))) if len(w) >= 4}
        score = len(title_words & q_words)
        if score > best_score:
            best_score = score
            best_id = str(s.get("id"))
    if best_score >= 2:
        return best_id

    return None


def _rerender(document: dict) -> str:
    return render_tr_html({
        "document_title": document.get("document_title") or "TERMO DE REFERÊNCIA",
        "sections": document.get("sections", []),
        "footer_text": document.get("footer_text", ""),
    })


def apply_edit(question: str, document: dict) -> tuple[dict, list[str]]:
    """
    Aplica a alteração pedida a uma única seção do TR.

    Retorna (documento_atualizado, [ids_alterados]).
    Se não identificar a seção ou o LLM não devolver JSON utilizável,
    retorna o documento sem mudanças e lista vazia.
    """
    document = copy.deepcopy(document)
    sections = document.get("sections", [])

    target_id = find_target_section_id(question, sections)
    if target_id is None:
        return document, []

    target = next((s for s in sections if str(s.get("id")) == target_id), None)
    if target is None:
        return document, []

    table_columns = target.get("table_columns") or []

    prompt = build_edit_section_prompt(
        section=target,
        change_request=question,
        table_columns=table_columns,
    )
    raw = ollama_generate(prompt)
    data = parse_llm_json(raw)

    if not data:
        return document, []

    changed = False

    # --- conteúdo textual ---
    new_content = data.get("content")
    if isinstance(new_content, str):
        new_content = [new_content]
    if isinstance(new_content, list):
        clean = [str(x).strip() for x in new_content if str(x).strip()]
        if clean:
            target["content"] = clean
            changed = True

    # --- tabela (apenas se a seção tiver tabela) ---
    if table_columns and isinstance(data.get("table_rows"), list) and data["table_rows"]:
        col_map = {col: _col_to_key(col) for col in table_columns}
        rows = []
        for raw_row in data["table_rows"]:
            if not isinstance(raw_row, dict):
                continue
            row = {}
            for col, key in col_map.items():
                row[col] = raw_row.get(key) or raw_row.get(col) or "A definir"
            rows.append(row)
        if rows:
            target["table_rows"] = rows
            changed = True

    if not changed:
        return document, []

    document["html"] = _rerender(document)
    return document, [target_id]


def explain_section(question: str, document: dict) -> tuple[str, Optional[str]]:
    """
    Explica um tópico do TR em texto corrido (não altera o documento).
    Retorna (mensagem, id_da_secao_ou_None).
    """
    sections = document.get("sections", [])
    target_id = find_target_section_id(question, sections)

    target = None
    if target_id is not None:
        target = next((s for s in sections if str(s.get("id")) == target_id), None)

    if target is None:
        return (
            "Sobre qual tópico você quer a explicação? "
            'Cite o número, por exemplo: "Explique o tópico 4".',
            None,
        )

    prompt = build_explain_section_prompt(
        question=question,
        section=target,
        document_title=document.get("document_title"),
    )
    message = ollama_generate(prompt)
    return message, target_id
