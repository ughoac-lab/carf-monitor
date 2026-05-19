"""Coleta acórdãos do CARF (via Solr) publicados recentemente e gera HTML.

Estratégia (caminho A):
- Consulta uma JANELA MÓVEL dos últimos QUERY_DAYS dias de publicação.
- Mantém memória (seen.json) dos acórdãos já mostrados, para nunca repetir
  nem perder — mesmo quando o indexador do CARF atrasa e despeja um lote
  de acórdãos com datas de publicação de vários dias atrás.
- A página exibe os acórdãos dos últimos DISPLAY_DAYS dias MAIS quaisquer
  acórdãos recém-detectados (mesmo que mais antigos), marcados com "NOVO".
"""

from __future__ import annotations

import datetime
import html
import json
import os
import sys
import webbrowser
from pathlib import Path

import requests

SOLR_URL = "https://acordaos.economia.gov.br/solr/acordaos2/select"
PDF_BASE = "https://acordaos.economia.gov.br/acordaos2/pdfs/processados"
OUTPUT_FILE = Path(__file__).parent / "index.html"
SEEN_FILE = Path(__file__).parent / "seen.json"

QUERY_DAYS = 21          # janela de detecção (busca no Solr)
DISPLAY_DAYS = 7         # janela exibida normalmente na página
SEEN_MAX_AGE_DAYS = 45   # por quanto tempo um acórdão fica na memória

WEEKDAY_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
MONTH_PT = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _to_date(s: str | None) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def fetch_window(end: datetime.date, days: int) -> list[dict]:
    start = end - datetime.timedelta(days=days)
    params = {
        "q": "*:*",
        "fq": (f"dt_publicacao_tdt:[{start:%Y-%m-%d}T00:00:00Z "
               f"TO {end:%Y-%m-%d}T23:59:59.999Z]"),
        "wt": "json",
        "rows": 10000,
        "fl": "id,numero_processo_s,numero_decisao_s,ementa_s,nome_relator_s,"
              "camara_s,turma_s,secao_s,nome_arquivo_pdf_s,dt_publicacao_tdt",
        "sort": "dt_publicacao_tdt desc,numero_processo_s asc",
    }
    r = requests.get(SOLR_URL, params=params, timeout=120)
    r.raise_for_status()
    return r.json()["response"]["docs"]


def fetch_latest_pub_date() -> datetime.date | None:
    """Data de publicação mais recente existente no índice (ignora datas
    futuras anômalas que existem na base do CARF)."""
    params = {
        "q": "*:*",
        "fq": "dt_publicacao_tdt:[* TO NOW]",
        "wt": "json",
        "rows": 1,
        "fl": "dt_publicacao_tdt",
        "sort": "dt_publicacao_tdt desc",
    }
    r = requests.get(SOLR_URL, params=params, timeout=60)
    r.raise_for_status()
    docs = r.json()["response"]["docs"]
    return _to_date(docs[0].get("dt_publicacao_tdt")) if docs else None


def load_seen() -> dict[str, str]:
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_seen(seen: dict[str, str], today: datetime.date) -> None:
    cutoff = today - datetime.timedelta(days=SEEN_MAX_AGE_DAYS)
    trimmed = {i: d for i, d in seen.items()
               if (_to_date(d) is None or _to_date(d) >= cutoff)}
    SEEN_FILE.write_text(
        json.dumps(trimmed, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8",
    )


def fmt_date_long(d: datetime.date) -> str:
    return f"{WEEKDAY_PT[d.weekday()]}, {d.day} de {MONTH_PT[d.month]} de {d.year}"


def render_item(doc: dict, is_new: bool) -> str:
    e = html.escape
    decisao = e(doc.get("numero_decisao_s", "?"))
    processo = e(doc.get("numero_processo_s", "?"))
    ementa = e(doc.get("ementa_s", "(sem ementa)"))
    relator = e(doc.get("nome_relator_s", "?"))
    contexto = " · ".join(filter(None, [
        doc.get("secao_s", ""), doc.get("camara_s", ""), doc.get("turma_s", ""),
    ]))
    pdf_name = doc.get("nome_arquivo_pdf_s")
    pdf_link = (f' · <a href="{e(PDF_BASE + "/" + pdf_name)}" target="_blank">PDF</a>'
                if pdf_name else "")
    badge = '<span class="novo">NOVO</span> ' if is_new else ""
    cls = "acordao novo-card" if is_new else "acordao"
    return f"""<article class="{cls}">
  <header>
    <h3>{badge}Acórdão {decisao}{pdf_link}</h3>
    <div class="meta">
      Processo {processo}<br>
      Relator: {relator}<br>
      {e(contexto)}
    </div>
  </header>
  <div class="ementa">{ementa}</div>
</article>"""


def render_html(display: list[tuple[dict, datetime.date]],
                new_ids: set[str], now: datetime.datetime,
                latest: datetime.date | None) -> str:
    groups: dict[datetime.date, list[dict]] = {}
    for doc, d in display:
        groups.setdefault(d, []).append(doc)

    sections = []
    for d in sorted(groups, reverse=True):
        items = "\n".join(render_item(doc, doc.get("id") in new_ids)
                          for doc in groups[d])
        sections.append(
            f'<h2 class="data">{fmt_date_long(d)} '
            f'<span class="qtd">({len(groups[d])})</span></h2>\n{items}'
        )
    body = ("\n".join(sections) if sections
            else '<p class="empty">Nenhum acórdão recente disponível no índice.</p>')

    n = len(new_ids)
    if n:
        aviso = (f'<p class="novidade">🔔 <b>{n}</b> acórdão(s) novo(s) nesta '
                 f'atualização (marcados com <span class="novo">NOVO</span>).</p>')
    else:
        aviso = ('<p class="novidade sem">Nenhum acórdão novo desde a '
                 'última atualização.</p>')

    now_str = now.strftime("%d/%m/%Y às %H:%M")
    if latest:
        latest_str = f"{latest:%d/%m/%Y} ({WEEKDAY_PT[latest.weekday()]})"
    else:
        latest_str = "indisponível"
    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Acórdãos CARF</title>
  <style>
    body {{ font-family: -apple-system, system-ui, Segoe UI, sans-serif;
            max-width: 900px; margin: 2em auto; padding: 0 1em;
            color: #222; line-height: 1.5; }}
    h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3em; margin-bottom: 0.3em; }}
    h1 small {{ display: block; font-size: 0.5em; color: #666;
                font-weight: normal; margin-top: 0.4em; }}
    .novidade {{ background: #eef6ff; border: 1px solid #b6d8ff;
                 padding: 0.6em 1em; border-radius: 6px; margin: 1em 0; }}
    .novidade.sem {{ background: #f5f5f5; border-color: #ddd; color: #777; }}
    .novo {{ background: #d73a49; color: #fff; font-size: 0.7em;
             padding: 0.1em 0.5em; border-radius: 4px; font-weight: bold;
             vertical-align: middle; }}
    h2.data {{ margin-top: 1.6em; font-size: 1.15em; color: #333;
               border-bottom: 1px solid #eee; padding-bottom: 0.2em; }}
    h2.data .qtd {{ color: #999; font-weight: normal; font-size: 0.85em; }}
    .empty {{ color: #999; font-style: italic; padding: 2em 0; text-align: center; }}
    .acordao {{ border: 1px solid #ddd; border-radius: 6px;
                padding: 1em 1.2em; margin: 1em 0; background: #fafafa; }}
    .acordao.novo-card {{ border-left: 4px solid #d73a49; background: #fff8f8; }}
    .acordao header {{ margin-bottom: 0.7em; }}
    .acordao h3 {{ margin: 0 0 0.4em 0; font-size: 1.05em; }}
    .acordao .meta {{ color: #555; font-size: 0.9em; }}
    .acordao .ementa {{ white-space: pre-wrap; margin: 0.8em 0 0 0;
                        font-size: 0.95em; color: #333; }}
    a {{ color: #0366d6; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .status {{ background: #f6f8fa; border: 1px solid #e1e4e8; border-radius: 6px;
               padding: 0.7em 1em; margin: 0.8em 0; font-size: 0.92em; color: #444; }}
    .status div {{ margin: 0.15em 0; }}
  </style>
</head>
<body>
  <h1>Acórdãos CARF</h1>
  <div class="status">
    <div>🤖 Robô executou em <b>{now_str}</b> (se for hoje, o robô está funcionando).</div>
    <div>📅 Publicação mais recente disponível no índice do CARF: <b>{latest_str}</b>.</div>
    <div>🪟 A página mostra os últimos {DISPLAY_DAYS} dias de publicação.</div>
  </div>
  {aviso}
  {body}
</body>
</html>"""


def main() -> None:
    today = datetime.date.today()
    if len(sys.argv) > 1:
        today = datetime.date.fromisoformat(sys.argv[1])
    print(f"Data de referência: {today.isoformat()}")

    print(f"Consultando Solr (últimos {QUERY_DAYS} dias de publicação)...")
    docs = fetch_window(today, QUERY_DAYS)
    print(f"Acórdãos na janela de detecção: {len(docs)}")

    first_run = not SEEN_FILE.exists()
    seen = load_seen()
    if first_run:
        new_ids: set[str] = set()
        print("Primeira execução: estabelecendo memória (sem marcar NOVO).")
    else:
        new_ids = {d["id"] for d in docs if d.get("id") and d["id"] not in seen}
    print(f"Novos (não vistos antes): {len(new_ids)}")

    display_cutoff = today - datetime.timedelta(days=DISPLAY_DAYS)
    display: list[tuple[dict, datetime.date]] = []
    for doc in docs:
        d = _to_date(doc.get("dt_publicacao_tdt"))
        if d is None:
            continue
        if d >= display_cutoff or doc.get("id") in new_ids:
            display.append((doc, d))
    display.sort(key=lambda x: x[0].get("numero_processo_s", ""))
    display.sort(key=lambda x: x[1], reverse=True)

    latest = fetch_latest_pub_date()
    print(f"Publicação mais recente no índice do CARF: {latest}")

    now = datetime.datetime.now()
    OUTPUT_FILE.write_text(render_html(display, new_ids, now, latest), encoding="utf-8")
    print(f"HTML salvo: {OUTPUT_FILE} ({len(display)} acórdãos exibidos)")

    for doc in docs:
        i = doc.get("id")
        if i:
            d = _to_date(doc.get("dt_publicacao_tdt"))
            seen[i] = d.isoformat() if d else today.isoformat()
    save_seen(seen, today)
    print(f"Memória atualizada: {len(seen)} acórdãos.")

    if not os.environ.get("CI"):
        webbrowser.open(OUTPUT_FILE.as_uri())
        print("Abrindo no navegador...")


if __name__ == "__main__":
    main()
