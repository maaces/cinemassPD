"""Arricchisce le schede Movie:

- Link SEMPRE disponibili, senza bisogno di alcuna API key:
    - letterboxd_url: link di RICERCA Letterboxd (Letterboxd non offre una
      API di ricerca pubblica gratuita, quindi non possiamo garantire un
      link diretto affidabile: la ricerca e' la scelta piu' robusta).
    - trailer_search_url: link di RICERCA YouTube ("<titolo> trailer").

- Link/dati PIU' precisi se fornisci una TMDB_API_KEY (gratuita, vedi
  README): tmdb_url (link diretto alla scheda del film), e per completare
  regista/durata/locandina/trailer quando il sito del cinema non li da'
  gia' (es. Multiastra e Porto Astra non pubblicano il regista in home).

- Titolo: se il film trovato su TMDB ha (a meno di maiuscole, accenti e
  punteggiatura) lo stesso titolo di quello del cinema, si usa la grafia
  ufficiale di TMDB ("AVENGERS: DOOMSDAY" -> "Avengers: Doomsday"). Se i
  titoli non corrispondono, il risultato TMDB potrebbe essere un altro film
  e il titolo del cinema resta com'e'.
"""
import difflib
import re
import time
import urllib.parse
from typing import List, Optional

import requests

from models import Movie, title_key

TMDB_BASE = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p/w500"


def _clean_title_for_search(title: str) -> str:
    t = title.lower().replace("’", "'")
    t = re.sub(r"\(.*?\)", " ", t)   # (RIED. 2026), (STITCH HEAD), (ED.SPEC.) ...
    t = re.sub(r"\b4k\b", " ", t)
    for junk in ["v.o.s", "v.o.", "extra"]:
        t = t.replace(junk, "")
    t = " ".join(t.split())
    return t.strip(" -–—")


def _official_title(scraped: str, hit: dict) -> Optional[str]:
    """Titolo TMDB (italiano o originale) da usare al posto di quello del cinema,
    solo se e' davvero lo stesso titolo scritto in un altro modo."""
    k = title_key(_clean_title_for_search(scraped))
    if not k:
        return None
    cands = [(c, title_key(c)) for c in (hit.get("title"), hit.get("original_title")) if c]
    for c, ck in cands:   # 1) stesso titolo, scritto diversamente
        if ck == k:
            return c
    for c, ck in cands:   # 2) titolo troncato dal sito ("Indagine su un cittadino al di sopra di")
        if len(k) >= 15 and ck.startswith(k + " "):
            return c
    for c, ck in cands:   # 3) piccolo refuso del sito ("Yellows letters")
        if len(k) >= 8 and difflib.SequenceMatcher(None, k, ck).ratio() >= 0.92:
            return c
    return None


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


def _enrich_from_tmdb(session: requests.Session, api_key: str, m: Movie) -> None:
    hit = _tmdb_search(session, api_key, m.title)
    if not hit:
        return

    official = _official_title(m.title, hit)
    if official:
        m.title = official

    if not m.tmdb_url:
        m.tmdb_url = f"https://www.themoviedb.org/movie/{hit['id']}"

    needs_details = not (m.director and m.duration_min and m.poster_url and m.trailer_url)
    if needs_details:
        details = _tmdb_details(session, api_key, hit["id"])
        if details:
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

    time.sleep(0.25)  # rispetto dei rate limit TMDB


def enrich_movies(movies: List[Movie], tmdb_api_key: Optional[str]) -> None:
    """Modifica 'movies' in place, riempiendo solo i campi mancanti."""
    session = requests.Session()

    for m in movies:
        if tmdb_api_key:
            try:
                _enrich_from_tmdb(session, tmdb_api_key, m)
            except requests.RequestException:
                pass  # se TMDB non risponde, il film resta con i soli dati dello scraper

        # --- Fallback universali: nessuna rete/API richiesta (dopo TMDB, cosi'
        # usano gia' il titolo ufficiale) ---
        if not m.letterboxd_url:
            q = urllib.parse.quote(_clean_title_for_search(m.title))
            m.letterboxd_url = f"https://letterboxd.com/search/films/{q}/"
        if not m.trailer_search_url:
            q = urllib.parse.quote(f"{m.title} trailer")
            m.trailer_search_url = f"https://www.youtube.com/results?search_query={q}"
