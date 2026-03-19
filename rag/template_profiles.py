TEMPLATE_PROFILES = {
    "servico_padrao": {
        "title": "TERMO DE REFERÊNCIA",
        "sections": [
            {"id": "1", "title": "DAS CONDIÇÕES GERAIS DA CONTRATAÇÃO", "kind": "opening_with_table"},
            {"id": "2", "title": "FUNDAMENTAÇÃO E DESCRIÇÃO DA NECESSIDADE DE CONTRATAÇÃO", "kind": "paragraphs"},
            {"id": "3", "title": "DESCRIÇÃO DA SOLUÇÃO COMO UM TODO CONSIDERANDO O CICLO DE VIDA DO OBJETO E ESPECIFICAÇÃO DO PRODUTO", "kind": "paragraphs"},
            {"id": "4", "title": "REQUISITOS DA CONTRATAÇÃO", "kind": "paragraphs"},
            {"id": "5", "title": "MODELO DE EXECUÇÃO CONTRATUAL", "kind": "paragraphs"},
            {"id": "6", "title": "MATERIAIS A SEREM DISPONIBILIZADOS", "kind": "paragraphs"},
            {"id": "7", "title": "MODELO DE GESTÃO DO CONTRATO", "kind": "paragraphs"},
            {"id": "8", "title": "FORMA E CRITÉRIOS DE SELEÇÃO DO FORNECEDOR", "kind": "paragraphs"},
            {"id": "9", "title": "CRITÉRIOS DE MEDIÇÃO E DE PAGAMENTO", "kind": "paragraphs"},
            {"id": "10", "title": "ESTIMATIVA DO VALOR DA CONTRATAÇÃO", "kind": "paragraphs"},
            {"id": "11", "title": "OBRIGAÇÕES DA CONTRATANTE", "kind": "paragraphs"},
            {"id": "12", "title": "OBRIGAÇÕES DA CONTRATADA", "kind": "paragraphs"},
            {"id": "13", "title": "INDICAÇÃO DE GESTOR E FISCAL DO CONTRATO", "kind": "paragraphs"},
            {"id": "14", "title": "ADEQUAÇÃO ORÇAMENTÁRIA", "kind": "paragraphs"},
        ]
    },
    "bens": {
        "title": "TERMO DE REFERÊNCIA",
        "sections": [
            {"id": "1", "title": "DAS CONDIÇÕES GERAIS DA CONTRATAÇÃO", "kind": "opening_with_table"},
            {"id": "2", "title": "FUNDAMENTAÇÃO E DESCRIÇÃO DA NECESSIDADE DE CONTRATAÇÃO", "kind": "paragraphs"},
            {"id": "3", "title": "DESCRIÇÃO DA SOLUÇÃO COMO UM TODO CONSIDERANDO O CICLO DE VIDA DO OBJETO E ESPECIFICAÇÃO DO PRODUTO", "kind": "paragraphs"},
            {"id": "4", "title": "REQUISITOS DA CONTRATAÇÃO", "kind": "paragraphs"},
            {"id": "5", "title": "MODELO DE EXECUÇÃO CONTRATUAL", "kind": "paragraphs"},
            {"id": "6", "title": "GARANTIA, MANUTENÇÃO E ASSISTÊNCIA TÉCNICA", "kind": "paragraphs"},
            {"id": "7", "title": "MODELO DE GESTÃO DO CONTRATO", "kind": "paragraphs"},
            {"id": "8", "title": "FORMA E CRITÉRIOS DE SELEÇÃO DO FORNECEDOR", "kind": "paragraphs"},
            {"id": "9", "title": "CRITÉRIOS DE MEDIÇÃO E DE PAGAMENTO", "kind": "paragraphs"},
            {"id": "10", "title": "ESTIMATIVA DO VALOR DA CONTRATAÇÃO", "kind": "paragraphs"},
            {"id": "11", "title": "OBRIGAÇÕES DA CONTRATANTE", "kind": "paragraphs"},
            {"id": "12", "title": "OBRIGAÇÕES DA CONTRATADA", "kind": "paragraphs"},
            {"id": "13", "title": "INDICAÇÃO DE GESTOR E FISCAL DO CONTRATO", "kind": "paragraphs"},
            {"id": "14", "title": "ADEQUAÇÃO ORÇAMENTÁRIA", "kind": "paragraphs"},
        ]
    },
    "evento_curto": {
        "title": "TERMO DE REFERÊNCIA",
        "sections": [
            {"id": "1", "title": "DAS CONDIÇÕES GERAIS DA CONTRATAÇÃO", "kind": "opening_with_table"},
            {"id": "2", "title": "FUNDAMENTAÇÃO E DESCRIÇÃO DA NECESSIDADE DE CONTRATAÇÃO", "kind": "paragraphs"},
            {"id": "3", "title": "DESCRIÇÃO DA SOLUÇÃO COMO UM TODO CONSIDERANDO O CICLO DE VIDA DO OBJETO E ESPECIFICAÇÃO DO PRODUTO", "kind": "paragraphs"},
            {"id": "4", "title": "REQUISITOS DA CONTRATAÇÃO", "kind": "paragraphs"},
            {"id": "5", "title": "MODELO DE EXECUÇÃO CONTRATUAL", "kind": "paragraphs"},
            {"id": "6", "title": "MATERIAIS A SEREM DISPONIBILIZADOS", "kind": "paragraphs"},
            {"id": "7", "title": "INFORMAÇÕES RELEVANTES PARA A DIMENSIONAMENTO DA PROPOSTA", "kind": "paragraphs"},
            {"id": "8", "title": "MODELO DE GESTÃO DO CONTRATO", "kind": "paragraphs"},
            {"id": "9", "title": "ADEQUAÇÃO ORÇAMENTÁRIA", "kind": "paragraphs"},
        ]
    }
}


def choose_profile(base_source: str) -> str:
    s = (base_source or "").lower()

    if "mobili" in s:
        return "bens"
    if "hemo" in s and "monitor" not in s:
        return "evento_curto"
    return "servico_padrao"