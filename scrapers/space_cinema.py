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
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import Movie, Showtime
from utils import DEBUG_PAGES

ROME = ZoneInfo("Europe/Rome")
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

GROUP_RE = re.compile(r"sessions-group-(\d{4}-\d{2}-\d{2})T")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
PRICE_RE = re.compile(r"\d+[.,]\d{2}")
LINGUA_ORIG_RE = re.compile(r"\s*[-–]\s*lingua originale\s*$", re.I)
SMALL_WORDS = {"di", "del", "dei", "della", "delle", "dello", "degli", "da", "dal", "dai",
               "il", "lo", "la", "le", "i", "gli", "un", "una", "e", "ed", "a", "al", "ai",
               "in", "nel", "nei", "nella", "su", "sul", "per", "con", "tra", "fra", "o"}


# --------------------------------------------------------------------------
# utilita'
# --------------------------------------------------------------------------
def _nice_title(raw: str) -> str:
    """The Space scrive i titoli TUTTI MAIUSCOLI. Li riporto in maiuscole/
    minuscole normali (così nella pagina si leggono bene e coincidono con
    gli stessi film degli altri cinema). Titoli gia' misti restano intatti."""
    t = " ".join(raw.split())
    if not t.isupper():
        return t
    out = []
    start = True  # inizio titolo o dopo ':' / ' - '
    for w in t.split(" "):
        low = w.lower()
        if any(c.isdigit() for c in w) or (len(w) > 1 and "." in w.strip(".")):
            out.append(w)  # 20MO, S.W.A.T. ecc.: lascio com'e'
        elif low in SMALL_WORDS and not start:
            out.append(low)
        else:
            # maiuscola dopo l'apostrofo (L'Isola) e dopo il trattino (Spider-Man)
            out.append(re.sub(r"(^|['’\-])([^\W\d_])",
                              lambda m: m.group(1) + m.group(2).upper(), low))
        start = w.endswith(":") or w in ("-", "–")
    return " ".join(out)


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


def _collect_pages(url: str) -> List[str]:
    """Apre la pagina e restituisce l'HTML di ogni giorno (il primo e' quello
    mostrato all'apertura). Solleva RuntimeError se la pagina non si carica."""
    from playwright.sync_api import sync_playwright

    htmls: List[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        try:
            ctx = browser.new_context(user_agent=BROWSER_UA, locale="it-IT",
                                      timezone_id="Europe/Rome",
                                      viewport={"width": 1366, "height": 900})
            ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                _accept_cookies(page)
                page.wait_for_selector("div.showing-listing-item", timeout=40000)
            except Exception as e:
                try:  # salvo comunque quello che c'e', per la diagnostica
                    DEBUG_PAGES[url] = page.content()
                except Exception:
                    pass
                raise RuntimeError(f"pagina The Space non caricata: {type(e).__name__}: "
                                   f"{str(e).splitlines()[0]}") from e

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
