"""Scraper per MovieConnection (es. il Lux di Padova).

Sito: https://www.movieconnection.it/lux/
Struttura: WordPress statico con film in un elenco, titoli linkati a schede
con dettagli (regia, paese, anno, durata) e link agli orari/prenotazioni.
"""
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from models import Movie, Showtime
from utils import get_session, polite_get, clean_youtube_url

DETAIL_LINK_RE = re.compile(r"/film/[^/?]+/?$")


def scrape(base_url: str, cinema_name: str) -> List[Movie]:
    session = get_session()
    resp = polite_get(session, base_url)
    soup = BeautifulSoup(resp.text, "html.parser")

    movies = {}
    
    # Cerca elenco di film: di solito in un <ul>/<li> o una griglia di div
    for film_elem in soup.find_all(["li", "div"], class_=re.compile("film|movie|post", re.I)):
        title_link = film_elem.find("a", href=DETAIL_LINK_RE)
        if not title_link:
            continue
        
        title = title_link.get_text(strip=True)
        if not title or len(title) < 2:
            continue
        
        if title not in movies:
            detail_url = title_link.get("href", "")
            if not detail_url.startswith("http"):
                detail_url = base_url.rstrip("/") + "/" + detail_url.lstrip("/")
            
            # Estrai immagine (locandina)
            poster_url = None
            img = film_elem.find("img")
            if img:
                poster_url = img.get("src")
                if poster_url and not poster_url.startswith("http"):
                    poster_url = base_url.rstrip("/") + "/" + poster_url.lstrip("/")
            
            # Estrai metadati dal testo (regia, anno, paese, durata)
            director = None
            duration_min = None
            text = film_elem.get_text(" ", strip=True)
            
            # Cerca "Regia: NomeRegista"
            regia_m = re.search(r"Regia:\s*([^,\n]+)", text, re.I)
            if regia_m:
                director = regia_m.group(1).strip()
            
            # Cerca "XXX min"
            dur_m = re.search(r"(\d{1,3})\s*min", text)
            if dur_m:
                duration_min = int(dur_m.group(1))
            
            movies[title] = Movie(
                title=title,
                director=director,
                duration_min=duration_min,
                poster_url=poster_url,
                detail_url=detail_url,
            )
        
        # Cerca orari (tipicamente link "Orari", "Prenota", ecc.)
        # Se non ci sono inline, useremo la pagina di dettaglio
        for time_link in film_elem.find_all("a", href=re.compile("orari|prenota", re.I)):
            label = time_link.get_text(strip=True)
            # Se il label contiene un orario (es. "17:00" o "20.30")
            tm = re.search(r"(\d{1,2})[:.](\d{2})", label)
            if tm:
                movies[title].showtimes.append(Showtime(
                    date="data-da-verificare",  # MovieConnection non sempre mostra la data nella lista
                    time=f"{int(tm.group(1)):02d}:{tm.group(2)}",
                    cinema=cinema_name,
                    booking_url=time_link.get("href"),
                    date_uncertain=True,
                ))
    
    return list(movies.values())
