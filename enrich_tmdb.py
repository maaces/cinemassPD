"""Arricchisce le schede Movie con dati mancanti usando TMDB
(https://www.themoviedb.org/), e aggiunge un link di ricerca Letterboxd.

TMDB e' gratuito per uso personale: serve solo registrarsi e creare una
API key (vedi README.md). Se non viene fornita nessuna chiave, questo
modulo non fa nulla (i film restano con i soli dati raccolti dagli
scraper) — il resto della pipeline funziona comunque.
"""
import time
import urllib.parse
from typing import List, Optional

import requests

from models import Movie

TMDB_BASE = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p/w500"


def _clean_title_for_search(title: str) -> str:
    # Toglie suffissi comuni che confondono la ricerca (es. "(Ried.)", "V.O.S")
    for junk in ["(ried.)", "(riedizione)", "v.o.s", "v.o.", "extra"]:
        title = title.lower().replace(junk, "")
    return title.strip(" -–—")


def _tmdb_search(session: requests.Session, api_key: str, title: str) -> Optional[dict]:
    params = {"api_key": api_key, "language": "it-IT", "query": _clean_title_for_search(title)}
    r = session.get(f"{TMDB_BASE}/search/movie", params=params, timeout=15)
    if not r.ok:
        return None
    results = r.json().get("results") or []
    return results[0] if results else None


def _tmdb_details(session: requests.Session, api_key: str, movie_id: int) -> Optional[dict]:
    params = {"api_key": api_key, "language": "it-IT", "append_to_response": "credits,videos"}
    r = session.get(f"{TMDB_BASE}/movie/{movie_id}", params=params, timeout=15)
    if not r.ok:
        return None
    return r.json()


def enrich_movies(movies: List[Movie], tmdb_api_key: Optional[str]) -> None:
    """Modifica 'movies' in place, riempiendo solo i campi mancanti."""
    session = requests.Session()

    for m in movies:
        # Link di ricerca Letterboxd: sempre valido, non richiede API.
        if not m.letterboxd_url:
            q = urllib.parse.quote(_clean_title_for_search(m.title))
            m.letterboxd_url = f"https://letterboxd.com/search/films/{q}/"

        needs_lookup = not m.director or not m.duration_min or not m.poster_url or not m.trailer_url
        if not (tmdb_api_key and needs_lookup):
            continue

        try:
            hit = _tmdb_search(session, tmdb_api_key, m.title)
            if not hit:
                continue
            details = _tmdb_details(session, tmdb_api_key, hit["id"])
            if not details:
                continue

            if not m.director:
                crew = (details.get("credits") or {}).get("crew") or []
                directors = [c["name"] for c in crew if c.get("job") == "Director"]
                if directors:
                    m.director = ", ".join(directors)

            if not m.duration_min and details.get("runtime"):
                m.duration_min = details["runtime"]

            if not m.poster_url and details.get("poster_path"):
                m.poster_url = POSTER_BASE + details["poster_path"]

            if not m.trailer_url:
                videos = (details.get("videos") or {}).get("results") or []
                yt = [v for v in videos if v.get("site") == "YouTube" and v.get("type") == "Trailer"]
                if yt:
                    m.trailer_url = f"https://www.youtube.com/watch?v={yt[0]['key']}"

            time.sleep(0.3)  # rispetto dei rate limit TMDB
        except requests.RequestException:
            # Se TMDB non risponde, semplicemente non arricchiamo questo film.
            continue
