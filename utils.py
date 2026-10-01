"""Funzioni di utilità condivise da scraper e script principale."""
import re
import time
from typing import List, Optional

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


def merge_movies(movie_lists: List[List[Movie]]) -> List[Movie]:
    """Unisce film con lo stesso titolo (normalizzato) provenienti da cinema
    diversi in un'unica scheda Movie, sommando le proiezioni."""
    merged = {}
    for movies in movie_lists:
        for m in movies:
            k = m.norm_key()
            if k not in merged:
                merged[k] = m
            else:
                existing = merged[k]
                existing.showtimes.extend(m.showtimes)
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
