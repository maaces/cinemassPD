"""Genera docs/index.html: pagina mobile-friendly organizzata per GIORNO e
poi per fasce orarie di MEZZ'ORA (es. "21:30" raggruppa 21:30-21:59). Se
piu' film (o eventi personalizzati) cadono nella stessa fascia, vengono
mostrati affiancati nella stessa riga (una griglia che va a capo se non
entrano tutti). Ogni card mostra comunque il proprio orario esatto, e le
card dentro una fascia sono ordinate per orario crescente. Le fasce senza
nulla dentro non vengono create (nessuna riga vuota).

Genera anche docs/ics/*.ics (un file per proiezione/evento) e
docs/data.json (dati grezzi, utile in futuro per un display ESP32).
"""
import datetime as dt
import html
import json
import os
import re
from collections import defaultdict
from typing import List, Optional

from calendar_links import google_calendar_link, ics_content
from custom_events import CustomEvent
from models import Movie, Showtime

WEEKDAYS_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
MONTHS_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
             "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-") or "item"


def _esc(text) -> str:
    return html.escape(str(text)) if text else ""


def _format_date_it(date_str: str) -> str:
    try:
        y, mo, d = (int(x) for x in date_str.split("-"))
        wd = WEEKDAYS_IT[dt.date(y, mo, d).weekday()]
        return f"{wd} {d} {MONTHS_IT[mo - 1]}"
    except (ValueError, AttributeError):
        return date_str


def _half_hour_bucket(time_str: Optional[str]) -> Optional[str]:
    """'21:35' -> '21:30', '21:05' -> '21:00'. None se l'orario non e' valido."""
    if not time_str:
        return None
    try:
        h, m = (int(x) for x in time_str.split(":"))
        return f"{h:02d}:{'30' if m >= 30 else '00'}"
    except ValueError:
        return None


def _write_ics(movie: Movie, showtime: Showtime, ics_dir: str, base_name: str) -> Optional[str]:
    content = ics_content(movie, showtime)
    if not content:
        return None
    fname = f"{base_name}.ics"
    with open(os.path.join(ics_dir, fname), "w", encoding="utf-8") as f:
        f.write(content)
    return f"ics/{fname}"


def _movie_card_html(m: Movie, st: Showtime, ics_dir: str, idx: int) -> str:
    gcal = google_calendar_link(m, st)
    ics_link = _write_ics(m, st, ics_dir, f"{_slug(m.title)}-{st.date}-{st.time.replace(':', '')}-{idx}")

    poster_html = (f'<img class="poster" src="{_esc(m.poster_url)}" alt="" loading="lazy">'
                   if m.poster_url else '<div class="poster poster-placeholder">🎬</div>')
    director_html = f'<div class="director">Regia: {_esc(m.director)}</div>' if m.director else ""
    duration_html = f'{m.duration_min} min' if m.duration_min else ""
    price_note = " · ".join(x for x in [st.price, st.note] if x)

    links = []
    if m.tmdb_url:
        links.append(f'<a href="{_esc(m.tmdb_url)}" target="_blank" rel="noopener">🎬 TMDB</a>')
    elif m.detail_url:
        links.append(f'<a href="{_esc(m.detail_url)}" target="_blank" rel="noopener">ℹ️ Scheda</a>')
    if m.trailer_url:
        links.append(f'<a href="{_esc(m.trailer_url)}" target="_blank" rel="noopener">▶️ Trailer</a>')
    elif m.trailer_search_url:
        links.append(f'<a href="{_esc(m.trailer_search_url)}" target="_blank" rel="noopener">🔍 Cerca trailer</a>')
    if m.letterboxd_url:
        links.append(f'<a href="{_esc(m.letterboxd_url)}" target="_blank" rel="noopener">🔍 Letterboxd</a>')

    buttons = []
    if gcal:
        buttons.append(f'<a class="btn" href="{_esc(gcal)}" target="_blank" rel="noopener">📅 Calendar</a>')
    if ics_link:
        buttons.append(f'<a class="btn btn-alt" href="{_esc(ics_link)}">⬇️ .ics</a>')

    return f"""
      <div class="mini-card">
        <div class="mc-head">
          {poster_html}
          <div class="mc-title">
            <div class="mc-time">{_esc(st.time)}</div>
            <div class="mc-name">{_esc(m.title)}</div>
            {director_html}
            <div class="meta">{_esc(duration_html)}</div>
          </div>
        </div>
        <div class="mc-cinema">📍 {_esc(st.cinema)}{(' · ' + _esc(price_note)) if price_note else ''}</div>
        <div class="links">{' · '.join(links)}</div>
        <div class="mc-actions">{' '.join(buttons)}</div>
      </div>"""


def _custom_card_html(ce: CustomEvent, ics_dir: str, idx: int) -> str:
    gcal_link = None
    ics_link = None
    if ce.date and ce.time:
        fake_movie = Movie(title=ce.title, duration_min=120, detail_url=ce.source_url)
        fake_showtime = Showtime(date=ce.date, time=ce.time, cinema="Evento personale")
        gcal_link = google_calendar_link(fake_movie, fake_showtime)
        ics_link = _write_ics(fake_movie, fake_showtime, ics_dir, f"evento-{_slug(ce.title)}-{idx}")

    time_html = f'<div class="mc-time">{_esc(ce.time)}</div>' if ce.time else ""
    photo_html = f'<img class="custom-photo" src="{_esc(ce.photo_url)}" alt="" loading="lazy">' if ce.photo_url else ""
    text_html = f'<div class="custom-text">{_esc(ce.text)}</div>' if ce.text else ""
    buttons = []
    if gcal_link:
        buttons.append(f'<a class="btn" href="{_esc(gcal_link)}" target="_blank" rel="noopener">📅 Calendar</a>')
    if ics_link:
        buttons.append(f'<a class="btn btn-alt" href="{_esc(ics_link)}">⬇️ .ics</a>')

    return f"""
      <div class="mini-card custom-card">
        {time_html}
        {photo_html}
        <div class="mc-name">📌 {_esc(ce.title)}</div>
        {text_html}
        <div class="mc-actions">{' '.join(buttons)}</div>
      </div>"""


def render(movies: List[Movie], custom_events: List[CustomEvent], out_dir: str, cinemas_note: str = "") -> None:
    ics_dir = os.path.join(out_dir, "ics")
    os.makedirs(ics_dir, exist_ok=True)

    # timeline[data][fascia_mezz'ora] = lista di (orario_esatto, html_card)
    timeline = defaultdict(lambda: defaultdict(list))
    uncertain_html = []
    json_movies, json_events = [], []
    counter = 0

    for m in movies:
        json_showtimes = []
        for st in m.showtimes:
            json_showtimes.append({"date": st.date, "time": st.time, "cinema": st.cinema,
                                    "price": st.price, "note": st.note, "date_uncertain": st.date_uncertain})
            counter += 1
            card = _movie_card_html(m, st, ics_dir, counter)
            bucket = _half_hour_bucket(st.time)
            if st.date_uncertain or not st.date or st.date == "data-da-verificare" or not bucket:
                uncertain_html.append(card)
            else:
                timeline[st.date][bucket].append((st.time, card))
        if m.showtimes:
            json_movies.append({
                "title": m.title, "director": m.director, "duration_min": m.duration_min,
                "poster_url": m.poster_url, "trailer_url": m.trailer_url or m.trailer_search_url,
                "letterboxd_url": m.letterboxd_url, "tmdb_url": m.tmdb_url, "detail_url": m.detail_url,
                "showtimes": json_showtimes,
            })

    for ce in custom_events:
        counter += 1
        card = _custom_card_html(ce, ics_dir, counter)
        bucket = _half_hour_bucket(ce.time)
        if ce.date and bucket:
            timeline[ce.date][bucket].append((ce.time, card))
        else:
            uncertain_html.append(card)
        json_events.append({"title": ce.title, "text": ce.text, "date": ce.date, "time": ce.time,
                             "photo_url": ce.photo_url, "source_url": ce.source_url})

    sections = []
    for date_str in sorted(timeline.keys()):
        rows = []
        for bucket in sorted(timeline[date_str].keys()):
            entries = sorted(timeline[date_str][bucket], key=lambda pair: pair[0])
            items = "".join(html_fragment for _, html_fragment in entries)
            rows.append(f"""
          <div class="time-row">
            <div class="time-label">{_esc(bucket)}</div>
            <div class="time-items">{items}</div>
          </div>""")
        sections.append(f"""
        <section class="day">
          <h2>{_esc(_format_date_it(date_str))}</h2>
          {''.join(rows)}
        </section>""")

    if uncertain_html:
        sections.append(f"""
        <section class="day">
          <h2>⚠️ Orari da verificare</h2>
          <div class="time-row"><div class="time-items">{''.join(uncertain_html)}</div></div>
        </section>""")

    now = dt.datetime.now().strftime("%d/%m/%Y alle %H:%M")
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
  .day {{ margin: 22px 0; }}
  .day h2 {{ font-size: 1.05rem; border-bottom: 2px solid var(--accent); padding-bottom: 4px; }}
  .time-row {{ display: flex; gap: 10px; margin: 14px 0; align-items: flex-start; }}
  .time-label {{ flex: 0 0 48px; font-weight: 700; font-size: 0.85rem; padding-top: 10px; color: var(--muted); }}
  .time-items {{ display: flex; flex-wrap: wrap; gap: 10px; flex: 1; }}
  .mini-card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 10px; flex: 1 1 190px; max-width: 240px;
  }}
  .mc-head {{ display: flex; gap: 8px; }}
  .poster {{ width: 52px; height: 76px; object-fit: cover; border-radius: 6px; flex-shrink: 0; }}
  .poster-placeholder {{ display: flex; align-items: center; justify-content: center; background: var(--border); font-size: 1.4rem; }}
  .mc-time {{ font-weight: 700; font-size: 0.85rem; color: var(--accent); }}
  .mc-name {{ font-weight: 600; font-size: 0.92rem; line-height: 1.2; }}
  .director {{ font-size: 0.78rem; color: var(--muted); }}
  .meta {{ font-size: 0.75rem; color: var(--muted); }}
  .mc-cinema {{ font-size: 0.78rem; margin-top: 6px; color: var(--muted); }}
  .links {{ font-size: 0.75rem; margin-top: 4px; }}
  .links a {{ color: var(--accent); text-decoration: none; }}
  .mc-actions {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }}
  .btn {{ font-size: 0.72rem; padding: 4px 8px; border-radius: 6px; background: var(--accent); color: #fff; text-decoration: none; white-space: nowrap; }}
  .btn-alt {{ background: transparent; border: 1px solid var(--accent); color: var(--accent); }}
  .custom-card {{ border-color: var(--accent); }}
  .custom-photo {{ width: 100%; max-height: 160px; object-fit: cover; border-radius: 8px; margin: 4px 0 6px; }}
  .custom-text {{ font-size: 0.8rem; margin-top: 4px; white-space: pre-line; }}
  footer {{ text-align: center; color: var(--muted); font-size: 0.75rem; padding: 24px 0 40px; }}
</style>
</head>
<body>
<header>
  <h1>🎬 Cinema in programmazione</h1>
  <p>Aggiornato il {now}. {_esc(cinemas_note)}</p>
</header>
{''.join(sections) if sections else '<p>Nessun film trovato in questo aggiornamento.</p>'}
<footer>Generato automaticamente · dati raccolti dai siti dei singoli cinema</footer>
</body>
</html>"""

    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_doc)

    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": dt.datetime.now().isoformat(), "movies": json_movies,
                   "custom_events": json_events}, f, ensure_ascii=False, indent=2)
