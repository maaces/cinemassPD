"""Per ogni proiezione genera:
  - un link 'Aggiungi a Google Calendar' (apre l'app pre-compilata, un tap)
  - il contenuto di un file .ics (per iPhone/Outlook/altri calendari)

Formato titolo evento: "{Titolo film} - {Regista}"
Luogo: nome del cinema
Inizio: orario di inizio proiezione
Fine: inizio + durata del film (se non nota, si usa un default di 2h,
segnalato chiaramente nella descrizione dell'evento).
"""
import datetime as dt
import urllib.parse
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from models import Movie, Showtime

ROME = ZoneInfo("Europe/Rome")
UTC = dt.timezone.utc
DEFAULT_DURATION_MIN = 120
_FMT = "%Y%m%dT%H%M%SZ"


def _start_end_utc(showtime: Showtime, duration_min: Optional[int]) -> Tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    try:
        y, mo, d = (int(x) for x in showtime.date.split("-"))
        h, mi = (int(x) for x in showtime.time.split(":"))
    except (ValueError, AttributeError, TypeError):
        return None, None
    start_local = dt.datetime(y, mo, d, h, mi, tzinfo=ROME)
    dur = duration_min or DEFAULT_DURATION_MIN
    end_local = start_local + dt.timedelta(minutes=dur)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _event_title(movie: Movie) -> str:
    return f"{movie.title} - {movie.director}" if movie.director else movie.title


def _description_lines(movie: Movie, showtime: Showtime):
    lines = []
    if showtime.price:
        lines.append(f"Prezzo: {showtime.price}")
    if showtime.note:
        lines.append(showtime.note)
    if not movie.duration_min:
        lines.append("Durata non nota: evento impostato a 2h di default, verifica sul sito del cinema.")
    if movie.detail_url:
        lines.append(movie.detail_url)
    return lines


def google_calendar_link(movie: Movie, showtime: Showtime) -> Optional[str]:
    start_utc, end_utc = _start_end_utc(showtime, movie.duration_min)
    if start_utc is None:
        return None
    params = {
        "action": "TEMPLATE",
        "text": _event_title(movie),
        "dates": f"{start_utc.strftime(_FMT)}/{end_utc.strftime(_FMT)}",
        "location": showtime.cinema,
        "details": "\n".join(_description_lines(movie, showtime)),
    }
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(",", "\\,")
                .replace(";", "\\;").replace("\n", "\\n"))


def ics_content(movie: Movie, showtime: Showtime) -> Optional[str]:
    start_utc, end_utc = _start_end_utc(showtime, movie.duration_min)
    if start_utc is None:
        return None
    uid = f"{abs(hash((movie.title, showtime.cinema, showtime.date, showtime.time)))}@cinema-scraper.local"
    description = _ics_escape("\n".join(_description_lines(movie, showtime)))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//cinema-scraper//IT",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dt.datetime.now(UTC).strftime(_FMT)}",
        f"DTSTART:{start_utc.strftime(_FMT)}",
        f"DTEND:{end_utc.strftime(_FMT)}",
        f"SUMMARY:{_ics_escape(_event_title(movie))}",
        f"LOCATION:{_ics_escape(showtime.cinema)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{description}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"
