"""Scraper per siti che caricano gli orari via JavaScript (The Space Cinema,
Cinema Rex): usano Playwright (browser headless), che gira senza problemi
su GitHub Actions.

Questi due scraper NON sono ancora stati verificati su HTML reale:
l'estrazione qui sotto e' "generica" (cerca testi HH:MM sotto
un'intestazione) e va calibrata.

Cosa e' garantito: ad ogni esecuzione in docs/debug/ finisce SEMPRE
qualcosa per questi cinema, anche se la pagina non carica:
  - l'HTML renderizzato (anche parziale, se il caricamento va in timeout)
  - oppure una pagina con l'errore esatto di Playwright
Prima, se Playwright andava in errore (tipicamente un timeout di
"networkidle", che su siti con analytics/pubblicita' non arriva mai) la
funzione restituiva None e nel debug non compariva nulla.
"""
import re
import traceback
from typing import List, Optional, Tuple

from models import Movie, Showtime
from utils import DEBUG_PAGES

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5")

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def _render_with_playwright(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Restituisce (html, errore). Prova sempre a recuperare l'HTML, anche
    se qualcosa va storto a meta' caricamento."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        return None, f"Playwright non installato: {e}"

    html, error = None, None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
            context = browser.new_context(
                user_agent=BROWSER_UA,
                locale="it-IT",
                timezone_id="Europe/Rome",
                viewport={"width": 1366, "height": 900},
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()
            try:
                # "domcontentloaded" invece di "networkidle": quest'ultimo su
                # molti siti non arriva mai (tracker, chat, banner) e fa fallire tutto
                resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if resp is not None and resp.status >= 400:
                    error = f"HTTP {resp.status} su {url}"
                # tenta di chiudere un eventuale banner cookie (best effort)
                for label in ("Accetta", "Accetta tutti", "Accetto", "Accept all", "OK"):
                    try:
                        page.get_by_role("button", name=label, exact=False).first.click(timeout=1500)
                        break
                    except Exception:
                        pass
                # attende che la rete si calmi, ma senza fallire se non succede
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                page.mouse.wheel(0, 3000)  # stimola eventuale lazy-load
                page.wait_for_timeout(4000)
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
            # in ogni caso, prendi quello che c'e' in pagina
            try:
                html = page.content()
            except Exception as e:
                error = (error or "") + f" | content() fallito: {e}"
            browser.close()
    except Exception as e:
        error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    return html, error


def _generic_extract(html: str, cinema_name: str) -> List[Movie]:
    """Estrazione 'best effort' generica: l'ultima intestazione (h1-h5)
    diventa il 'film corrente', e ogni testo HH:MM trovato dopo di essa
    diventa un suo orario con data 'da verificare'. Da ricalibrare."""
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
            movies.setdefault(current_title, Movie(title=current_title))
            continue
        if current_title:
            m = TIME_RE.match(text)
            if m:
                movies[current_title].showtimes.append(Showtime(
                    date="data-da-verificare",
                    time=f"{int(m.group(1)):02d}:{m.group(2)}",
                    cinema=cinema_name,
                    date_uncertain=True,
                ))
    # scarta le intestazioni senza orari (menu, footer, ecc.)
    return [m for m in movies.values() if m.showtimes]


def _scrape_generic(url: str, cinema_name: str) -> List[Movie]:
    html, error = _render_with_playwright(url)
    if error:
        print(f"   [!] Playwright {cinema_name}: {error.splitlines()[0]}")
    if html:
        DEBUG_PAGES[url] = html
    else:
        # nessun HTML: salva comunque l'errore, cosi' compare in docs/debug/
        DEBUG_PAGES[url] = f"<html><body><pre>ERRORE PLAYWRIGHT\n{error}</pre></body></html>"
        return []
    try:
        return _generic_extract(html, cinema_name)
    except Exception as e:
        print(f"   [!] Estrazione fallita per {cinema_name}: {e}")
        return []


def scrape_space_cinema(url: str, cinema_name: str) -> List[Movie]:
    return _scrape_generic(url, cinema_name)


def scrape_cinema_rex(url: str, cinema_name: str) -> List[Movie]:
    return _scrape_generic(url, cinema_name)
