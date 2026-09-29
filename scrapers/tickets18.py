"""Scraper per cinema basati sulla piattaforma '18tickets' (18months.it).

Verificato sull'HTML reale di Cineplex Moderno (pd.cineplexmoderno.cineplexmoderno.it).
Ogni film e' un blocco <div class="movie movie--preview"> con:
  - titolo e link:        h6 a.movie__title
  - locandina:             .movie__images img
  - regista/cast:          <p class="movie__option"><strong>Regia:</strong> ...</p>
                            (ogni campo e' un <p> separato: niente piu' testo
                            di lingua/cast/programmazione mescolato nel regista)
  - trailer:                a.trailer-sample (spesso con URL malformato/annidato,
                            ripulito da clean_youtube_url)
  - orari:                  ogni proiezione e' <a data-time="EPOCH_MS" href="...">,
                            l'epoch in millisecondi ci da' data e ora ESATTE senza
                            dover interpretare il testo italiano ("Lunedi 28/09/2026"),
                            quindi e' la fonte piu' affidabile che abbiamo.
"""
import datetime
import re
from typing import List
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import Movie, Showtime
from utils import get_session, polite_get, clean_youtube_url

ROME = ZoneInfo("Europe/Rome")
ROOM_RE = re.compile(r"(Sala\s*\S+)\s*(.*)$", re.I)


def scrape(base_url: str, cinema_name: str) -> List[Movie]:
    session = get_session()
    resp = polite_get(session, base_url)
    soup = BeautifulSoup(resp.text, "html.parser")

    movies: List[Movie] = []

    for movie_div in soup.find_all("div", class_="movie--preview"):
        title_link = movie_div.select_one("h6 a.movie__title") or movie_div.find("a", class_="movie__title")
        if not title_link:
            continue
        title = title_link.get_text(strip=True)
        if not title:
            continue

        href = title_link.get("href", "")
        detail_url = href if href.startswith("http") else base_url.rstrip("/") + href

        img = movie_div.select_one(".movie__images img")
        poster_url = img.get("src") if img else None

        movie = Movie(title=title, detail_url=detail_url, poster_url=poster_url)

        # Ogni informazione (Regia, Con, Lingua, Eta') e' un <p> a se':
        # leggiamo solo quelli che ci interessano, senza swallow di testo altrui.
        for p in movie_div.find_all("p", class_="movie__option"):
            strong = p.find("strong")
            if not strong:
                continue
            label = strong.get_text(strip=True)
            value = p.get_text(" ", strip=True)
            if value.startswith(label):
                value = value[len(label):].strip()
            label_l = label.lower().rstrip(":")
            if label_l.startswith("regia") and value:
                movie.director = value
            elif label_l.startswith("con") and value:
                movie.cast = [c.strip() for c in value.split(",") if c.strip()]

        trailer_a = movie_div.find("a", class_="trailer-sample")
        if trailer_a:
            movie.trailer_url = clean_youtube_url(trailer_a.get("href", ""))

        for a in movie_div.select("a[data-time]"):
            ms = a.get("data-time")
            if not ms:
                continue
            try:
                dt_local = datetime.datetime.fromtimestamp(int(ms) / 1000, tz=ROME)
            except (ValueError, OSError, OverflowError):
                continue

            li_text = a.get_text(" ", strip=True)
            room, note = None, None
            rest = re.sub(r"^\d{1,2}:\d{2}\s*", "", li_text).strip()
            room_match = ROOM_RE.match(rest)
            if room_match:
                room = room_match.group(1)
                note = room_match.group(2).strip() or None
            elif rest:
                note = rest

            a_href = a.get("href", "")
            movie.showtimes.append(Showtime(
                date=dt_local.strftime("%Y-%m-%d"),
                time=dt_local.strftime("%H:%M"),
                cinema=cinema_name,
                room=room,
                note=note,
                booking_url=a_href if a_href.startswith("http") else base_url.rstrip("/") + a_href,
            ))

        movies.append(movie)

    return movies
