"""
prompts.py
Gera o SYSTEM_PROMPT dinamicamente com base no perfil do TR escolhido.

Por que dinâmico?
- servico_padrao tem 14 seções e tabela com 6 colunas (BRINDES / CURSOS)
- bens         tem 14 seções, seção 6 diferente, tabela com 5 colunas (MOBILIÁRIO)
- evento_curto tem  9 seções e tabela com 4 colunas (HEMO)
Um prompt único com keys fixas confundia o LLM nos perfis menores.
"""

import re
from rag.template_profiles import TEMPLATE_PROFILES


# ---------------------------------------------------------------------------
# Mapeamento: nome da coluna → key JSON segura (sem espaços, sem parênteses)
# ---------------------------------------------------------------------------
def _col_to_key(col: str) -> str:
    """'VALOR UNITÁRIO (R$)' → 'VALOR_UNITARIO_RS'"""
    s = col.upper()
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    s = s.strip().replace(" ", "_")
    return s


def build_prompt(
    profile_name: str,
    table_columns: list,
    base_source: str,
    context: str,
    question: str,
) -> str:
    """
    Monta o SYSTEM_PROMPT completo com:
    - seções corretas para o perfil escolhido
    - keys JSON derivadas das colunas reais da tabela
    - instruções anti-alucinação
    """
    profile = TEMPLATE_PROFILES.get(profile_name, TEMPLATE_PROFILES["servico_padrao"])
    sections = profile["sections"]

    # --- bloco de seções (todas exceto a 1, que tem campos próprios) -------
    sections_list = "\n".join(
        f'  "section_{s["id"]}_paragraphs": ["..."]  // {s["title"]}'
        for s in sections
        if s["kind"] != "opening_with_table"
    )

    # --- bloco da tabela ---------------------------------------------------
    if table_columns:
        col_keys = {col: _col_to_key(col) for col in table_columns}
        col_mapping = "\n".join(f'    "{k}": "..."' for k in col_keys.values())
        table_block = f"""  "table_rows": [
    {{
{col_mapping}
    }}
  ],"""
        col_hint = (
            "COLUNAS DA TABELA (use exatamente estas keys no JSON):\n"
            + "\n".join(f'  "{col}" → key JSON: "{key}"'
                        for col, key in col_keys.items())
        )
    else:
        table_block = '  "table_rows": [],'
        col_hint = "Esta contratação não possui tabela de itens."

    prompt = f"""Você é o assistente jurídico-técnico da FSPH (Fundação de Saúde Parreiras Horta).
Sua tarefa é gerar um Termo de Referência completo baseado no pedido do usuário e no contexto fornecido.

REGRAS ABSOLUTAS:
1. Retorne SOMENTE JSON válido, sem markdown, sem texto fora do JSON.
2. Não invente fatos fora do CONTEXTO. Se faltar informação, escreva "A definir".
3. Não altere os títulos das seções — eles estão fixos no sistema.
4. A escrita deve ser formal, técnica e jurídica, seguindo a Lei nº 14.133/2021.
5. Cada item de lista de parágrafos deve ser uma string completa, nunca vazia.

PERFIL DO TR: {profile_name}
TR BASE (modelo de estilo): {base_source}

{col_hint}

FORMATO JSON ESPERADO:
{{
  "opening_paragraphs": ["Parágrafo 1.1 ...", "Parágrafo 1.2 ...", "Parágrafo 1.3 ..."],
{table_block}
{sections_list}
}}

CONTEXTO (trechos recuperados dos TRs oficiais da FSPH):
{context}

PEDIDO DO USUÁRIO:
{question}

Redija agora o Termo de Referência completo no formato JSON acima.
"""
    return prompt
