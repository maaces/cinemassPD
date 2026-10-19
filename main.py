"""Script principale: legge config.yaml, lancia gli scraper abilitati,
unisce i risultati, li arricchisce (TMDB) e genera la pagina in docs/.

In piu' scrive una diagnostica in docs/debug/:
  - report.txt: per ogni cinema quanti film/orari sono stati trovati, quanti
    con data non riconosciuta, eventuali errori
  - <cinema>.txt: l'HTML ripulito della pagina scaricata (serve a calibrare
    gli scraper senza dover ispezionare i siti a mano)
"""
import datetime as dt
import os
import re
import traceback
from zoneinfo import ZoneInfo

import yaml

from custom_events import fetch_custom_events
from enrich_tmdb import enrich_movies
from render_html import render
from scrapers import (tickets18, wp_remotefilm, movieconnection, fronte_del_porto,
                      space_cinema, cinema_rex, esperia, piccolo)
from utils import DEBUG_PAGES, clean_html_for_dump, merge_movies, tidy_title
from models import Movie
from movies_from_json import load_movies

# space_cinema usa Playwright (importato solo quando serve); cinema_rex legge
# un JSON con una semplice richiesta HTTP e usa Playwright solo come ripiego.
SCRAPER_MAP = {
    "tickets18": tickets18.scrape,
    "wp_remotefilm": wp_remotefilm.scrape,
    "movieconnection": movieconnection.scrape,
    "fronte_del_porto": fronte_del_porto.scrape,
    "space_cinema": space_cinema.scrape,
    "playwright": space_cinema.scrape,   # vecchio nome in config.yaml, ancora valido
    "cinema_rex": cinema_rex.scrape,
    "esperia": esperia.scrape,
    "piccolo": piccolo.scrape,
}


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "cinema"


def _pages_base_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def _previous_showtimes(previous, cinema_name: str) -> list:
    """Le proiezioni di un cinema prese dall'ultimo run riuscito (docs/data.json).
    Servono quando lo scraper di quel cinema fallisce: meglio tenere gli orari
    gia' noti che far sparire il cinema dalla pagina. Le date passate vengono
    comunque nascoste da render_html."""
    out = []
    for pm in previous:
        sts = [s for s in pm.showtimes if s.cinema == cinema_name]
        if sts:
            out.append(Movie(title=pm.title, director=pm.director, duration_min=pm.duration_min,
                             poster_url=pm.poster_url, trailer_url=pm.trailer_url,
                             trailer_search_url=pm.trailer_search_url,
                             letterboxd_url=pm.letterboxd_url, tmdb_url=pm.tmdb_url,
                             detail_url=pm.detail_url, showtimes=sts))
    return out


def main() -> None:
    config = load_config()
    tmdb_key = os.environ.get("TMDB_API_KEY") or config.get("tmdb_api_key")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    debug_dir = os.path.join(out_dir, "debug")
    os.makedirs(debug_dir, exist_ok=True)
    base = _pages_base_url()

    previous = load_movies(os.path.join(out_dir, "data.json"))
    all_movies = []
    empty_cinemas = []
    reused_cinemas = []
    report = [f"Report generato il {dt.datetime.now(ZoneInfo('Europe/Rome')).strftime('%d/%m/%Y %H:%M')} (ora italiana)",
              "=" * 60]

    for cinema in config.get("cinemas", []):
        if not cinema.get("enabled", True):
            continue
        name = cinema["name"]
        scraper = SCRAPER_MAP.get(cinema["type"])
        if not scraper:
            msg = f"tipo di scraper sconosciuto o non disponibile: {cinema['type']}"
            print(f"[!] {name}: {msg}")
            report += [f"\n## {name}", f"URL: {cinema['url']}", f"STATO: NON ESEGUITO ({msg})"]
            empty_cinemas.append(name)
            continue

        if cinema.get("local_only"):
            # aggiornato dal PC (run_space_only.py): qui riprendo gli orari gia' salvati
            movies = _previous_showtimes(previous, name)
            n_local = sum(len(m.showtimes) for m in movies)
            print(f"-> {name}: aggiornato in locale, riprendo {n_local} proiezioni salvate")
            all_movies.append(movies)
            report += [f"\n## {name}", f"URL: {cinema['url']}",
                       f"STATO: aggiornato in locale (run_space_only.py), {n_local} orari salvati"]
            continue

        print(f"-> Scraping {name} ({cinema['url']}) ...")
        DEBUG_PAGES.clear()
        movies, error = [], None
        reused = False
        try:
            movies = scraper(cinema["url"], name)
        except Exception as e:  # uno scraper rotto non deve bloccare gli altri
            error = f"{type(e).__name__}: {e}"
            print(f"   [ERRORE] {name}: {error}")
            traceback.print_exc()
            # niente risultati nuovi: tengo gli orari dell'ultimo run riuscito
            movies = _previous_showtimes(previous, name)
            reused = bool(movies)
            if reused:
                reused_cinemas.append(name)
                print(f"   uso gli orari dell'ultimo aggiornamento riuscito di {name}")

        n_showtimes = sum(len(m.showtimes) for m in movies)
        n_uncertain = sum(1 for m in movies for s in m.showtimes
                          if s.date_uncertain or s.date == "data-da-verificare")
        print(f"   trovati {len(movies)} film, {n_showtimes} orari ({n_uncertain} con data non riconosciuta)")
        all_movies.append(movies)
        if n_showtimes == 0:
            empty_cinemas.append(name)

        # dump ripulito delle pagine scaricate
        dump_files = []
        for i, (url, html_text) in enumerate(DEBUG_PAGES.items()):
            fname = f"{_slug(name)}{'' if i == 0 else f'-{i + 1}'}.txt"
            try:
                with open(os.path.join(debug_dir, fname), "w", encoding="utf-8") as f:
                    f.write(clean_html_for_dump(html_text))
                dump_files.append(f"{base}debug/{fname}" if base else f"debug/{fname}")
            except Exception as e:
                print(f"   [!] dump non riuscito per {url}: {e}")

        report += [
            f"\n## {name}",
            f"URL: {cinema['url']}",
            f"Scraper: {cinema['type']}",
            f"Film trovati: {len(movies)}",
            f"Orari trovati: {n_showtimes} (di cui con data non riconosciuta: {n_uncertain})",
            f"Errore: {error or 'nessuno'}" + (" (orari presi dall'ultimo aggiornamento riuscito)" if reused else ""),
            "HTML ripulito: " + (", ".join(dump_files) if dump_files else "non disponibile"),
        ]

    # il report va scritto SUBITO: se un passaggio successivo fallisse,
    # la diagnostica dei cinema resterebbe comunque disponibile
    with open(os.path.join(debug_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")

    merged = merge_movies(all_movies)
    print(f"Totale film unici: {len(merged)}")

    if tmdb_key:
        print("-> Arricchimento dati con TMDB ...")
    else:
        print("[i] Nessuna TMDB_API_KEY impostata: regista/durata/locandina mancanti "
              "resteranno vuoti se il sito del cinema non li fornisce gia'.")
    try:
        enrich_movies(merged, tmdb_key)
    except Exception as e:
        print(f"   [ERRORE] arricchimento TMDB: {type(e).__name__}: {e}")
        traceback.print_exc()

    # stesso film scritto in modo diverso da due cinema ma ritrovato su TMDB con
    # lo stesso ID: lo unisco in una sola scheda
    merged = merge_movies([merged], key=lambda m: m.tmdb_url or m.norm_key())
    for m in merged:
        m.title = tidy_title(m.title)
    print(f"Totale film unici dopo TMDB: {len(merged)}")

    print("-> Lettura eventi personalizzati (Issue GitHub con label 'evento') ...")
    try:
        custom_events = fetch_custom_events()
    except Exception as e:
        print(f"   [ERRORE] eventi personalizzati: {type(e).__name__}: {e}")
        traceback.print_exc()
        custom_events = []
    print(f"   trovati {len(custom_events)} eventi personalizzati")

    note = ""
    if empty_cinemas:
        note = "Nessun orario trovato per: " + ", ".join(empty_cinemas) + "."
    if reused_cinemas:
        note += (" Orari di " + ", ".join(reused_cinemas) +
                 " ripresi dall'ultimo aggiornamento riuscito.").strip()
    render(merged, custom_events, out_dir, cinemas_note=note)
    print(f"-> Pagina generata in {out_dir}/index.html")


if __name__ == "__main__":
    main()
