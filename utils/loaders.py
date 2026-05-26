from pathlib import Path
from pypdf import PdfReader
import docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
import re
import shutil
import subprocess

SUPPORTED = {".txt", ".pdf", ".docx", ".doc"}


def _clean(text: str) -> str:
    text = (text or "").replace("\xa0", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _load_doc_via_antiword(path: Path) -> str:
    antiword = shutil.which("antiword")
    if not antiword:
        raise ValueError(
            "Arquivo .doc detectado, mas o antiword não está instalado.\n"
            "Solução recomendada: salvar o arquivo como .docx."
        )

    result = subprocess.run([antiword, str(path)], capture_output=True)
    out = result.stdout

    if not out:
        return ""

    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return out.decode("latin-1", errors="ignore")


def _iter_docx_blocks(document: DocxDocument):
    """
    Percorre parágrafos e tabelas na ordem real em que aparecem no DOCX.
    Isso é importante porque a tabela geralmente aparece dentro da seção 1.
    """
    body = document.element.body

    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


def _row_cells(row) -> list[str]:
    cells = []
    seen_adjacent = None

    for cell in row.cells:
        value = _clean(cell.text)

        if not value:
            continue

        # DOCX com célula mesclada às vezes repete o texto da célula.
        if value == seen_adjacent:
            continue

        seen_adjacent = value
        cells.append(value)

    return cells


def _table_to_lines(table: Table) -> list[str]:
    lines = []

    for row in table.rows:
        cells = _row_cells(row)
        if cells:
            lines.append(" | ".join(cells))

    return lines


def _normalize_column_name(value: str) -> str:
    value = _clean(value)
    value = value.replace(" / ", " ")
    value = value.replace("/", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip().upper()


def _extract_table_columns_from_table(table: Table) -> list[str]:
    if not table.rows:
        return []

    # Procura a primeira linha que parece cabeçalho de tabela de itens.
    for row in table.rows[:3]:
        cells = _row_cells(row)
        normalized = [_normalize_column_name(c) for c in cells]

        has_item = any(c == "ITEM" for c in normalized)
        has_descricao = any("DESCRI" in c for c in normalized)

        if has_item and has_descricao:
            columns = []
            seen = set()

            for raw in cells:
                col = _normalize_column_name(raw)

                if not col:
                    continue

                if col in seen:
                    continue

                seen.add(col)
                columns.append(col)

            return columns

    return []


def load_text(path: Path) -> str:
    ext = path.suffix.lower()

    if ext == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")

    if ext == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    if ext == ".docx":
        document = docx.Document(str(path))
        parts = []

        for block in _iter_docx_blocks(document):
            if isinstance(block, Paragraph):
                text = _clean(block.text)
                if text:
                    parts.append(text)

            elif isinstance(block, Table):
                parts.extend(_table_to_lines(block))

        return "\n".join(parts)

    if ext == ".doc":
        return _load_doc_via_antiword(path)

    raise ValueError(f"Extensão não suportada: {ext}")


def _mostly_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]

    if len(letters) < 8:
        return False

    uppercase = sum(1 for c in letters if c.isupper())
    return uppercase / len(letters) >= 0.60


def _strip_heading_number(text: str) -> str:
    text = _clean(text)
    text = re.sub(r"^\d{1,2}\s*[.\-]?\s*", "", text)
    return _clean(text)


def _is_main_heading(text: str) -> bool:
    text = _clean(text)

    if not text:
        return False

    if text.upper() == "TERMO DE REFERÊNCIA":
        return False

    if "|" in text:
        return False

    # Não considera subitens como 4.1, 4.1.1 etc. como seção principal.
    if re.match(r"^\d{1,2}\.\d+", text):
        return False

    without_number = _strip_heading_number(text)

    if len(without_number) < 10:
        return False

    return _mostly_upper(without_number)


def extract_template(path: Path) -> dict:
    """
    Extrai a estrutura do próprio documento:
    - título
    - seções
    - ordem das seções
    - tabelas e colunas
    """
    ext = path.suffix.lower()

    template = {
        "source": path.name,
        "document_title": "TERMO DE REFERÊNCIA",
        "sections": [],
        "table_columns": [],
    }

    if ext != ".docx":
        raw = load_text(path)
        return _extract_template_from_text(path.name, raw)

    document = docx.Document(str(path))

    current_section = None
    section_counter = 0

    for block in _iter_docx_blocks(document):
        if isinstance(block, Paragraph):
            text = _clean(block.text)

            if not text:
                continue

            if text.upper() == "TERMO DE REFERÊNCIA":
                template["document_title"] = text.upper()
                continue

            if _is_main_heading(text):
                if current_section:
                    template["sections"].append(current_section)

                section_counter += 1
                current_section = {
                    "id": str(section_counter),
                    "title": _strip_heading_number(text),
                    "content_sample": [],
                    "table_columns": [],
                }
                continue

            if current_section:
                current_section["content_sample"].append(text)

        elif isinstance(block, Table):
            columns = _extract_table_columns_from_table(block)

            if current_section and columns:
                current_section["table_columns"] = columns

                if not template["table_columns"]:
                    template["table_columns"] = columns

            elif current_section:
                current_section["content_sample"].extend(_table_to_lines(block)[:3])

    if current_section:
        template["sections"].append(current_section)

    return template


def _extract_template_from_text(source_name: str, text: str) -> dict:
    lines = [_clean(line) for line in text.splitlines() if _clean(line)]

    template = {
        "source": source_name,
        "document_title": "TERMO DE REFERÊNCIA",
        "sections": [],
        "table_columns": extract_table_columns(text),
    }

    current = None
    counter = 0

    for line in lines:
        if line.upper() == "TERMO DE REFERÊNCIA":
            template["document_title"] = line.upper()
            continue

        if _is_main_heading(line):
            if current:
                template["sections"].append(current)

            counter += 1
            current = {
                "id": str(counter),
                "title": _strip_heading_number(line),
                "content_sample": [],
                "table_columns": template["table_columns"] if counter == 1 else [],
            }
            continue

        if current:
            current["content_sample"].append(line)

    if current:
        template["sections"].append(current)

    return template


def extract_outline(text: str) -> list[str]:
    template = _extract_template_from_text("raw_text", text)
    return [f'{s["id"]}. {s["title"]}' for s in template["sections"]]


def extract_table_columns(text: str) -> list[str]:
    upper = text.upper()

    if "ITEM" not in upper or "DESCRI" not in upper:
        return []

    if "ALUNOS POR TURMA" in upper or "C/H" in upper:
        return [
            "ITEM",
            "DESCRIÇÃO",
            "C/H",
            "ALUNOS POR TURMA",
            "QUANT DE TURMAS",
            "VALOR ESTIMADO POR TURMA (R$)",
        ]

    if "QUANTIDADE ESTIMADA" in upper or "APRESENTAÇÃO" in upper:
        return [
            "ITEM",
            "DESCRIÇÃO",
            "APRESENTAÇÃO",
            "QUANTIDADE ESTIMADA",
            "VALOR UNITÁRIO (R$)",
            "VALOR TOTAL (R$)",
        ]

    if "VALOR TOTAL ESTIMADO" in upper:
        return [
            "ITEM",
            "DESCRIÇÃO",
            "QUANTIDADE",
            "VALOR UNITÁRIO",
            "VALOR TOTAL ESTIMADO",
        ]

    return ["ITEM", "DESCRIÇÃO"]