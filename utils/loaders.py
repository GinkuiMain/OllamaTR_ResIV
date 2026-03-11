from pathlib import Path
from pypdf import PdfReader
import docx
import re
import shutil
import subprocess

# Os documentos que enviaram para a gente estão em DOC, não DOCx. Ou seja, são do office antigo. Consequentemente, vou ter que fazer uma
# Pequena maracutaia para ler .doc.
# Antiword é um leitor de documentos gratúito que formata o .doc.

SUPPORTED = {".txt", ".pdf", ".docx", ".doc"}


# Carregar doc via antiword (caso haja)
def _load_doc_via_antiword(path: Path) -> str:
    try:
        antiword = shutil.which("antiword")
        if not antiword:
            raise ValueError(
                "Arquivo .doc detectado, contudo o antiword não está instalado ou não foi encontrado no PATH.\n"
                "Soluções:\n"
                "1) Salvar o .doc como .docx (Recomendado! Pode usar o CloudConvert, por exemplo)\n"
                "2) Instalar o antiword e tentar novamente."
            )
        # Caso o antiword esteja instalado, ele costuma a devolver bytes com encoding meio antigo- Ai tive que catar na internet como decodificar
        p = subprocess.run([antiword, str(path)], capture_output=True)  # aqui, o antiword devolve bytes que precisam ser decodificados
        out = p.stdout  # A saída em fluxo de bytes
        # Ai agora, tentar decodificar
        if not out:
            return ""
        try:
            return out.decode('utf-8')  # Tentar UTF-8 primeiro
        except UnicodeDecodeError:
            return out.decode('latin-1', errors="ignore")  # Se falhar, tentar Latin-1
    except Exception as e:
        raise ValueError(f"Erro ao processar arquivo .doc com antiword: {e}")

# Reformular load text
def load_text(path: Path) -> str:
    try:
        ext = path.suffix.lower()  # Vai pegar a extensão do arquivo e diminuir-la para o código

        if ext == ".txt":
            return path.read_text(encoding='utf-8', errors="ignore")
        if ext == ".pdf":
            reader = PdfReader(str(path))  # As 4 linhas de código abaixo irão extrair o texto de cada página do nosso PDF
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")

            return "\n".join(parts)
        if ext == ".docx":
            d = docx.Document(str(path))  # O docx é um formato mais moderno, e a biblioteca python-docx consegue ler ele sem problemas. O código abaixo extrai o texto de cada parágrafo do documento e junta tudo em uma string só.
            return "\n".join(p.text for p in d.paragraphs)
        if ext == ".doc":
            return _load_doc_via_antiword(path)  # Só que ai precisa do antiword instalado e configurado no PATH do sistema

        raise ValueError(f"Unsupported file type: {ext}")

    except Exception as e:
        return "Erro ao carregar arquivo {path.name}: {e}"


# Adicionar mostly_upper
def _mostly_upper(s:str) -> bool:  # Isso aqui serve para discernir se um trecho é, ou não é, um título. A ideia é que, se mais de 70% das letras forem maiúsculas, a gente considere que é um título.
    try:
        letters = [c for c in s if c.isalpha()]  # Vai pegar somente as letras do texto
        if len(letters) < 5:
            return False
        upp = sum(1 for c in letters if c.isupper())  # Vai contar quantas letras são maiúsculas
        return upp / len(letters) > 0.6  # Se mais de 60% das letras forem maiúsculas, considerar que é um título
    except Exception as e:
        print("Erro em _mostly_upper: {e}")
        return False


# Extract outline
def extract_outline(text: str) -> list[str]:
    # Pega só as linhas que parecem títulos. Tipo:
    # 1. DAS CONDIÇÕES GERAIS...   2. DO MOTIVO...
    outline =[]
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(\d{1,2})\.\s+(.+)$", line)
        if m:
            title = m.group(2).strip()
            if _mostly_upper(title):
                outline.append(f"{m.group(1)}. {title}")
    return outline


# Extract table columns
def extract_table_columns(text: str) -> list[str]:
    # Tenta pegar colunas de tabela que aparece no item 1.1 (ITEM / DESCRIÇÃO / etc.)
    # Retorna lista de colunas para pedir ao LLM uma tabela igual.
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        up = line.upper()
        if "ITEM" in up and ("DESCRI" in up or "DESCRIÇÃO" in up):
            # junta algumas linhas seguintes pois pode quebrar (ex: QUANTIDADE / ESTIMADA)
            block = " ".join(lines[i:i+4])
            block = re.sub(r"\s{2,}", " ", block)
            # tenta separar por palavras-chave conhecidas
            # fallback: retorna as palavras em caixa alta agrupadas
            cols = []
            # heurística por tokens comuns:
            known = ["ITEM", "DESCRIÇÃO", "APRESENTAÇÃO", "QUANTIDADE", "ESTIMADA", "C/H", "ALUNOS", "TURMA",
                     "VALOR", "UNITÁRIO", "TOTAL", "ESTIMADO", "POR", "GUIA", "CUSTO"]
            tokens = block.replace(":", " ").split()
            buff = []
            for t in tokens:
                tu = t.upper().strip()
                if tu in known:
                    buff.append(t)
                else:
                    # continua
                    pass
            # junta em frases
            if buff:
                joined = " ".join(buff)
                # agrupa "QUANTIDADE ESTIMADA", "VALOR UNITÁRIO", etc.
                joined = joined.replace("QUANTIDADE ESTIMADA", "QUANTIDADE_ESTIMADA")
                joined = joined.replace("VALOR UNITÁRIO", "VALOR_UNITÁRIO")
                joined = joined.replace("VALOR TOTAL", "VALOR_TOTAL")
                parts = joined.split()
                # reconstrução simples
                fixed = []
                for p in parts:
                    p = p.replace("_", " ")
                    if p not in fixed:
                        fixed.append(p)
                # garante que começa por ITEM e DESCRIÇÃO
                if "ITEM" not in fixed:
                    fixed.insert(0, "ITEM")
                if "DESCRIÇÃO" not in fixed:
                    fixed.insert(1, "DESCRIÇÃO")
                return fixed
            return ["ITEM", "DESCRIÇÃO"]
    return []


"""
def load_text(path: Path) -> str:
    ext = path.suffix.lower()

    match ext:
        case ".txt":
            return path.read_text(encoding='utf-8', errors="ignore")
        case ".pdf":
            reader = PdfReader(str(path))
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            return "\n".join(parts)
        case ".docx":
            d = docx.Document(str(path))
            return "\n".join(p.text for p in d.paragraphs)
    raise ValueError(f"Unsupported file type: {ext}")
"""