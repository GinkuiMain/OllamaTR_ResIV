from datetime import datetime, timezone
from pathlib import Path

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".doc"}


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1 << 30:
        return f"{size_bytes / (1 << 30):.2f} GB"
    if size_bytes >= 1 << 20:
        return f"{size_bytes / (1 << 20):.2f} MB"
    if size_bytes >= 1 << 10:
        return f"{size_bytes / (1 << 10):.2f} KB"
    return f"{size_bytes} B"


def get_docs_folder() -> Path:
    folder = Path("data/docs")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def safe_filename(filename: str) -> str:
    return Path(filename).name


def format_file_metadata(path: Path) -> dict:
    stat = path.stat()
    return {
        "nome": path.name,
        "tamanho_bytes": stat.st_size,
        "tamanho": _format_size(stat.st_size),
        "ultima_atualizacao": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }
