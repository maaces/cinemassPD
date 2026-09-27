"""Script principale: legge config.yaml, lancia gli scraper abilitati,
unisce i risultati, li arricchisce (TMDB) e genera la pagina in docs/."""
import os

import yaml

from enrich_tmdb import enrich_movies
from render_html import render
from scrapers import tickets18, wp_remotefilm
from utils import merge_movies

SCRAPER_MAP = {
    "tickets18": tickets18.scrape,
    "wp_remotefilm": wp_remotefilm.scrape,
}


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    config = load_config()
    tmdb_key = os.environ.get("TMDB_API_KEY") or config.get("tmdb_api_key")

    all_movies = []
    notes = []
    for cinema in config.get("cinemas", []):
        if not cinema.get("enabled", True):
            continue
        scraper = SCRAPER_MAP.get(cinema["type"])
        if not scraper:
            print(f"[!] Tipo di scraper sconosciuto per {cinema['name']}: {cinema['type']}")
            continue
        print(f"-> Scraping {cinema['name']} ({cinema['url']}) ...")
        try:
            movies = scraper(cinema["url"], cinema["name"])
            print(f"   trovati {len(movies)} film")
            all_movies.append(movies)
        except Exception as e:  # uno scraper rotto non deve bloccare gli altri
            print(f"   [ERRORE] {cinema['name']}: {e}")
            notes.append(f"{cinema['name']}: errore durante l'aggiornamento")

    merged = merge_movies(all_movies)
    print(f"Totale film unici: {len(merged)}")

    if tmdb_key:
        print("-> Arricchimento dati con TMDB ...")
    else:
        print("[i] Nessuna TMDB_API_KEY impostata: regista/durata/locandina mancanti "
              "resteranno vuoti se il sito del cinema non li fornisce gia'.")
    enrich_movies(merged, tmdb_key)  # imposta comunque i link Letterboxd anche senza chiave

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    render(merged, out_dir, cinemas_note=" ".join(notes))
    print(f"-> Pagina generata in {out_dir}/index.html")


if __name__ == "__main__":
    main()
