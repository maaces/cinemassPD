"""Scraper per cinema basati sulla piattaforma '18tickets' (18months.it).

Esempio riconosciuto: Cineplex Moderno (pd.cineplexmoderno.cineplexmoderno.it).
La programmazione e' resa server-side in HTML "normale": ogni film ha un
blocco con titolo, regia, cast, e per ogni giorno un elenco di link con
orario e sala. Questo modulo cammina il DOM in ordine di apparizione e
tiene traccia di "film corrente" e "data corrente" via via che li incontra.

NOTA: gli esatti nomi di classe CSS di questa piattaforma non sono stati
verificati su HTML grezzo (il nostro strumento di lettura pagine restituisce
testo/markdown, non HTML puro). La logica sotto si basa sui pattern di URL
(che sono stabili) piuttosto che su classi CSS, per essere piu' robusta.
Se qualcosa smette di funzionare dopo un aggiornamento del sito, usa
tools/debug_dump.py per salvare l'HTML reale e sistemare i pattern.
"""
import re
from typing import List

from bs4 import BeautifulSoup

from models import Movie, Showtime
from utils import get_session, polite_get, clean_youtube_url

FILM_HEADING_RE = re.compile(r"/film/(\d+)/?$")
SHOWTIME_LINK_RE = re.compile(r"/film/\d+/[0-9a-fA-F-]{36}")
DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})")

MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}


def scrape(base_url: str, cinema_name: str) -> List[Movie]:
    session = get_session()
    resp = polite_get(session, base_url)
    soup = BeautifulSoup(resp.text, "html.parser")

    movies = {}
    current_movie = None
    current_date = None

    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "a", "p", "div", "span"]):
        link_tag = el if el.name == "a" else el.find("a", recursive=False)
        href = (link_tag.get("href") if link_tag else None) or ""

        # Intestazione film: link diretto a /film/<id> (non uno spettacolo specifico)
        if link_tag and FILM_HEADING_RE.search(href) and not SHOWTIME_LINK_RE.search(href):
            title = link_tag.get_text(strip=True)
            if title and len(title) > 1:
                if title not in movies:
                    full_url = href if href.startswith("http") else base_url.rstrip("/") + href
                    movies[title] = Movie(title=title, detail_url=full_url)
                current_movie = movies[title]
                img = el.find("img") if el.name != "a" else None
                if img and img.get("src") and not current_movie.poster_url:
                    current_movie.poster_url = img["src"]
            continue

        text = el.get_text(" ", strip=True)

        if current_movie and text.startswith("Regia:") and not current_movie.director:
            current_movie.director = text.replace("Regia:", "", 1).strip()

        if current_movie and text.startswith("Con:") and not current_movie.cast:
            current_movie.cast = [c.strip() for c in text.replace("Con:", "", 1).split(",") if c.strip()]

        # Marcatore di data tipo "Sabato 26/09/2026"
        m = DATE_RE.search(text)
        if m and len(text) < 40:
            gg, mm, aaaa = m.groups()
            current_date = f"{aaaa}-{mm}-{gg}"

        if el.name == "a" and "youtube.com" in href and current_movie and not current_movie.trailer_url:
            current_movie.trailer_url = clean_youtube_url(href)

        if el.name == "a" and SHOWTIME_LINK_RE.search(href):
            label = el.get_text(" ", strip=True)
            tmatch = TIME_RE.match(label)
            if current_movie and current_date and tmatch:
                full_url = href if href.startswith("http") else base_url.rstrip("/") + href
                current_movie.showtimes.append(Showtime(
                    date=current_date,
                    time=f"{int(tmatch.group(1)):02d}:{tmatch.group(2)}",
                    cinema=cinema_name,
                    note=label[tmatch.end():].strip() or None,
                    booking_url=full_url,
                ))

    return list(movies.values())
