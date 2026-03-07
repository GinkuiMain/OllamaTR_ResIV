# OllamaTR_ResIV

API RAG local com FastAPI + ChromaDB + Ollama para responder perguntas com base nos documentos em `data/docs`.

## Requisitos

- Windows 10/11
- VS Code
- Python `3.11.x` (recomendado) ou `3.12.x`
- Ollama instalado

## Compatibilidade de versao (importante)

Este projeto usa `chromadb`, que ainda depende de partes do `pydantic v1` internamente.

Por isso, **nao use Python 3.14** neste projeto.

Use:

- Python 3.11 (recomendado)
- Python 3.12

## 1) Instalar Python correto

Baixe e instale Python 3.11:

`https://www.python.org/downloads/release/python-3119/`

Na instalacao, marque:

- `Add Python 3.11 to PATH`

Depois confirme no PowerShell:

```powershell
py --list-paths
```

Voce deve ver algo como `-V:3.11 ...`.

## 2) Criar ambiente virtual no VS Code

No terminal do projeto (`...\OllamaTR_ResIV`):

```powershell
rmdir venv /s /q
py -3.11 -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Se o VS Code nao selecionar o interpretador automaticamente:

- `Ctrl+Shift+P`
- `Python: Select Interpreter`
- Escolha `venv\Scripts\python.exe`

## 3) Instalar e preparar Ollama

Instale o Ollama:

`https://ollama.com/download`

No terminal (com internet), baixe os modelos usados pelo projeto:

```powershell
ollama pull mistral
ollama pull nomic-embed-text
```

Se necessario, inicie o servico local:

```powershell
ollama serve
```

Padrao esperado pelo projeto:

- Ollama em `http://localhost:11434`
- LLM: `mistral`
- Embeddings: `nomic-embed-text`

## 4) Rodar a API

```powershell
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

API disponivel em:

- `http://127.0.0.1:8000`
- Docs Swagger: `http://127.0.0.1:8000/docs`

## 5) Indexar documentos (obrigatorio antes do chat)

Coloque arquivos `.txt`, `.pdf` ou `.docx` em `data/docs` e rode:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/admin/index
```

Isso cria/atualiza a base vetorial em `data/chroma`.

## 6) Consultar o chat

Exemplo no PowerShell:

```powershell
$body = @{
	question = "Quais sao os principais requisitos do termo?"
	top_k = 6
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat -ContentType "application/json" -Body $body
```

## Endpoints

- `GET /health`: status da API
- `POST /admin/index`: indexa documentos de `data/docs`
- `POST /chat`: gera resposta RAG com fontes

## Estrutura do projeto

```text
app.py
requirements.txt
data/
	docs/
	chroma/            # gerado automaticamente apos indexacao
prompts/
	prompts.py
rag/
	ingest.py          # indexacao e embeddings
	rag.py             # retrieval + geracao
utils/
	loaders.py         # leitura de txt/pdf/docx
```

## Solucao de problemas

### Erro: "No suitable Python runtime found"

Python 3.11 nao esta instalado. Instale e tente novamente:

```powershell
py -3.11 -m venv venv
```

### Erro com `pydantic.v1` e Python 3.14

Troque para Python 3.11/3.12 e recrie o `venv`.

### Erro de conexao com Ollama

Verifique se o Ollama esta rodando e se os modelos foram baixados:

```powershell
ollama list
```

### Chat sem resposta util

- Verifique se indexou os documentos com `POST /admin/index`
- Confira se os arquivos estao em `data/docs`
- Reindexe apos alterar documentos
