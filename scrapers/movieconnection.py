"""Scraper per MovieConnection / il Lux (Padova).

Verificato sull'HTML reale (https://www.movieconnection.it/lux/): il sito usa
il plugin WordPress "The Events Calendar" (tribe-events). Ogni PROIEZIONE (non
ogni film) e' una riga <li class="tribe-events-calendar-list__event-row">
con data (attributo datetime="YYYY-MM-DD", affidabile) e un titolo nel
formato "TITOLO – Regista # Paese Anno (durata′)". Proiezioni ripetute dello
stesso film (es. NAZA su piu' giorni) sono righe separate: le raggruppiamo
per titolo.
"""
import re
from typing import List

from bs4 import BeautifulSoup

from models import Movie, Showtime
from utils import get_session, polite_get

# "ALICE NELLE CITTÀ – Wim Wenders # Germania Ovest 1973 (110′)"
# "DUEL – Steven Spielberg # USA 1971"   (durata non sempre presente)
TITLE_RE = re.compile(
    r"^(?P<title>.+?)\s*[–-]\s*(?P<director>.+?)\s*#\s*(?P<country>.+?)\s+"
    r"(?P<year>\d{4})(?:\s*\((?P<duration>\d+)[′'\u2032]\))?\s*$"
)
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*$")


def scrape(base_url: str, cinema_name: str) -> List[Movie]:
    session = get_session()
    resp = polite_get(session, base_url)
    soup = BeautifulSoup(resp.text, "html.parser")

    movies = {}

    for row in soup.find_all("li", class_="tribe-events-calendar-list__event-row"):
        article = row.find("article")
        if not article:
            continue

        title_link = article.select_one("h4.tribe-events-calendar-list__event-title a")
        if not title_link:
            continue
        full_title = title_link.get_text(strip=True)
        detail_url = title_link.get("href")

        m = TITLE_RE.match(full_title)
        if m:
            title = m.group("title").strip()
            director = m.group("director").strip()
            duration = int(m.group("duration")) if m.group("duration") else None
        else:
            title, director, duration = full_title, None, None

        key = title.lower()
        if key not in movies:
            img = article.select_one(".tribe-events-calendar-list__event-featured-image-wrapper img")
            poster_url = img.get("src") if img else None
            movies[key] = Movie(title=title, director=director, duration_min=duration,
                                 poster_url=poster_url, detail_url=detail_url)

        time_el = article.select_one("time.tribe-events-calendar-list__event-datetime")
        date_str = time_el.get("datetime") if time_el else None
        start_span = article.select_one(".tribe-event-date-start")
        time_str = None
        if start_span:
            tm = TIME_RE.search(start_span.get_text(strip=True))
            if tm:
                time_str = f"{int(tm.group(1)):02d}:{tm.group(2)}"

        if date_str and time_str:
            movies[key].showtimes.append(Showtime(
                date=date_str, time=time_str, cinema=cinema_name, booking_url=detail_url,
            ))

    return list(movies.values())
