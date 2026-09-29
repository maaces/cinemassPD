"""Scraper per Fronte del Porto Padova.

DISCLAIMER: il sito vieta l'accesso automatico nel suo robots.txt. Questo
scraper lo ignora consapevolmente, su richiesta esplicita dell'utente
(uso personale, un aggiornamento per volta, User-Agent identificabile,
nessun uso commerciale). Se il gestore del sito comunicasse di preferire
il contrario, disabilita questo cinema in config.yaml.

Verificato sull'HTML reale (https://www.frontedelportopadova.it/eventi/):
struttura custom (non un plugin standard). Le proiezioni sono raggruppate
per giorno in blocchi <div class="programmazione-data-gruppo"> con un
titolo tipo "MERCOLEDì, 30 SETTEMBRE 2026"; ogni proiezione e' un
<article class="evento-card-new"> con titolo, locandina, orario
("H 21:00"), prezzo/nota e un link alla scheda passato via onclick
(il sito non usa <a href>, ma window.location.href=... in JS).
Niente regista qui: lo completa TMDB.
"""
import re
from typing import List

from bs4 import BeautifulSoup

from models import Movie, Showtime
from utils import DEBUG_PAGES, get_session, polite_get

MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
DATE_HEADER_RE = re.compile(r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})")
TIME_RE = re.compile(r"H\s*(\d{1,2}):(\d{2})")
HREF_RE = re.compile(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]")
DURATION_RE = re.compile(r"(\d{1,3})[\u2019\u2032']")


def scrape(base_url: str, cinema_name: str) -> List[Movie]:
    session = get_session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; CinemasPadovasBot/1.0; "
                      "personal use only; not commercial; contact via github repo)",
    })
    resp = session.get(base_url, timeout=25)  # ignora deliberatamente robots.txt
    resp.raise_for_status()
    DEBUG_PAGES[base_url] = resp.text

    soup = BeautifulSoup(resp.text, "html.parser")
    movies = {}

    for group in soup.find_all("div", class_="programmazione-data-gruppo"):
        header = group.find("h2", class_="programmazione-data-titolo")
        if not header:
            continue
        m = DATE_HEADER_RE.search(header.get_text(" ", strip=True))
        if not m:
            continue
        day, month_name, year = m.groups()
        month = MONTHS_IT.get(month_name.lower())
        if not month:
            continue
        date_str = f"{int(year):04d}-{month:02d}-{int(day):02d}"

        for article in group.find_all("article", class_="evento-card-new"):
            title_el = article.select_one("h2.evento-card-new-title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            key = title.lower()

            if key not in movies:
                img = article.select_one(".evento-card-new-immagine img")
                poster_url = img.get("src") if img else None
                href_m = HREF_RE.search(article.get("onclick", ""))
                detail_url = href_m.group(1) if href_m else None

                duration = None
                caratt = article.select_one(".evento-card-new-caratteristiche")
                if caratt:
                    dm = DURATION_RE.search(caratt.get_text(" ", strip=True))
                    if dm:
                        duration = int(dm.group(1))

                movies[key] = Movie(title=title, duration_min=duration,
                                     poster_url=poster_url, detail_url=detail_url)

            time_el = article.select_one(".evento-card-new-ora")
            if not time_el:
                continue
            tm = TIME_RE.search(time_el.get_text(" ", strip=True))
            if not tm:
                continue

            price_el = article.select_one(".prenota-prog-prezzo")
            note = price_el.get_text(" ", strip=True) if price_el else None

            movies[key].showtimes.append(Showtime(
                date=date_str,
                time=f"{int(tm.group(1)):02d}:{tm.group(2)}",
                cinema=cinema_name,
                note=note,
                booking_url=movies[key].detail_url,
            ))

    return list(movies.values())
