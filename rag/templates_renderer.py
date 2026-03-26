from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "xml"])
)


def render_tr_html(data: dict) -> str:
    template = env.get_template("tr_fsph.html")
    return template.render(**data)


def save_tr_html(data: dict, out_path: str):
    html = render_tr_html(data)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return str(path)


