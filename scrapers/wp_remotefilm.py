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
from zoneinfo import ZoneInfo

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


LABEL_RE_1 = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/\d{2,4})?(?:\s+\S+)?$")   # "26/09 Sabato"
LABEL_RE_2 = re.compile(r"^\S+\s+(\d{1,2})/(\d{1,2})(?:/\d{2,4})?$")           # "Sabato 26/09"
_TEXT_DATE_HINT = re.compile(r"\d{1,2}/\d{1,2}")


def _norm_text(el) -> str:
    return " ".join(el.stripped_strings)


def _label_date(el):
    """Se il testo dell'elemento e' una 'etichetta giorno' (es. '26/09 Sabato')
    ritorna (giorno, mese), altrimenti None."""
    text = _norm_text(el)
    if len(text) > 30:
        return None
    m = LABEL_RE_1.match(text) or LABEL_RE_2.match(text)
    if not m:
        return None
    gg, mm = int(m.group(1)), int(m.group(2))
    return (gg, mm) if 1 <= gg <= 31 and 1 <= mm <= 12 else None


def _find_date_labels(soup):
    """Trova gli elementi-etichetta dei giorni. Ritorna lista di (elemento, (gg, mm))
    in ordine di documento, senza ripetere lo stesso elemento."""
    labels, seen_ids = [], set()
    for s in soup.find_all(string=_TEXT_DATE_HINT):
        el = s.parent
        for _ in range(3):  # sale al massimo di 3 livelli cercando il testo completo
            if el is None or el.name in ("body", "html"):
                break
            d = _label_date(el)
            if d:
                if id(el) not in seen_ids:
                    seen_ids.add(id(el))
                    labels.append((el, d))
                break
            el = el.parent
    return labels


def _time_anchors(root):
    return [a for a in root.find_all("a") if TIME_RE.match(a.get_text(" ", strip=True))]


def _ancestor(node, levels):
    for _ in range(levels):
        node = node.parent
        if node is None:
            return None
    return node


def _strategy_attributes(soup, labels, unique_dates):
    """Strategia A: le etichette sono tab (href="#id", data-target, aria-controls...)
    che puntano al contenitore del giorno tramite id."""
    attrs = ("href", "data-target", "data-bs-target", "data-href", "aria-controls", "data-tab", "data-day")
    by_date = {}
    for el, d in labels:
        node = el
        for _ in range(5):
            if node is None:
                break
            for a in attrs:
                v = node.get(a) if hasattr(node, "get") else None
                if isinstance(v, list):
                    v = " ".join(v)
                if v:
                    target = soup.find(id=v.lstrip("#"))
                    if target is not None and _time_anchors(target):
                        by_date.setdefault(d, target)
                        break
            else:
                node = node.parent
                continue
            break
    if all(d in by_date for d in unique_dates):
        return [(by_date[d], d) for d in unique_dates]
    return None


def _partition_levels(anchors, max_depth=15):
    """Per ogni profondita' calcola i gruppi di antenati (in ordine di documento)."""
    for depth in range(1, max_depth + 1):
        groups = []
        seen = set()
        for a in anchors:
            anc = _ancestor(a, depth)
            if anc is None:
                return
            if id(anc) not in seen:
                seen.add(id(anc))
                groups.append(anc)
        if len(groups) < 2:
            return
        yield depth, groups


def _strategy_partition_equal(soup, anchors, unique_dates):
    """Strategia B: i contenitori dei giorni sono fratelli e il loro numero coincide
    con il numero di etichette-giorno trovate (nell'ordine dei tab)."""
    n = len(unique_dates)
    for depth, groups in _partition_levels(anchors):
        if len(groups) == n and len({id(g.parent) for g in groups}) == 1:
            return list(zip(groups, unique_dates))
    return None


def _strategy_partition_labelled(soup, anchors, labels):
    """Strategia C: ogni contenitore-giorno contiene al suo interno la propria
    etichetta (es. un titolo '26/09 Sabato' sopra l'elenco dei film)."""
    for depth, groups in _partition_levels(anchors):
        if len({id(g.parent) for g in groups}) != 1:
            continue
        result = []
        for g in groups:
            inside = [d for el, d in labels if g in el.parents]
            if len(set(inside)) != 1:
                result = None
                break
            result.append((g, inside[0]))
        if result and len({d for _, d in result}) == len(result):
            return result
    return None


def _find_day_tabs(soup: BeautifulSoup, today: datetime.date):
    """Ritorna (lista di (contenitore, 'YYYY-MM-DD'), nome_strategia) oppure ([], None)."""
    labels = _find_date_labels(soup)
    anchors = _time_anchors(soup)
    if not labels or not anchors:
        return [], None

    unique_dates = []
    for _, d in labels:
        if d not in unique_dates:
            unique_dates.append(d)

    for name, result in (
        ("attributi/id", _strategy_attributes(soup, labels, unique_dates)),
        ("contenitori fratelli", _strategy_partition_equal(soup, anchors, unique_dates)),
        ("etichetta dentro il contenitore", _strategy_partition_labelled(soup, anchors, labels)),
    ):
        if result:
            out = []
            for container, (gg, mm) in result:
                year = _guess_year(gg, mm, today)
                out.append((container, f"{year:04d}-{mm:02d}-{gg:02d}"))
            return out, name
    return [], None


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
    today = datetime.datetime.now(ZoneInfo("Europe/Rome")).date()

    listing = _extract_listing(soup)
    movies: Dict[str, Movie] = {}

    tabs, strategy = _find_day_tabs(soup, today)
    print(f"   giorni riconosciuti: {len(tabs)} (strategia: {strategy or 'nessuna -> date da verificare'})")
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
