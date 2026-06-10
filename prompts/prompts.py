import json
import re

"""
Aqui é o arquivo de personalidade / construção de prompt para o Maestro / FSPH AI
Quando tivermos que fazer a alteração que o mentor pediu, não a empresa, de colocar uma personalidade nela, ajustaremos aqui.
"""


def _col_to_key(col: str) -> str:
    """
    Converte nome de coluna em chave JSON segura.

    Ex:
    "VALOR UNITÁRIO (R$)" -> "VALOR_UNITARIO_RS"
    """
    text = col.upper()
    text = (
        text.replace("Á", "A")
        .replace("À", "A")
        .replace("Â", "A")
        .replace("Ã", "A")
        .replace("É", "E")
        .replace("Ê", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ô", "O")
        .replace("Õ", "O")
        .replace("Ú", "U")
        .replace("Ç", "C")
    )
    text = re.sub(r"[^A-Z0-9 ]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text


def build_prompt(
    *,
    base_source: str,
    sections: list[dict],
    table_columns: list[str],
    context: str,
    question: str,
) -> str:
    section_schema = {
        section["id"]: ["..."]
        for section in sections
    }

    table_schema = []
    if table_columns:
        table_schema = [
            {
                _col_to_key(col): "..."
                for col in table_columns
            }
        ]

    expected_json = {
        "sections": section_schema,
        "table_rows": table_schema,
        "footer_text": "",
    }

    section_list = "\n".join(
        f'{section["id"]}. {section["title"]}'
        for section in sections
    )

    if table_columns:
        column_mapping = "\n".join(
            f'- "{col}" deve ser preenchida usando a chave JSON "{_col_to_key(col)}"'
            for col in table_columns
        )
    else:
        column_mapping = "Este modelo não possui tabela de itens."

    return f"""
Você é o assistente técnico-jurídico da Fundação de Saúde Parreiras Horta.

Sua tarefa é preencher os campos variáveis de um Termo de Referência.

IMPORTANTE:
A estrutura do documento já foi extraída do TR oficial "{base_source}".
Você NÃO deve criar novas seções.
Você NÃO deve remover seções.
Você NÃO deve alterar títulos.
Você deve apenas preencher o conteúdo textual de cada seção.

REGRAS:
1. Retorne SOMENTE JSON válido.
2. Não use markdown.
3. Não escreva explicações fora do JSON.
4. Não invente dados fora do contexto.
5. Quando faltar informação, escreva "A definir".
6. Cada seção deve conter uma lista de strings.
7. Evite repetir exatamente o mesmo texto em várias seções.
8. Use linguagem formal, objetiva e compatível com Termo de Referência.

SEÇÕES EXTRAÍDAS DO TR BASE:
{section_list}

COLUNAS DA TABELA:
{column_mapping}

FORMATO JSON ESPERADO:
{json.dumps(expected_json, ensure_ascii=False, indent=2)}

CONTEXTO RECUPERADO:
{context}

PEDIDO DO USUÁRIO:
{question}

Retorne agora somente o JSON válido.
""".strip()


def build_conversational_prompt(question: str) -> str:
    return (
        "Você é o assistente virtual da Fundação de Saúde Parreiras Horta, "
        "especializado em Termos de Referência, contratações públicas e licitações.\n"
        "Responda de forma cordial, breve e em português.\n"
        "Se a mensagem for apenas uma saudação, responda naturalmente e oriente "
        "o usuário a descrever a contratação que deseja transformar em TR.\n\n"
        f"Mensagem do usuário: {question}"
    )


def build_document_query_prompt(question: str, context: str) -> str:
    return (
        "Você é o assistente técnico-jurídico da Fundação de Saúde Parreiras Horta.\n"
        "Responda à dúvida do usuário com base no contexto fornecido.\n"
        "Não gere um Termo de Referência. Apenas responda a dúvida.\n\n"
        f"CONTEXTO:\n{context}\n\n"
        f"DÚVIDA DO USUÁRIO:\n{question}"
    )


def build_edit_section_prompt(
    *,
    section: dict,
    change_request: str,
    table_columns: list[str],
) -> str:
    """
    Prompt para editar UMA seção de um TR já existente.

    Diferente de build_prompt (que gera o documento inteiro), aqui o modelo
    recebe o conteúdo atual da seção e deve devolver apenas a versão atualizada,
    aplicando somente a alteração pedida.
    """
    current_content = "\n".join(f"- {p}" for p in section.get("content", [])) or "(seção vazia)"

    has_table = bool(table_columns)
    if has_table:
        col_lines = "\n".join(
            f'- "{col}" deve usar a chave JSON "{_col_to_key(col)}"'
            for col in table_columns
        )
        current_rows = json.dumps(section.get("table_rows", []), ensure_ascii=False, indent=2)
        table_block = (
            "\nESTA SEÇÃO TAMBÉM POSSUI UMA TABELA.\n"
            f"Colunas e respectivas chaves JSON:\n{col_lines}\n\n"
            f"LINHAS ATUAIS DA TABELA:\n{current_rows}\n\n"
            'Se a alteração afetar a tabela, devolva "table_rows" com as linhas '
            "atualizadas (use as chaves JSON acima). Se a tabela não muda, "
            'devolva "table_rows" exatamente como está.\n'
        )
        expected_json = {
            "content": ["..."],
            "table_rows": [{_col_to_key(col): "..." for col in table_columns}],
        }
    else:
        table_block = ""
        expected_json = {"content": ["..."]}

    return f"""
Você é o assistente técnico-jurídico da Fundação de Saúde Parreiras Horta.
Você está EDITANDO uma única seção de um Termo de Referência que já existe.

SEÇÃO ALVO:
{section.get("id")}. {section.get("title")}

CONTEÚDO ATUAL DA SEÇÃO:
{current_content}
{table_block}
ALTERAÇÃO SOLICITADA PELO USUÁRIO:
{change_request}

REGRAS:
1. Aplique APENAS a alteração pedida; preserve o restante do conteúdo da seção.
2. NÃO altere o título nem o número da seção.
3. NÃO invente dados que o usuário não forneceu; quando faltar, use "A definir".
4. Use linguagem formal, objetiva, compatível com Termo de Referência.
5. Retorne SOMENTE JSON válido, sem markdown e sem explicações fora do JSON.
6. O campo "content" deve ser uma lista de strings (um item por parágrafo).

FORMATO JSON ESPERADO:
{json.dumps(expected_json, ensure_ascii=False, indent=2)}

Retorne agora somente o JSON válido.
""".strip()


def build_explain_section_prompt(
    *,
    question: str,
    section: dict,
    document_title: str | None = None,
) -> str:
    """Prompt para explicar um tópico do TR em texto corrido (sem gerar documento)."""
    content = "\n".join(f"- {p}" for p in section.get("content", [])) or "(seção vazia)"

    return (
        "Você é o assistente técnico-jurídico da Fundação de Saúde Parreiras Horta.\n"
        "Explique, em português claro e objetivo, o tópico indicado do Termo de Referência.\n"
        "NÃO gere um novo documento e NÃO retorne JSON. Responda em texto corrido.\n\n"
        f"DOCUMENTO: {document_title or 'TERMO DE REFERÊNCIA'}\n\n"
        f"TÓPICO {section.get('id')}. {section.get('title')}\n"
        f"CONTEÚDO DO TÓPICO:\n{content}\n\n"
        f"PERGUNTA DO USUÁRIO:\n{question}"
    )