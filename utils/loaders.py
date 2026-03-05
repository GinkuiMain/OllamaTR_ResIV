from pathlib import Path
from pypdf import PdfReader
import docx

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