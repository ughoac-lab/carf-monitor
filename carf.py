"""Coleta acórdãos do CARF publicados no último dia útil e gera HTML."""

from __future__ import annotations

import datetime
import html
import sys
import webbrowser
from pathlib import Path

import requests

SOLR_URL = "https://acordaos.economia.gov.br/solr/acordaos2/select"
PDF_BASE = "https://acordaos.economia.gov.br/acordaos2/pdfs/processados"
OUTPUT_FILE = Path(__file__).parent / "index.html"

WEEKDAY_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def target_date(today: datetime.date | None = None) -> datetime.date:
    today = today or datetime.date.today()
    if today.weekday() == 0:  # segunda → busca sexta
        return today - datetime.timedelta(days=3)
    return today - datetime.timedelta(days=1)


def fetch_acordaos(date: datetime.date) -> tuple[list[dict], int]:
    start = date.strftime("%Y-%m-%dT00:00:00Z")
    end = date.strftime("%Y-%m-%dT23:59:59.999Z")
    params = {
        "q": "*:*",
        "fq": f"dt_publicacao_tdt:[{start} TO {end}]",
        "wt": "json",
        "rows": 5000,
        "fl": "id,numero_processo_s,numero_decisao_s,ementa_s,nome_relator_s,"
              "camara_s,turma_s,secao_s,nome_arquivo_pdf_s,dt_publicacao_tdt",
        "sort": "secao_s asc,camara_s asc,numero_processo_s asc",
    }
    response = requests.get(SOLR_URL, params=params, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["response"]["docs"], data["response"]["numFound"]


def render_item(doc: dict) -> str:
    e = html.escape
    processo = e(doc.get("numero_processo_s", "?"))
    decisao = e(doc.get("numero_decisao_s", "?"))
    ementa = e(doc.get("ementa_s", "(sem ementa)"))
    relator = e(doc.get("nome_relator_s", "?"))
    contexto = " · ".join(filter(None, [
        doc.get("secao_s", ""),
        doc.get("camara_s", ""),
        doc.get("turma_s", ""),
    ]))
    pdf_name = doc.get("nome_arquivo_pdf_s")
    pdf_link = (
        f' · <a href="{e(PDF_BASE + "/" + pdf_name)}" target="_blank">PDF</a>'
        if pdf_name else ""
    )
    return f"""<article class="acordao">
  <header>
    <h2>Acórdão {decisao}{pdf_link}</h2>
    <div class="meta">
      Processo {processo}<br>
      Relator: {relator}<br>
      {e(contexto)}
    </div>
  </header>
  <div class="ementa">{ementa}</div>
</article>"""


def render_html(docs: list[dict], date: datetime.date, total: int) -> str:
    date_str = date.strftime("%d/%m/%Y")
    weekday_pt = WEEKDAY_PT[date.weekday()]
    now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    if not docs:
        body = '<p class="empty">Nenhum acórdão publicado nesta data.</p>'
    else:
        plural = "s" if total != 1 else ""
        items = "\n".join(render_item(d) for d in docs)
        body = f'<p class="count">{total} acórdão{plural} publicado{plural}.</p>\n{items}'

    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>CARF — {date_str}</title>
  <style>
    body {{ font-family: -apple-system, system-ui, Segoe UI, sans-serif;
            max-width: 900px; margin: 2em auto; padding: 0 1em;
            color: #222; line-height: 1.5; }}
    h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3em; margin-bottom: 0.5em; }}
    h1 small {{ display: block; font-size: 0.55em; color: #666;
                font-weight: normal; margin-top: 0.4em; }}
    .count {{ color: #666; font-style: italic; }}
    .empty {{ color: #999; font-style: italic; padding: 2em 0; text-align: center; }}
    .acordao {{ border: 1px solid #ddd; border-radius: 6px;
                padding: 1em 1.2em; margin: 1.2em 0; background: #fafafa; }}
    .acordao header {{ margin-bottom: 0.7em; }}
    .acordao h2 {{ margin: 0 0 0.4em 0; font-size: 1.1em; }}
    .acordao .meta {{ color: #555; font-size: 0.9em; }}
    .acordao .ementa {{ white-space: pre-wrap; margin: 0.8em 0 0 0;
                        font-size: 0.95em; color: #333; }}
    a {{ color: #0366d6; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>Acórdãos CARF
    <small>Publicados em {weekday_pt}, {date_str} · gerado em {now_str}</small>
  </h1>
  {body}
</body>
</html>"""


def main() -> None:
    if len(sys.argv) > 1:
        date = datetime.date.fromisoformat(sys.argv[1])
        print(f"Data informada: {date.strftime('%d/%m/%Y')}")
    else:
        date = target_date()
        print(f"Data calculada (último dia útil): {date.strftime('%d/%m/%Y')}")

    print("Consultando Solr...")
    docs, total = fetch_acordaos(date)
    print(f"Encontrados: {total} acórdão(s)")

    html_text = render_html(docs, date, total)
    OUTPUT_FILE.write_text(html_text, encoding="utf-8")
    print(f"HTML salvo em: {OUTPUT_FILE}")

    webbrowser.open(OUTPUT_FILE.as_uri())
    print("Abrindo no navegador...")


if __name__ == "__main__":
    main()
