"""Scraper per The Space Cinema (Limena) -
https://www.thespacecinema.it/cinema/limena/al-cinema

Calibrato sull'HTML reale della pagina renderizzata (ottobre 2026).

Come funziona il sito: e' un'app Next.js. Le schede dei film e gli orari
vengono caricati via JavaScript, e la pagina mostra SOLO il giorno
selezionato nella barra "Oggi / Domani / lun / mar ...". Gli altri giorni
si caricano cliccando i pulsanti della barra. Quindi serve un vero browser
(Playwright) che:
  1) apre la pagina e accetta il banner cookie
  2) legge il giorno gia' mostrato
  3) clicca uno per uno gli altri giorni e legge anche quelli
  4) unisce tutto (la stessa proiezione non viene mai contata due volte)

Struttura dell'HTML (verificata):
  div.showing-listing-item                     un film
    .film-heading__title                       titolo (MAIUSCOLO)
    a.film-heading[href]                       scheda del film
    .showing-film-card__poster img[src]        locandina
    dl.text-detail  (Cast / Durata "1 ora 41 min.")
    .film-attribute__name-value                etichette ("EXTRA", "EVENTO SPECIALE"...)
    .sessions__group-block[data-test="sessions-group-2026-10-03T00:00:00"]
        ul.sessions__list > li > a.session[href=link biglietti]
            time.session-time__start           ora ("14:05")
            .session-special-attributes__screen-name   "Sala 5"
            .session-special-attributes__label         "Proiezione LASER 4K"...
            .session-price-info__value                 "9,99 €"
        .sessions__group-midnight-sessions     "Proiezioni dopo mezzanotte":
            sono dentro il blocco del giorno, ma con ora 00:xx-05:xx:
            avvengono in realta' il giorno DOPO, e cosi' le registro.
  button.filter-dates-button[data-day="2026-10-04T00:00:00"]   i giorni
  (l'ultimo pulsante, data-day="All times", e' "Tutti i giorni": lo salto)

Non uso le API interne del sito (richiedono un token di sessione): il
browser fa esattamente quello che farebbe una persona.
"""
import datetime as dt
import re
import time
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import Movie, Showtime
from utils import DEBUG_PAGES, nice_title as _nice_title

ROME = ZoneInfo("Europe/Rome")

GROUP_RE = re.compile(r"sessions-group-(\d{4}-\d{2}-\d{2})T")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
PRICE_RE = re.compile(r"\d+[.,]\d{2}")
LINGUA_ORIG_RE = re.compile(r"\s*[-–]\s*lingua originale\s*$", re.I)
# --------------------------------------------------------------------------
# utilita'
# --------------------------------------------------------------------------
def _duration_min(text: str) -> Optional[int]:
    """'3 ore 5 min.' -> 185 | '1 ora 30 min.' -> 90 | '3 ore' -> 180 | 'TBC' -> None"""
    m = re.search(r"(?:(\d+)\s*or[ae])?\s*(?:(\d+)\s*min)?", text.replace("Durata", ""), re.I)
    if not m or not (m.group(1) or m.group(2)):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def _text(el) -> str:
    return " ".join(el.stripped_strings) if el else ""


# --------------------------------------------------------------------------
# parsing dell'HTML renderizzato
# --------------------------------------------------------------------------
def parse_listing(html: str, cinema_name: str) -> Dict[str, Movie]:
    """Estrae film e proiezioni da UNA versione della pagina (qualunque sia
    il giorno mostrato: ogni blocco porta la sua data). Ritorna {chiave: Movie}."""
    soup = BeautifulSoup(html, "html.parser")
    movies: Dict[str, Movie] = {}

    for item in soup.select("div.showing-listing-item"):
        title_el = item.select_one(".film-heading__title")
        if not title_el:
            continue
        raw_title = _text(title_el)
        original_lang = bool(LINGUA_ORIG_RE.search(raw_title))
        title = _nice_title(LINGUA_ORIG_RE.sub("", raw_title))

        link = item.select_one("a.film-heading")
        poster = item.select_one(".showing-film-card__poster img")
        poster_url = poster.get("src") if poster else None
        if poster_url and not poster_url.startswith("http"):
            poster_url = None  # nelle pagine salvate e' un percorso locale: inutile

        details = {}
        for dl in item.select("dl.text-detail"):
            k, v = dl.find("dt"), dl.find("dd")
            if k and v:
                details[_text(k)] = _text(v)
        cast = [c.strip() for c in details.get("Cast", "").split(",") if c.strip()]
        labels = [_text(x).title() for x in item.select(".film-attribute__name-value")]

        movie = Movie(
            title=title,
            cast=cast,
            duration_min=_duration_min(details.get("Durata", "")),
            poster_url=poster_url,
            detail_url=link.get("href") if link else None,
        )

        for group in item.select(".sessions__group-block"):
            gm = GROUP_RE.search(group.get("data-test", ""))
            if not gm:
                continue
            day = dt.date.fromisoformat(gm.group(1))

            for a in group.select("a.session"):
                tm = TIME_RE.search(_text(a.select_one(".session-time__start")))
                if not tm:
                    continue
                hour, minute = int(tm.group(1)), int(tm.group(2))
                after_midnight = a.find_parent(class_="sessions__group-midnight-sessions") is not None
                real_day = day + dt.timedelta(days=1) if after_midnight else day

                room = _text(a.select_one(".session-special-attributes__screen-name")) or None
                notes = list(labels)
                if original_lang:
                    notes.insert(0, "V.O.S.")
                notes += [_text(x) for x in a.select(".session-special-attributes__label")]
                if after_midnight:
                    notes.append(f"Dopo mezzanotte (serata del {day.strftime('%d/%m')})")
                pm = PRICE_RE.search(_text(a.select_one(".session-price-info__value")))

                movie.showtimes.append(Showtime(
                    date=real_day.strftime("%Y-%m-%d"),
                    time=f"{hour:02d}:{minute:02d}",
                    cinema=cinema_name,
                    price=f"da {pm.group().replace('.', ',')} €" if pm else None,
                    room=room,
                    note=" · ".join(dict.fromkeys(n for n in notes if n)) or None,
                    booking_url=a.get("href"),
                ))

        key = movie.norm_key()
        if key in movies:  # lo stesso film in due schede: riunisco
            movies[key].showtimes.extend(movie.showtimes)
        else:
            movies[key] = movie
    return movies


def merge_pages(pages: List[Dict[str, Movie]]) -> List[Movie]:
    """Unisce i risultati dei vari giorni scartando le proiezioni gia' viste
    (la stessa proiezione ha lo stesso link biglietti)."""
    merged: Dict[str, Movie] = {}
    seen = set()
    for page in pages:
        for key, movie in page.items():
            target = merged.setdefault(key, Movie(
                title=movie.title, cast=movie.cast, duration_min=movie.duration_min,
                poster_url=movie.poster_url, detail_url=movie.detail_url))
            target.poster_url = target.poster_url or movie.poster_url
            target.duration_min = target.duration_min or movie.duration_min
            for st in movie.showtimes:
                sig = (key, st.date, st.time, st.room, st.booking_url)
                if sig in seen:
                    continue
                seen.add(sig)
                target.showtimes.append(st)
    return [m for m in merged.values() if m.showtimes]


# --------------------------------------------------------------------------
# browser
# --------------------------------------------------------------------------
def _accept_cookies(page) -> None:
    for sel in ("#onetrust-accept-btn-handler", "button:has-text('Accetta tutti')",
                "button:has-text('Accetta')"):
        try:
            page.locator(sel).first.click(timeout=2500)
            page.wait_for_timeout(500)
            return
        except Exception:
            pass


RELOAD_AFTER_S = 25     # se la pagina resta bloccata cosi' a lungo, la ricarico
MAX_RELOADS = 2
LOAD_TIMEOUT_S = 100    # tempo massimo totale per ottenere l'elenco dei film
LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


def _launch(p):
    """Preferisco il Chromium 'completo' in nuova modalita' headless
    (channel="chromium"): per i controlli anti-bot e' molto meno riconoscibile
    della 'headless shell' predefinita di Playwright. Se non e' installato,
    ripiego su quella predefinita."""
    try:
        return p.chromium.launch(channel="chromium", args=LAUNCH_ARGS)
    except Exception as e:
        print(f"   [i] The Space: Chromium completo non disponibile ({type(e).__name__}), uso la headless shell")
        return p.chromium.launch(args=LAUNCH_ARGS)


def _natural_user_agent(browser) -> str:
    """User-Agent REALE del browser installato, senza la parola 'Headless'.
    Non ne invento uno: una versione di Chrome che non combacia con quella vera
    (e con gli header che il browser manda) e' proprio cio' che fa scattare i blocchi."""
    ctx = browser.new_context()
    try:
        return ctx.new_page().evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
    finally:
        ctx.close()


def _listing_ready(page) -> bool:
    try:
        return page.locator("div.showing-listing-item").count() > 0
    except Exception:
        return False  # pagina in navigazione/ricaricamento: riprovo


def _wait_for_listing(page, url: str) -> None:
    """Aspetta l'elenco dei film. Se invece la pagina resta ferma sul controllo
    anti-bot di Cloudflare ('Ci siamo quasi...', anche dopo 'Verifica riuscita'),
    la ricarica: il cookie di verifica ormai c'e' e il secondo caricamento passa."""
    start = last_nav = time.time()
    reloads = 0
    while time.time() - start < LOAD_TIMEOUT_S:
        if _listing_ready(page):
            return
        if time.time() - last_nav > RELOAD_AFTER_S and reloads < MAX_RELOADS:
            reloads += 1
            last_nav = time.time()
            print(f"   [i] The Space: pagina ancora ferma dopo {int(last_nav - start)}s, ricarico ({reloads}/{MAX_RELOADS})")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
        page.wait_for_timeout(2000)
    raise TimeoutError(f"elenco film non comparso entro {LOAD_TIMEOUT_S}s")


def _describe_page(page) -> str:
    """Titolo + inizio del testo visibile: finisce nel report e dice subito
    se si e' davanti a un blocco anti-bot o a una pagina vuota."""
    try:
        text = " ".join(page.inner_text("body").split())[:160]
        return f"titolo={page.title()!r} testo={text!r}"
    except Exception:
        return "(pagina non leggibile)"


def _collect_pages(url: str) -> List[str]:
    """Apre la pagina e restituisce l'HTML di ogni giorno (il primo e' quello
    mostrato all'apertura). Solleva RuntimeError se la pagina non si carica."""
    from playwright.sync_api import sync_playwright

    htmls: List[str] = []
    with sync_playwright() as p:
        browser = _launch(p)
        try:
            ctx = browser.new_context(user_agent=_natural_user_agent(browser), locale="it-IT",
                                      timezone_id="Europe/Rome",
                                      viewport={"width": 1366, "height": 900})
            ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                _wait_for_listing(page, url)
                _accept_cookies(page)
            except Exception as e:
                detail = _describe_page(page)
                try:  # salvo comunque quello che c'e', per la diagnostica
                    DEBUG_PAGES[url] = page.content()
                except Exception:
                    pass
                raise RuntimeError(f"pagina The Space non caricata: {type(e).__name__}: "
                                   f"{str(e).splitlines()[0]} | {detail}") from e

            page.wait_for_timeout(1500)  # lascia finire il caricamento degli orari
            htmls.append(page.content())

            # giorni disponibili: tutti i pulsanti con data-day = data vera
            days = [d for d in page.eval_on_selector_all(
                        "button.filter-dates-button", "els => els.map(e => e.dataset.day)")
                    if d and DAY_RE.match(d)]
            first_active = page.eval_on_selector(
                "button.filter-dates-button.active", "e => e.dataset.day") if days else None

            for day in days:
                if day == first_active:
                    continue  # gia' letto
                try:
                    page.locator(f'button.filter-dates-button[data-day="{day}"]').click(timeout=8000)
                    # attendo che compaia il blocco di QUEL giorno; se quel giorno
                    # non ha proiezioni, vado avanti dopo il timeout
                    try:
                        page.wait_for_selector(f'[data-test="sessions-group-{day}"]', timeout=8000)
                    except Exception:
                        pass
                    page.wait_for_timeout(800)
                    htmls.append(page.content())
                except Exception as e:
                    print(f"   [!] The Space: giorno {day[:10]} non letto ({type(e).__name__})")
        finally:
            browser.close()
    return htmls


# --------------------------------------------------------------------------
# punto di ingresso
# --------------------------------------------------------------------------
def scrape(url: str, cinema_name: str) -> List[Movie]:
    htmls = _collect_pages(url)
    DEBUG_PAGES[url] = htmls[0]  # il primo giorno, per la diagnostica
    pages = [parse_listing(h, cinema_name) for h in htmls]
    movies = merge_pages(pages)
    if not movies:
        raise RuntimeError("pagina caricata ma nessuna proiezione trovata (struttura cambiata?)")
    return movies
