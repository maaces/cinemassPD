"""Scraper per siti che caricano gli orari via JavaScript (The Space Cinema,
Cinema Rex): usano Playwright (browser headless), che gira senza problemi
su GitHub Actions (impossibile invece su Termux/telefono).

ONESTA' SUL LIVELLO DI CONFIDENZA: a differenza degli altri 5 scraper di
questo progetto, questi due NON sono stati verificati su HTML reale, perche'
lo strumento con cui ho ispezionato gli altri siti non esegue JavaScript e
quindi non riesce a vedere cosa c'e' dietro questi due. L'estrazione qui
sotto e' percio' "generica": cammina il DOM cercando testo nel formato
HH:MM vicino a un'intestazione, che potrebbe non trovare nulla o trovare
cose sbagliate a seconda della vera struttura del sito.

Quello che *e'* garantito: ad ogni esecuzione l'HTML della pagina COSI' COM'E'
DOPO il rendering JavaScript viene salvato in docs/debug/<cinema>.txt (lo
stesso meccanismo di diagnostica usato per gli altri cinema). Quindi anche
se l'estrazione fallisce al primo giro, avremo finalmente l'HTML vero da
cui scrivere uno scraper preciso, esattamente come e' stato fatto per
Cineplex Moderno, MovieConnection e Fronte del Porto.
"""
import re
from typing import List, Optional

from models import Movie, Showtime
from utils import DEBUG_PAGES

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5")


def _render_with_playwright(url: str) -> Optional[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"[!] Playwright non installato: impossibile leggere {url}. "
              f"Aggiungi 'pip install playwright && playwright install --with-deps chromium' "
              f"al workflow (vedi README).")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(2500)  # margine per rendering JS lento/lazy load
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"[!] Errore Playwright su {url}: {e}")
        return None


def _generic_extract(html: str, cinema_name: str) -> List[Movie]:
    """Estrazione 'best effort' generica: l'ultima intestazione (h1-h5)
    incontrata cammin facendo diventa il 'film corrente', e ogni testo nel
    formato esatto HH:MM trovato dopo di essa (dentro link/bottoni/testo)
    viene registrato come suo orario, con data segnata come 'da verificare'
    perche' senza conoscere la struttura reale non sappiamo a quale giorno
    appartenga. Va quasi certamente ricalibrata sull'HTML vero (vedi sopra)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    movies = {}
    current_title = None
    for el in soup.find_all(HEADING_TAGS + ("a", "button", "span", "li")):
        text = el.get_text(" ", strip=True)
        if not text or len(text) > 200:
            continue

        if el.name in HEADING_TAGS and 2 < len(text) < 100:
            current_title = text
            if current_title not in movies:
                movies[current_title] = Movie(title=current_title)
            continue

        if el.name in ("a", "button", "span", "li") and current_title:
            m = TIME_RE.match(text)
            if m:
                movies[current_title].showtimes.append(Showtime(
                    date="data-da-verificare",
                    time=f"{int(m.group(1)):02d}:{m.group(2)}",
                    cinema=cinema_name,
                    date_uncertain=True,
                ))

    return list(movies.values())


def _scrape_generic(url: str, cinema_name: str) -> List[Movie]:
    html = _render_with_playwright(url)
    if not html:
        return []
    DEBUG_PAGES[url] = html  # fondamentale: cosi' finisce nel report di diagnostica
    return _generic_extract(html, cinema_name)


def scrape_space_cinema(url: str, cinema_name: str) -> List[Movie]:
    return _scrape_generic(url, cinema_name)


def scrape_cinema_rex(url: str, cinema_name: str) -> List[Movie]:
    return _scrape_generic(url, cinema_name)
