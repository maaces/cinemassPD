"""Scraper per Cinema Rex (Padova) - https://www.cinemarex.it/

Calibrato sull'HTML reale della pagina "Programmazione" (ottobre 2026).

Come funziona il sito: la pagina e' quasi vuota, e uno script inline scarica
TUTTA la programmazione (settimana + "Prossimamente") da un unico endpoint
JSON:  https://www.cinemarex.it/pages/rexJsonCompact.php
e con quello costruisce i tab dei giorni e le schede dei film.

Per questo lo scraper ha due strade:
  1) PRINCIPALE: legge direttamente il JSON con una semplice richiesta HTTP
     (niente browser, veloce, preciso: data e ora sono nel campo "inizio").
  2) FALLBACK: se il JSON non e' raggiungibile o ha cambiato forma, apre la
     pagina con Playwright e legge le schede gia' renderizzate dal sito
     (div.movie dentro i tab-pane dei giorni).

Schema JSON (ricostruito dal codice JavaScript della pagina):
  { "titoli": [ { "titolo", "autore", "durata", "descrizione", "locandina",
                  "categoria_film"/"categoria_musica"/"categoria_teatro"/
                  "categoria_teatroragazzi"/"categoria_kids"/"categoria_cineforum": "y",
                  "eventi": [ { "inizio", "fl_film_vos": "y", "cast": "y",
                                "valore_prezzo_1", "valore_prezzo_2",
                                "id_cinebot", "locandina_special" } ] } ] }

NOTA: a differenza di quanto avviene per The Space, qui lo schema JSON non
l'ho potuto provare dal vivo (il mio ambiente non raggiunge il sito): l'ho
ricostruito dallo script della pagina e provato su dati equivalenti. Se
l'endpoint dovesse rispondere in modo diverso, scatta in automatico il
fallback sul DOM (che e' invece verificato sull'HTML reale) e il report di
diagnostica lo segnala.
"""
import datetime as dt
import json
import re
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import Movie, Showtime
from utils import DEBUG_PAGES, get_session

ROME = ZoneInfo("Europe/Rome")
JSON_URL = "https://www.cinemarex.it/pages/rexJsonCompact.php"
SITE_URL = "https://www.cinemarex.it/"
TICKET_URL = "https://ticket.cinebot.it/rex/titolo/{}"
EVENT_URL = "https://www.cinemarex.it/evento?eventName={}"

# Il Rex programma anche teatro, concerti e spettacoli per ragazzi. Questa e'
# una pagina di FILM: di default teniamo solo le categorie qui sotto (i titoli
# teatrali darebbero abbinamenti sbagliati su TMDB). Per includere tutto,
# aggiungi "Teatro", "Musica", "Teatro ragazzi".
INCLUDE_CATEGORIES = {"Film"}

# Etichette ("ribbon") del sito che vale la pena mostrare come nota.
# Il resto (Teatro, Concerto, Famiglia, "Gratis tesserati NOI"...) e' ignorato.
RIBBON_TO_NOTE = {
    "In lingua originale": "V.O.S.",
    "Regista in sala": "Regista in sala",
    "Ingresso libero": "Ingresso libero",
    "Cinema in festa": "Cinema in festa",
    "Cineforum": "Cineforum",
    "Pomeriggio al Rex": "Pomeriggio al Rex",
}
PRICE_FLAGS = {  # stesso dizionario dello script del sito
    "0_0": "Ingresso libero",
    "3.5_0": "Biglietto 3€",
    "4_0": "Cinema in festa",
    "4.5_0": "Biglietto 4€",
    "5.5_0": "Biglietto 5€",
}
CATEGORY_KEYS = [  # stesso ordine di priorita' dello script del sito
    ("categoria_film", "Film"),
    ("categoria_musica", "Musica"),
    ("categoria_teatroragazzi", "Teatro ragazzi"),
    ("categoria_teatro", "Teatro"),
]

WEEKDAYS_IT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
DAY_LABEL_RE = re.compile(r"([a-zà-ù]{3})\w*\.?\s+(\d{1,2})/(\d{1,2})", re.I)
TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})")


# --------------------------------------------------------------------------
# utilita'
# --------------------------------------------------------------------------
def _slugify(text: str) -> str:
    """Identica a slugify() dello script del sito: serve per il link scheda."""
    return re.sub(r"\W", "_", text.lower())


def _notes(flags: List[str]) -> Optional[str]:
    notes = []
    for f in flags:
        n = RIBBON_TO_NOTE.get(f)
        if n and n not in notes:
            notes.append(n)
    return " · ".join(notes) or None


def _parse_inizio(value) -> Optional[dt.datetime]:
    """'inizio' puo' essere ISO ('2026-10-03T21:00:00'), con 'Z'/offset, o
    'YYYY-MM-DD HH:MM:SS'. Se non porta il fuso e' ora italiana."""
    if value is None:
        return None
    if isinstance(value, (int, float)):  # epoch (s o ms)
        v = value / 1000 if value > 1e11 else value
        return dt.datetime.fromtimestamp(v, tz=ROME)
    s = str(value).strip().replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d.astimezone(ROME) if d.tzinfo else d.replace(tzinfo=ROME)


def _infer_date(weekday: str, day: int, month: int, today: dt.date) -> Optional[dt.date]:
    """Le etichette del sito sono 'sab 03/10' (senza anno). Scelgo l'anno
    per cui il giorno della settimana COMBACIA davvero: e' molto piu' sicuro
    di indovinare 'quest'anno o il prossimo'."""
    wd = weekday.lower()[:3]
    for year in (today.year, today.year + 1, today.year - 1):
        try:
            d = dt.date(year, month, day)
        except ValueError:
            continue
        if WEEKDAYS_IT[d.weekday()] == wd and (d - today).days > -60:
            return d
    return None


def _merge(movies: Dict[str, Movie], movie: Movie, showtime: Showtime) -> None:
    key = movie.norm_key()
    if key not in movies:
        movies[key] = movie
    else:
        old = movies[key]
        old.director = old.director or movie.director
        old.duration_min = old.duration_min or movie.duration_min
        old.detail_url = old.detail_url or movie.detail_url
    movies[key].showtimes.append(showtime)


# --------------------------------------------------------------------------
# strada 1: JSON
# --------------------------------------------------------------------------
def parse_json(data: dict, cinema_name: str) -> List[Movie]:
    titoli = data.get("titoli")
    if not isinstance(titoli, list):
        raise ValueError("JSON senza la lista 'titoli' (formato cambiato?)")
    movies: Dict[str, Movie] = {}
    for ev in titoli:
        title = (ev.get("titolo") or "").strip()
        if not title:
            continue
        category = next((label for k, label in CATEGORY_KEYS if ev.get(k) == "y"), None)
        if INCLUDE_CATEGORIES and category not in INCLUDE_CATEGORIES:
            continue
        director = (ev.get("autore") or "").strip() or None
        try:
            duration = int(str(ev.get("durata")).strip()) if ev.get("durata") else None
        except ValueError:
            duration = None

        for item in ev.get("eventi") or []:
            start = _parse_inizio(item.get("inizio"))
            if not start:
                continue
            flags = []
            if item.get("fl_film_vos") == "y":
                flags.append("In lingua originale")
            if item.get("cast") == "y":
                flags.append("Regista in sala")
            price_label = PRICE_FLAGS.get(f"{item.get('valore_prezzo_1')}_{item.get('valore_prezzo_2')}")
            if price_label:
                flags.append(price_label)
            if ev.get("categoria_cineforum") == "y":
                flags.append("Cineforum")
            if start.weekday() == 3 and start.hour == 16:  # "gio" alle 16
                flags.append("Pomeriggio al Rex")

            note = _notes(flags)
            price = next((f for f in flags if f.startswith("Biglietto")), None)  # "Biglietto 4€" -> prezzo
            movie = Movie(
                title=title,
                director=director,
                duration_min=duration,
                detail_url=EVENT_URL.format(_slugify(title)),
            )
            st = Showtime(
                date=start.strftime("%Y-%m-%d"),
                time=start.strftime("%H:%M"),
                cinema=cinema_name,
                price=price.replace("Biglietto ", "") if price else None,
                note=note,
                booking_url=TICKET_URL.format(item["id_cinebot"]) if item.get("id_cinebot") else None,
            )
            _merge(movies, movie, st)
    return list(movies.values())


def _fetch_json(cinema_name: str) -> List[Movie]:
    session = get_session()
    session.headers["Accept"] = "application/json"
    session.headers["Referer"] = SITE_URL
    resp = session.get(JSON_URL, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    # nel dump di diagnostica tolgo le locandine (base64 enormi)
    slim = {"titoli": [{k: v for k, v in t.items() if k != "locandina"} for t in data.get("titoli", [])]}
    for t in slim["titoli"]:
        for e in t.get("eventi", []):
            e.pop("locandina_special", None)
    DEBUG_PAGES[JSON_URL] = "<pre>" + json.dumps(slim, ensure_ascii=False, indent=1) + "</pre>"
    return parse_json(data, cinema_name)


# --------------------------------------------------------------------------
# strada 2: DOM renderizzato (verificato sull'HTML reale)
# --------------------------------------------------------------------------
def parse_rendered_html(html: str, cinema_name: str, today: Optional[dt.date] = None) -> List[Movie]:
    """Legge le schede gia' renderizzate: ogni <div class="movie"> dentro un
    tab-pane contiene titolo, giorno ('sab 03/10'), ora, ribbon, link biglietti."""
    today = today or dt.datetime.now(ROME).date()
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("#day-content div.movie") or soup.select("div.movie")
    if not cards:
        raise ValueError("nessuna scheda div.movie nella pagina")

    movies: Dict[str, Movie] = {}
    for card in cards:
        title_el = card.select_one(".card-title")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)

        info = {}
        for li in card.select("ul.event-general-info li"):
            label = li.find("b")
            value = li.find("span")
            if label and value:
                info[label.get_text(strip=True)] = value.get_text(" ", strip=True)
        category = info.get("Categoria")
        if INCLUDE_CATEGORIES and category not in INCLUDE_CATEGORIES:
            continue

        # data: etichetta nascosta '.day' oppure id del tab-pane ('sab_03_10')
        day_el = card.select_one(".day")
        label = day_el.get_text(" ", strip=True) if day_el else ""
        m = DAY_LABEL_RE.search(label)
        if not m:
            pane = card.find_parent(class_="tab-pane")
            m = DAY_LABEL_RE.search((pane.get("id", "") if pane else "").replace("_", " ", 1).replace("_", "/"))
        hour_el = card.select_one(".hour span")
        tm = TIME_RE.search(hour_el.get_text(" ", strip=True)) if hour_el else None
        if not m or not tm:
            continue
        date = _infer_date(m.group(1), int(m.group(2)), int(m.group(3)), today)
        if not date:
            continue

        ribbons = [r.get_text(" ", strip=True) for r in card.select(".ribbon-card")]
        price = next((r.replace("Biglietto ", "") for r in ribbons if r.startswith("Biglietto")), None)
        buy = card.select_one("a.btn-card")
        link = card.select_one("a.poster")
        dur = re.search(r"\d+", info.get("Durata", ""))

        movie = Movie(
            title=title,
            director=(info.get("Regia") or None),
            duration_min=int(dur.group()) if dur else None,
            detail_url=link.get("href") if link else None,
        )
        st = Showtime(
            date=date.strftime("%Y-%m-%d"),
            time=f"{int(tm.group(1)):02d}:{tm.group(2)}",
            cinema=cinema_name,
            price=price,
            note=_notes(ribbons),
            booking_url=buy.get("href") if buy and "cinebot" in (buy.get("href") or "") else None,
        )
        _merge(movies, movie, st)
    return list(movies.values())


def _render_page(url: str) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(locale="it-IT", timezone_id="Europe/Rome",
                                      viewport={"width": 1366, "height": 900})
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # le schede compaiono quando lo script ha scaricato il JSON
            page.wait_for_selector("#day-content div.movie", timeout=30000)
            return page.content()
        finally:
            browser.close()


# --------------------------------------------------------------------------
# punto di ingresso
# --------------------------------------------------------------------------
def scrape(url: str, cinema_name: str) -> List[Movie]:
    try:
        movies = _fetch_json(cinema_name)
        if movies:
            return movies
        print(f"   [!] {cinema_name}: JSON valido ma senza film in categoria {sorted(INCLUDE_CATEGORIES)}, provo il DOM")
    except Exception as e:
        print(f"   [!] {cinema_name}: lettura JSON non riuscita ({type(e).__name__}: {e}), provo il browser")

    page_url = url if "cinemarex.it" in url else SITE_URL
    html = _render_page(page_url)
    DEBUG_PAGES[page_url] = html
    return parse_rendered_html(html, cinema_name)
