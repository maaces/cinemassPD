"""Scraper per siti che caricano orari via JavaScript (The Space Cinema, Cinema Rex).

Usa Playwright (browser headless), che gira su GitHub Actions senza problemi.
Questo modulo e' facoltativo: se Playwright non e' installato, il sistema
continua comunque (saltera' il cinema con un warning).

Comandi GitHub Actions per abilitare:
  - pip install playwright
  - playwright install  (scarica i binari del browser)
"""
import datetime as dt
import re
from typing import List, Optional

from models import Movie, Showtime
from utils import get_session, clean_youtube_url

DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})")
PRICE_RE = re.compile(r"([\d]+[,.]\d{2})\s*€")


def scrape_space_cinema(base_url: str, cinema_name: str) -> List[Movie]:
    """The Space Cinema: orari caricati via JavaScript, tipicamente in una
    tabella con data/sala e pulsanti con orario per ogni proiezione.
    Esempio URL: https://www.thespacecinema.it/cinema/limena/al-cinema"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"[!] Playwright non installato: {cinema_name} verra' saltato")
        return []

    movies = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(base_url, wait_until="networkidle", timeout=30000)
            
            # Legge il content HTML DOPO che JavaScript ha girato
            html = page.content()
            browser.close()

            # Simple scraping: cerca film che hanno link a scheda e orari
            # (logica semplificata per non complicare troppo, qui e' il concetto)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            
            # The Space ha una struttura specifica. Qui usiamo pattern generici:
            # se la struttura reale e' diversa, va calibrata con debug_dump
            for film_section in soup.find_all("div", class_=re.compile("film|movie", re.I)):
                title_elem = film_section.find(["h1", "h2", "h3", "a"])
                if not title_elem:
                    continue
                title = title_elem.get_text(strip=True)
                if not title or len(title) < 2:
                    continue
                if title not in movies:
                    movies[title] = Movie(title=title)
                
                # Cerca orari (di solito sono link o button con orario)
                for time_elem in film_section.find_all(["a", "button"], 
                                                        string=re.compile(r"^\d{1,2}:\d{2}$")):
                    text = time_elem.get_text(strip=True)
                    m = TIME_RE.match(text)
                    if m:
                        # Assume data odierna (senza info precisa dai link, usiamo placeholder)
                        today = dt.date.today()
                        date_str = today.isoformat()
                        movies[title].showtimes.append(Showtime(
                            date=date_str,
                            time=f"{int(m.group(1)):02d}:{m.group(2)}",
                            cinema=cinema_name,
                            date_uncertain=True,  # senza data esplicita dal sito
                        ))

    except Exception as e:
        print(f"[!] Errore durante lo scraping di {cinema_name}: {e}")
    
    return list(movies.values())


def scrape_cinema_rex(base_url: str, cinema_name: str) -> List[Movie]:
    """Cinema Rex: simile a The Space, orari caricati via JS.
    URL di esempio: https://www.cinemarex.it/"""
    return scrape_space_cinema(base_url, cinema_name)  # stessa logica per ora
