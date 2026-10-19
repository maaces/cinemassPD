"""Funzioni di utilità condivise da scraper e script principale."""
import re
import time
from typing import Callable, List, Optional

import requests

from models import Movie

# Pagine HTML grezze scaricate durante lo scraping del cinema corrente:
# main.py le salva (ripulite) in docs/debug/ per poter calibrare gli scraper.
DEBUG_PAGES = {}

USER_AGENT = (
    "Mozilla/5.0 (compatible; CinemaScheduleBot/1.0; "
    "uso personale, non commerciale)"
)


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
    })
    return s


def polite_get(session: requests.Session, url: str, delay: float = 1.0, **kwargs) -> requests.Response:
    """GET con timeout e una piccola pausa per non martellare il server."""
    resp = session.get(url, timeout=25, **kwargs)
    resp.raise_for_status()
    DEBUG_PAGES[url] = resp.text
    time.sleep(delay)
    return resp


SMALL_WORDS = {"di", "del", "dei", "della", "delle", "dello", "degli", "da", "dal", "dai",
               "il", "lo", "la", "le", "i", "gli", "un", "una", "e", "ed", "a", "al", "ai",
               "in", "nel", "nei", "nella", "su", "sul", "per", "con", "tra", "fra", "o"}


def nice_title(raw: str) -> str:
    """Alcuni siti (The Space, Esperia) scrivono i titoli TUTTI MAIUSCOLI. Li riporto in maiuscole/
    minuscole normali (così nella pagina si leggono bene e coincidono con
    gli stessi film degli altri cinema). Titoli gia' misti restano intatti."""
    t = " ".join(raw.split())
    if not t.isupper():
        return t
    out = []
    start = True  # inizio titolo o dopo ':' / ' - '
    for w in t.split(" "):
        low = w.lower()
        if any(c.isdigit() for c in w) or (len(w) > 1 and "." in w.strip(".")):
            out.append(w)  # 20MO, S.W.A.T. ecc.: lascio com'e'
        elif low in SMALL_WORDS and not start:
            out.append(low)
        else:
            # maiuscola dopo l'apostrofo (L'Isola) e dopo il trattino (Spider-Man)
            out.append(re.sub(r"(^|['’\-])([^\W\d_])",
                              lambda m: m.group(1) + m.group(2).upper(), low))
        start = w.endswith(":") or w in ("-", "–")
    return " ".join(out)


def title_is_well_cased(t: str) -> bool:
    """True se il titolo ha maiuscole e minuscole e inizia con la maiuscola
    (cioe' non e' TUTTO MAIUSCOLO, tutto minuscolo o 'iniziale minuscola')."""
    letters = [c for c in t if c.isalpha()]
    return bool(letters) and letters[0].isupper() and not t.isupper() and not t.islower()


def tidy_title(raw: str) -> str:
    """Ultima ripulitura del titolo mostrato in pagina: spazi doppi, apostrofi
    tipografici, TUTTO MAIUSCOLO (-> nice_title) e iniziale minuscola."""
    t = " ".join((raw or "").replace("’", "'").replace("‘", "'").split())
    if t.isupper():
        return nice_title(t)
    for i, c in enumerate(t):
        if c.isalpha():
            if c.islower():
                t = t[:i] + c.upper() + t[i + 1:]
            break
    return t


YOUTUBE_ID_RE = re.compile(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})")


def clean_youtube_url(href: str) -> Optional[str]:
    """Alcuni siti generano link YouTube malformati (URL annidati).
    Estrae l'ultimo video id valido e ricostruisce un link pulito."""
    if not href:
        return None
    ids = YOUTUBE_ID_RE.findall(href)
    if ids:
        return f"https://www.youtube.com/watch?v={ids[-1]}"
    return href


def merge_movies(movie_lists: List[List[Movie]], key: Optional[Callable[[Movie], str]] = None) -> List[Movie]:
    """Unisce film con lo stesso titolo (normalizzato) provenienti da cinema
    diversi in un'unica scheda Movie, sommando le proiezioni.
    'key' permette di unire con un altro criterio (es. lo stesso ID TMDB).
    Tra i titoli dei doppioni tiene quello scritto meglio (non TUTTO MAIUSCOLO):
    il Cineplex scrive tutto in maiuscolo, Porto Astra no."""
    key = key or (lambda mv: mv.norm_key())
    merged = {}
    for movies in movie_lists:
        for m in movies:
            k = key(m)
            if k not in merged:
                merged[k] = m
            else:
                existing = merged[k]
                if title_is_well_cased(m.title) and not title_is_well_cased(existing.title):
                    existing.title = m.title
                existing.showtimes.extend(m.showtimes)
                existing.tmdb_url = existing.tmdb_url or m.tmdb_url
                existing.letterboxd_url = existing.letterboxd_url or m.letterboxd_url
                existing.trailer_search_url = existing.trailer_search_url or m.trailer_search_url
                existing.director = existing.director or m.director
                existing.duration_min = existing.duration_min or m.duration_min
                existing.poster_url = existing.poster_url or m.poster_url
                existing.trailer_url = existing.trailer_url or m.trailer_url
                existing.cast = existing.cast or m.cast
                existing.detail_url = existing.detail_url or m.detail_url
    # Elimina le proiezioni identiche (stessa data, ora, cinema, nota) e ordina
    for m in merged.values():
        seen = set()
        unique = []
        for st in m.showtimes:
            key = (st.date, st.time, st.cinema, st.note or "")
            if key in seen:
                continue
            seen.add(key)
            unique.append(st)
        m.showtimes = sorted(unique, key=lambda s: (s.date or "9999", s.time or "99:99"))
    return list(merged.values())


def clean_html_for_dump(html_text: str, max_chars: int = 600_000) -> str:
    """Toglie da un HTML tutto cio' che non serve a capirne la struttura
    (script, stili, svg, commenti, campi nascosti) cosi' il dump resta leggero."""
    from bs4 import BeautifulSoup, Comment
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "svg", "noscript", "link", "meta", "iframe"]):
        tag.decompose()
    for tag in soup.find_all("input", attrs={"type": "hidden"}):
        tag.decompose()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for tag in soup.find_all(True):
        for attr in ("style", "srcset", "sizes", "data-srcset"):
            if attr in tag.attrs:
                del tag.attrs[attr]
    out = re.sub(r"\n\s*\n+", "\n", soup.prettify())
    return out[:max_chars]
