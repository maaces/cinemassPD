"""Genera docs/index.html (pagina mobile-friendly con la programmazione),
docs/ics/*.ics (un file per ogni proiezione) e docs/data.json (dati grezzi,
utile in futuro per progetti come un display ESP32)."""
import datetime as dt
import html
import json
import os
import re
from typing import List

from calendar_links import google_calendar_link, ics_content
from models import Movie


def _slug(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text or "film"


def _esc(text) -> str:
    return html.escape(str(text)) if text else ""


def render(movies: List[Movie], out_dir: str, cinemas_note: str = "") -> None:
    ics_dir = os.path.join(out_dir, "ics")
    os.makedirs(ics_dir, exist_ok=True)

    movies_sorted = sorted(movies, key=lambda m: m.title.lower())
    now = dt.datetime.now().strftime("%d/%m/%Y alle %H:%M")

    cards = []
    json_data = []

    for m in movies_sorted:
        if not m.showtimes:
            continue

        showtime_rows = []
        json_showtimes = []
        for i, st in enumerate(m.showtimes):
            gcal = google_calendar_link(m, st)
            ics = ics_content(m, st)
            ics_link = ""
            if ics:
                fname = f"{_slug(m.title)}-{st.date}-{st.time.replace(':', '')}-{i}.ics"
                with open(os.path.join(ics_dir, fname), "w", encoding="utf-8") as f:
                    f.write(ics)
                ics_link = f"ics/{fname}"

            date_label = st.date if st.date != "data-da-verificare" else "data da verificare"
            if st.date_uncertain:
                date_label += " ⚠️"
            extra = f" · {_esc(st.note)}" if st.note else ""
            price = f" · {_esc(st.price)}" if st.price else ""

            buttons = []
            if gcal:
                buttons.append(f'<a class="btn" href="{_esc(gcal)}" target="_blank" rel="noopener">📅 Google Calendar</a>')
            if ics_link:
                buttons.append(f'<a class="btn btn-alt" href="{_esc(ics_link)}">⬇️ .ics</a>')

            showtime_rows.append(f"""
              <div class="showtime">
                <div class="st-info"><strong>{_esc(date_label)}</strong> · {_esc(st.time)} · {_esc(st.cinema)}{price}{extra}</div>
                <div class="st-actions">{' '.join(buttons)}</div>
              </div>""")

            json_showtimes.append({
                "date": st.date, "time": st.time, "cinema": st.cinema,
                "price": st.price, "note": st.note, "date_uncertain": st.date_uncertain,
            })

        poster_html = f'<img class="poster" src="{_esc(m.poster_url)}" alt="" loading="lazy">' if m.poster_url else '<div class="poster poster-placeholder">🎬</div>'
        director_html = f'<div class="director">Regia: {_esc(m.director)}</div>' if m.director else ""
        duration_html = f' · {m.duration_min} min' if m.duration_min else ""
        links = []
        if m.trailer_url:
            links.append(f'<a href="{_esc(m.trailer_url)}" target="_blank" rel="noopener">▶️ Trailer</a>')
        if m.letterboxd_url:
            links.append(f'<a href="{_esc(m.letterboxd_url)}" target="_blank" rel="noopener">🎞️ Letterboxd</a>')
        if m.detail_url:
            links.append(f'<a href="{_esc(m.detail_url)}" target="_blank" rel="noopener">ℹ️ Scheda</a>')
        links_html = " · ".join(links)

        cards.append(f"""
        <article class="card">
          <div class="card-head">
            {poster_html}
            <div class="card-title">
              <h2>{_esc(m.title)}</h2>
              {director_html}
              <div class="meta">{duration_html.strip(' ·')}</div>
              <div class="links">{links_html}</div>
            </div>
          </div>
          <div class="showtimes">{''.join(showtime_rows)}</div>
        </article>""")

        json_data.append({
            "title": m.title, "director": m.director, "duration_min": m.duration_min,
            "poster_url": m.poster_url, "trailer_url": m.trailer_url,
            "letterboxd_url": m.letterboxd_url, "detail_url": m.detail_url,
            "showtimes": json_showtimes,
        })

    html_doc = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Cinema in programmazione</title>
<style>
  :root {{
    --bg: #fafafa; --fg: #1a1a1a; --card: #ffffff; --border: #e5e5e5;
    --accent: #2c5f8a; --muted: #6b6b6b;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #14161a; --fg: #f0f0f0; --card: #1e2126; --border: #2c2f36; --accent: #7fb0e0; --muted: #9a9a9a; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--fg);
    font-family: -apple-system, Roboto, Segoe UI, sans-serif;
    padding: env(safe-area-inset-top,0) 12px env(safe-area-inset-bottom,0);
  }}
  header {{ padding: 20px 4px 8px; }}
  header h1 {{ margin: 0 0 4px; font-size: 1.4rem; }}
  header p {{ margin: 0; color: var(--muted); font-size: 0.85rem; }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 12px; margin: 12px 0;
  }}
  .card-head {{ display: flex; gap: 12px; }}
  .poster {{ width: 72px; height: 104px; object-fit: cover; border-radius: 8px; flex-shrink: 0; }}
  .poster-placeholder {{ display: flex; align-items: center; justify-content: center; background: var(--border); font-size: 1.8rem; }}
  .card-title h2 {{ margin: 0 0 2px; font-size: 1.05rem; }}
  .director {{ font-size: 0.85rem; color: var(--muted); }}
  .meta {{ font-size: 0.8rem; color: var(--muted); }}
  .links {{ font-size: 0.8rem; margin-top: 4px; }}
  .links a {{ color: var(--accent); text-decoration: none; }}
  .showtimes {{ margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; }}
  .showtime {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; padding: 5px 0; font-size: 0.85rem; }}
  .st-actions {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .btn {{ font-size: 0.75rem; padding: 4px 8px; border-radius: 6px; background: var(--accent); color: #fff; text-decoration: none; white-space: nowrap; }}
  .btn-alt {{ background: transparent; border: 1px solid var(--accent); color: var(--accent); }}
  footer {{ text-align: center; color: var(--muted); font-size: 0.75rem; padding: 24px 0 40px; }}
</style>
</head>
<body>
<header>
  <h1>🎬 Cinema in programmazione</h1>
  <p>Aggiornato il {now}. {_esc(cinemas_note)}</p>
</header>
{''.join(cards) if cards else '<p>Nessun film trovato in questo aggiornamento.</p>'}
<footer>Generato automaticamente · dati raccolti dai siti dei singoli cinema</footer>
</body>
</html>"""

    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_doc)

    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": dt.datetime.now().isoformat(), "movies": json_data}, f, ensure_ascii=False, indent=2)
