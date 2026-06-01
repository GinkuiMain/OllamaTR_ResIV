from pathlib import Path

from utils.docs_utils import format_file_metadata, get_docs_folder


def listar_documentos() -> dict:
    folder = get_docs_folder()
    extensoes_permitidas = {".pdf", ".docx", ".txt", ".doc"}
    arquivos = []

    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in extensoes_permitidas:
            continue

        arquivos.append(format_file_metadata(path))

    return {"ok": True, "arquivos": arquivos}
