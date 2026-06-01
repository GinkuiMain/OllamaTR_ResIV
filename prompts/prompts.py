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