from pathlib import Path

from utils.docs_utils import ALLOWED_EXTENSIONS, get_docs_folder, safe_filename
from rag.ingest import index_docs


def _find_document_path(folder: Path, nome_seguro: str) -> Path | None:
    candidate = folder / nome_seguro
    if candidate.exists() and candidate.is_file():
        return candidate

    target_stem = Path(nome_seguro).stem
    matches = [
        path for path in folder.iterdir()
        if path.is_file()
        and path.suffix.lower() in ALLOWED_EXTENSIONS
        and path.stem == target_stem
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def remover_documento(nome_arquivo: str) -> dict:
    nome_seguro = safe_filename(nome_arquivo)
    if nome_seguro != nome_arquivo:
        return {"ok": False, "msg": "Nome de arquivo inválido."}

    folder = get_docs_folder()
    arquivo_path = _find_document_path(folder, nome_seguro)
    if arquivo_path is None:
        return {"ok": False, "msg": f"Arquivo '{nome_seguro}' não encontrado."}

    arquivo_path.unlink()
    resultado = index_docs("data/docs", reset=True)

    return {
        "ok": True,
        "arquivo_removido": arquivo_path.name,
        "indexacao": resultado,
    }
