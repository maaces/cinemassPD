"""Scraper per cinema che usano il plugin WordPress 'remotefilm'
(riconoscibile dai link '?post_type=remotefilm&p=NNN').

Cinema noti che usano questa piattaforma: Multiastra, Porto Astra
(entrambi a Padova; probabilmente anche Fronte del Porto Padova, ma il
suo robots.txt vieta esplicitamente l'accesso automatico, quindi questo
scraper NON va puntato li' senza il permesso del gestore del sito).

Struttura tipica della pagina:
  1) Una sezione "in programmazione" con locandina + titolo + trama +
     link "Scheda completa" per ogni film.
  2) Una sezione "Orari di programmazione" con un selettore di giorni
     (tab) e, per ciascun giorno, l'elenco di film con i relativi orari.

Il selettore di giorni e' quasi certamente realizzato con tab in stile
Bootstrap (link con href="#id-tab" + div con quello stesso id). Se la
struttura reale differisse, lo scraper ripiega su un'estrazione "piatta"
senza distinzione di giorno (le proiezioni vengono comunque raccolte, ma
segnalate come "data da verificare").
"""
import datetime
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from models import Movie, Showtime
from utils import get_session, polite_get

DETAIL_LINK_RE = re.compile(r"/film/[^/?]+/?$")
ORARI_LINK_RE = re.compile(r"post_type=remotefilm&p=\d+")
TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})")
DATE_TAB_RE = re.compile(r"\b(\d{2})/(\d{2})\b")
PRICE_RE = re.compile(r"([\d]+[,.]\d{2})\s*€")
JS_URL_RE = re.compile(r'"(https?://[^"]+)"')


def _guess_year(day: int, month: int, today: datetime.date) -> int:
    """I tab mostrano solo giorno/mese: deduciamo l'anno assumendo che la
    data sia oggi o nel prossimo futuro (mai piu' di ~7 mesi indietro)."""
    year = today.year
    try:
        candidate = datetime.date(year, month, day)
    except ValueError:
        return year
    if (today - candidate).days > 210:
        return year + 1
    return year


def _extract_listing(soup: BeautifulSoup) -> Dict[str, Dict]:
    """Sezione con locandine/trame: ritorna {chiave_normalizzata: info}."""
    from models import Movie as _M
    listing = {}
    for a in soup.find_all("a", string=re.compile("Scheda completa", re.I)):
        href = a.get("href", "")
        # Risale al blocco (li/div) che contiene anche titolo e immagine
        block = a.find_parent(["li", "div"]) or a.parent
        if block is None:
            continue
        heading = block.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        img = block.find("img")
        if not heading:
            continue
        title = heading.get_text(strip=True)
        key = _M(title=title).norm_key()
        listing[key] = {
            "title": title,
            "detail_url": href,
            "poster_url": img.get("src") if img else None,
        }
    return listing


def _find_day_tabs(soup: BeautifulSoup, today: datetime.date):
    """Cerca link tipo <a href="#qualcosa">26/09 ... Sabato</a> e i relativi
    contenitori. Ritorna una lista di (contenitore_tag, "YYYY-MM-DD")."""
    tabs = []
    for a in soup.find_all("a", href=re.compile(r"^#")):
        label = a.get_text(" ", strip=True)
        m = DATE_TAB_RE.search(label)
        if not m:
            continue
        gg, mm = int(m.group(1)), int(m.group(2))
        anchor_id = a["href"].lstrip("#")
        container = soup.find(id=anchor_id)
        if container is None:
            continue
        year = _guess_year(gg, mm, today)
        tabs.append((container, f"{year:04d}-{mm:02d}-{gg:02d}"))
    return tabs


def _parse_schedule_block(container, cinema_name: str, date_str: Optional[str],
                           date_uncertain: bool, listing: Dict[str, Dict],
                           movies: Dict[str, Movie]):
    current_movie = None
    for el in container.find_all(["a", "p", "div", "li", "span"]):
        link = el if el.name == "a" else el.find("a", recursive=False)
        href = (link.get("href") if link else None) or ""

        if link and ORARI_LINK_RE.search(href):
            title = link.get_text(strip=True)
            if not title:
                continue
            key = Movie(title=title).norm_key()
            info = listing.get(key)
            if key not in movies:
                movies[key] = Movie(
                    title=(info["title"] if info else title.title()),
                    detail_url=(info["detail_url"] if info else None),
                    poster_url=(info["poster_url"] if info else None),
                )
            current_movie = movies[key]
            continue

        if el.name != "a" and current_movie is not None:
            text = el.get_text(" ", strip=True)
            # Le sotto-liste con gli orari sono <li> o <p> con più <a> dentro,
            # ognuno con testo tipo "15.15" oppure "20.00Ingresso 5,50 €"
            for time_link in el.find_all("a", recursive=False):
                label = time_link.get_text(" ", strip=True)
                tmatch = TIME_RE.match(label)
                if not tmatch:
                    continue
                thref = time_link.get("href", "")
                booking_url = thref if thref.startswith("http") else None
                if not booking_url:
                    js_match = JS_URL_RE.search(thref)
                    if js_match:
                        booking_url = js_match.group(1)
                price_match = PRICE_RE.search(label)
                current_movie.showtimes.append(Showtime(
                    date=date_str or "data-da-verificare",
                    time=f"{int(tmatch.group(1)):02d}:{tmatch.group(2)}",
                    cinema=cinema_name,
                    price=(price_match.group(1) + " €") if price_match else None,
                    note=label[tmatch.end():].split("Ingresso")[0].strip() or None,
                    booking_url=booking_url,
                    date_uncertain=date_uncertain,
                ))


def scrape(base_url: str, cinema_name: str) -> List[Movie]:
    session = get_session()
    resp = polite_get(session, base_url)
    soup = BeautifulSoup(resp.text, "html.parser")
    today = datetime.date.today()

    listing = _extract_listing(soup)
    movies: Dict[str, Movie] = {}

    tabs = _find_day_tabs(soup, today)
    if tabs:
        for container, date_str in tabs:
            _parse_schedule_block(container, cinema_name, date_str,
                                   date_uncertain=False, listing=listing, movies=movies)
    else:
        # Fallback: nessun tab riconosciuto, prendiamo tutta la pagina come
        # un unico blocco e segnaliamo che la data non e' affidabile.
        _parse_schedule_block(soup, cinema_name, None,
                               date_uncertain=True, listing=listing, movies=movies)

    return list(movies.values())
