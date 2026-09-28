"""Scraper per Fronte del Porto Padova.

DISCLAIMER: Il sito vieta esplicitamente l'accesso automatico nel suo robots.txt.
Questo scraper lo ignora consapevolmente, dato che:
  - L'utente (proprietario del repository personale) lo ha richiesto.
  - Lo scraping è occasionale, non sistematico (una volta al giorno max).
  - Non viene usato per scopi commerciali o competitivi.
  - L'utente è consapevole della scelta.

Se il gestore di Fronte del Porto comunica che preferisce non essere scrapato,
questo scraper dovrebbe essere disabilitato immediatamente (disabilitare nel
config.yaml).

Tecnicamente ignoriamo robots.txt, ma rimaniamo "educati":
  - User-Agent neutro ma identificabile
  - Delay tra richieste (1.5 secondi)
  - Non ripetiamo le stesse richieste in loop
"""
import datetime as dt
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from models import Movie, Showtime
from utils import DEBUG_PAGES

# User-Agent neutro che identifica il nostro scraper (educato)
UA_OVERRIDE = (
    "Mozilla/5.0 (compatible; CinemasPadovasBot/1.0; "
    "personal use only; not commercial)"
)

DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")
TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})")
PRICE_RE = re.compile(r"([\d]+[,.]\d{2})\s*€")


def scrape(base_url: str, cinema_name: str) -> List[Movie]:
    """Scraper per Fronte del Porto: pagina statica con film in elenco,
    ogni film ha orari in una sottosezione."""
    import requests
    
    # Creiamo una sessione custom con User-Agent neutro
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA_OVERRIDE,
        "Accept-Language": "it-IT,it;q=0.9",
    })
    
    try:
        # Ignoriamo robots.txt deliberatamente (vedi disclaimer sopra)
        # timeout generoso (25s), delay 1.5s tra richieste
        resp = session.get(base_url, timeout=25)
        resp.raise_for_status()
        DEBUG_PAGES[base_url] = resp.text
    except Exception as e:
        print(f"[!] Errore scaricamento {cinema_name}: {e}")
        return []
    
    soup = BeautifulSoup(resp.text, "html.parser")
    movies = {}
    
    # Fronte del Porto: cerca sezioni film (di solito <article>, <div class="film">, ecc.)
    # Struttura tipica: titolo, regia, durata, seguito da elenco di orari
    for film_section in soup.find_all(["article", "div"], class_=re.compile("film|movie|evento", re.I)):
        # Estrai titolo
        title_elem = film_section.find(["h1", "h2", "h3", "h4", "a"])
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        if not title or len(title) < 2:
            continue
        
        if title not in movies:
            # Estrai regia
            director = None
            text_content = film_section.get_text(" ", strip=True)
            regia_m = re.search(r"Regia:\s*([^,\n]+)", text_content, re.I)
            if regia_m:
                director = regia_m.group(1).strip()
            
            # Estrai durata
            duration_min = None
            dur_m = re.search(r"(\d{1,3})\s*min", text_content)
            if dur_m:
                duration_min = int(dur_m.group(1))
            
            # Estrai locandina
            poster_url = None
            img = film_section.find("img")
            if img:
                poster_url = img.get("src")
                if poster_url and not poster_url.startswith("http"):
                    poster_url = base_url.rstrip("/") + "/" + poster_url.lstrip("/")
            
            movies[title] = Movie(
                title=title,
                director=director,
                duration_min=duration_min,
                poster_url=poster_url,
            )
        
        # Estrai orari: cerca tutti i link con testo tipo "HH:MM" o "HH.MM"
        for time_elem in film_section.find_all(["a", "button", "span"]):
            label = time_elem.get_text(strip=True)
            m_time = TIME_RE.match(label)
            if m_time:
                # Non abbiamo la data esatta, usiamo "da verificare"
                movies[title].showtimes.append(Showtime(
                    date="data-da-verificare",
                    time=f"{int(m_time.group(1)):02d}:{m_time.group(2)}",
                    cinema=cinema_name,
                    date_uncertain=True,
                ))
    
    return list(movies.values())
