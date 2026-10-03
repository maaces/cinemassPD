"""Scraper per Cinema Esperia (Padova) - https://www.esperiapadova.it/Blog?category=1

Calibrato sull'HTML reale della pagina (ottobre 2026).

Il sito e' un blog "a schede" in HTML statico (nessun JavaScript necessario):
  div.blog_post
     a.show[href="./Post?postid=840"]          scheda del film
     img.Bfotopost[src="data/img/840/x.jpg"]   locandina (percorso relativo)
     .Btitle                                   titolo (TUTTO MAIUSCOLO)
     .Bsubtitle   date e orari in TESTO LIBERO + prezzi:
        "VENERDI 2 Ottobre - ore 21.00, DOMENICA 4 Ottobre - ore 18.30
         Interi: 6,00 euro ; - ridotti :5,00 euro."
     a "ACQUISTA ONLINE" -> 2tickets.it
     .news_date                                data di PUBBLICAZIONE del post (non della proiezione!)
  paginazione: <a class="pagingbutton" href="?pagination=2&category=1...">

La categoria "Programmazione cinematografica" contiene anche post che non
sono film ("Europa Cinemas", "Contatti telefonici"): si riconoscono perche'
NON hanno date+orari nel sottotitolo, e vengono scartati.
"""
import datetime as dt
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import Movie, Showtime
from scrapers.italian_dates import parse_showtimes
from utils import get_session, polite_get, nice_title

ROME = ZoneInfo("Europe/Rome")
MAX_PAGES = 5
PRICE_FULL_RE = re.compile(r"interi?\W{0,4}(\d+(?:[.,]\d{1,2})?)\s*(?:euro|€)", re.I)
PRICE_RED_RE = re.compile(r"ridott\w*\W{0,4}(\d+(?:[.,]\d{1,2})?)\s*(?:euro|€)", re.I)
# "Regia di Tommaso Landucci." / "Un film di Christopher Nolan con ..." (solo i primi 4 nomi, iniziali comprese)
DIRECTOR_RE = re.compile(r"(?:\bRegia di|\bUn film di)\s+((?:[A-ZÀ-Ý]\.\s*|[A-ZÀ-Ý][\w'’\-]+\s+){0,3}[A-ZÀ-Ý][\w'’\-]+)")
VOS_RE = re.compile(r"\b(v\.?o\.?s?\.?|lingua originale)\b", re.I)


def _money(s: str) -> str:
    v = float(s.replace(",", "."))
    return f"{int(v)} €" if v == int(v) else f"{v:.2f}".replace(".", ",") + " €"


def _price(text: str) -> Optional[str]:
    full, red = PRICE_FULL_RE.search(text), PRICE_RED_RE.search(text)
    if full and red:
        return f"{_money(full.group(1))} (rid. {_money(red.group(1))})"
    return _money(full.group(1)) if full else None


def parse_page(html: str, cinema_name: str, page_url: str, today: Optional[dt.date] = None) -> List[Movie]:
    today = today or dt.datetime.now(ROME).date()
    soup = BeautifulSoup(html, "html.parser")
    movies: Dict[str, Movie] = {}
    for post in soup.select("div.blog_post"):
        title_el = post.select_one(".Btitle")
        sub_el = post.select_one(".Bsubtitle")
        if not title_el or not sub_el:
            continue
        sub = " ".join(sub_el.get_text(" ", strip=True).split())
        shows = parse_showtimes(sub, today)
        if not shows:  # post che non e' un film (avvisi, contatti, ...)
            continue

        raw_title = " ".join(title_el.get_text(" ", strip=True).split())
        link = post.select_one("a.show")
        img = post.select_one("img.Bfotopost")
        buy = next((a for a in post.select("a") if "acquista" in a.get_text().lower()), None)
        body = post.select_one(".readmore-content")
        body_text = " ".join(body.get_text(" ", strip=True).split()) if body else ""
        dm = DIRECTOR_RE.search(body_text)

        movie = Movie(
            title=nice_title(raw_title),
            director=dm.group(1).strip(" .") if dm else None,
            poster_url=urljoin(page_url, img["src"]) if img and img.get("src") else None,
            detail_url=urljoin(page_url, link["href"]) if link and link.get("href") else None,
        )
        price = _price(sub)
        note = "V.O.S." if VOS_RE.search(raw_title + " " + sub) else None
        for day, time in shows:
            movie.showtimes.append(Showtime(
                date=day.strftime("%Y-%m-%d"), time=time, cinema=cinema_name,
                price=price, note=note, booking_url=buy.get("href") if buy else None,
            ))
        key = movie.norm_key()
        if key in movies:
            movies[key].showtimes.extend(movie.showtimes)
        else:
            movies[key] = movie
    return list(movies.values())


def scrape(url: str, cinema_name: str) -> List[Movie]:
    session = get_session()
    movies: Dict[str, Movie] = {}
    seen_urls = set()
    queue = [url]
    while queue and len(seen_urls) < MAX_PAGES:
        page_url = queue.pop(0)
        if page_url in seen_urls:
            continue
        seen_urls.add(page_url)
        resp = polite_get(session, page_url)
        for m in parse_page(resp.text, cinema_name, page_url):
            key = m.norm_key()
            if key in movies:
                movies[key].showtimes.extend(m.showtimes)
            else:
                movies[key] = m
        # pagine successive (di solito ce n'e' una sola)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("a.pagingbutton[href]"):
            label = a.get_text(strip=True)
            if not label.isdigit() or int(label) < 2:
                continue  # "1" e' la pagina che stiamo gia' leggendo; "«" e "»" li ignoro
            nxt = urljoin(page_url, a["href"])
            if nxt not in seen_urls and nxt not in queue:
                queue.append(nxt)
    for m in movies.values():  # per sicurezza: stessa proiezione letta due volte = una sola
        seen, unique = set(), []
        for st in m.showtimes:
            if (st.date, st.time) not in seen:
                seen.add((st.date, st.time))
                unique.append(st)
        m.showtimes = unique
    return list(movies.values())
