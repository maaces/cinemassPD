"""Scraper per il Piccolo Teatro di Padova (cinema) - https://www.piccolo-padova.it/

Calibrato sull'HTML reale della home (ottobre 2026).

Il sito e' un WordPress classico, in HTML statico. La home elenca i post
(10 per pagina, pagine successive su /page/2/, /page/3/, ...; quando le
pagine finiscono il sito risponde 404). Ogni post e' un <article> la cui
classe CSS contiene la categoria di WordPress:

    <article class="post-24603 post ... category-cinema">
        a[href=pagina del film] > h2.entry-title        titolo
        .data-evento   "sabato 3 ottobre ore 21.15
                        domenica 4 ottobre ore 18.45 e 21.15"
        img.wp-post-image[src]                           locandina

Il Piccolo mescola cinema, teatro, musica, lirica e incontri. Qui si tengono
SOLO gli articoli con classe "category-cinema". Gli altri (category-teatro,
category-musica, category-arte, category-evento-di-terzi...) sono scartati.
Per includerne altri, aggiungili a INCLUDE_CATEGORIES (ma poi dovrai
gestire a mano il fatto che non sono film).

Biglietti: il sito rimanda a Liveticket. Gli eventi di Liveticket sono
raggruppati per intervallo ("dal 03/10 al 04/10") e non danno gli orari
dei singoli giorni, quindi gli orari li prendo dal sito del Piccolo e
uso Liveticket solo come link di acquisto.
"""
import datetime as dt
import re
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from models import Movie, Showtime
from scrapers.italian_dates import parse_showtimes
from utils import DEBUG_PAGES, get_session, polite_get, nice_title

ROME = ZoneInfo("Europe/Rome")
MAX_PAGES = 6
INCLUDE_CATEGORIES = {"cinema"}
TICKET_URL = "https://www.liveticket.it/piccoloteatropadova"
VOS_RE = re.compile(r"\s*[\[(]\s*(?:v\.?o\.?s?\.?|lingua originale)\s*[\])]\s*|\s+[-–]\s*v\.?o\.?\s*$", re.I)


def parse_page(html: str, cinema_name: str, today: Optional[dt.date] = None) -> List[Movie]:
    today = today or dt.datetime.now(ROME).date()
    soup = BeautifulSoup(html, "html.parser")
    movies: Dict[str, Movie] = {}
    for art in soup.select("article"):
        cats = {c[len("category-"):] for c in art.get("class", []) if c.startswith("category-")}
        if not cats & INCLUDE_CATEGORIES:
            continue
        title_el = art.select_one("h2.entry-title") or art.select_one("h2")
        when_el = art.select_one(".data-evento")
        if not title_el or not when_el:
            continue
        shows = parse_showtimes(" ".join(when_el.get_text(" ", strip=True).split()), today)
        if not shows:
            continue

        raw_title = " ".join(title_el.get_text(" ", strip=True).split())
        vos = bool(VOS_RE.search(raw_title))
        link = title_el.find_parent("a") or art.select_one("a[href]")
        img = art.select_one("img.wp-post-image")
        poster = img.get("src") if img else None

        movie = Movie(
            title=nice_title(VOS_RE.sub("", raw_title).strip()),
            poster_url=poster if poster and poster.startswith("http") else None,
            detail_url=link.get("href") if link else None,
        )
        for day, time in shows:
            movie.showtimes.append(Showtime(
                date=day.strftime("%Y-%m-%d"), time=time, cinema=cinema_name,
                note="V.O.S." if vos else None, booking_url=TICKET_URL,
            ))
        key = movie.norm_key()
        if key in movies:
            movies[key].showtimes.extend(movie.showtimes)
        else:
            movies[key] = movie
    return list(movies.values())


def scrape(url: str, cinema_name: str) -> List[Movie]:
    session = get_session()
    base = url.rstrip("/")
    movies: Dict[str, Movie] = {}
    for n in range(1, MAX_PAGES + 1):
        page_url = base + "/" if n == 1 else f"{base}/page/{n}/"
        try:
            resp = polite_get(session, page_url)
        except requests.HTTPError as e:
            if n > 1 and e.response is not None and e.response.status_code == 404:
                break  # finite le pagine
            raise
        for m in parse_page(resp.text, cinema_name):
            key = m.norm_key()
            if key in movies:
                movies[key].showtimes.extend(m.showtimes)
            else:
                movies[key] = m
    return list(movies.values())
