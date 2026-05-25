import shutil
from pathlib import Path
from fastapi import UploadFile
from rag.ingest import index_docs

from utils.docs_utils import get_docs_folder, safe_filename


async def processar_upload(arquivo: UploadFile) -> dict:
    """Valida, salva e indexa o documento enviado."""
    extensoes_permitidas = {".pdf", ".docx", ".txt", ".doc"}
    extensao = Path(arquivo.filename).suffix.lower()

    if extensao not in extensoes_permitidas:
        return {
            "ok": False,
            "msg": f"Extensão '{extensao}' não permitida. Use: {extensoes_permitidas}"
        }

    nome_seguro = safe_filename(arquivo.filename)
    destino = get_docs_folder() / nome_seguro

    with open(destino, "wb") as buffer:
        shutil.copyfileobj(arquivo.file, buffer)

    resultado = index_docs("data/docs", reset=False)

    return {
        "ok": True,
        "arquivo": nome_seguro,
        "indexacao": resultado,
    }
