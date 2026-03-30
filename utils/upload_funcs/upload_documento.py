import shutil
from pathlib import Path
from fastapi import UploadFile
from rag.ingest import index_docs


async def processar_upload(arquivo: UploadFile) -> dict:
    """Valida, salva e indexa o documento enviado."""
    extensoes_permitidas = {".pdf", ".docx", ".txt", ".doc"}
    extensao = Path(arquivo.filename).suffix.lower()

    if extensao not in extensoes_permitidas:
        return {
            "ok": False,
            "msg": f"Extensão '{extensao}' não permitida. Use: {extensoes_permitidas}"
        }

    destino = Path("data/docs") / arquivo.filename
    with open(destino, "wb") as buffer:
        shutil.copyfileobj(arquivo.file, buffer)

    resultado = index_docs("data/docs", reset=False)

    return {
        "ok": True,
        "arquivo": arquivo.filename,
        "indexacao": resultado
    }