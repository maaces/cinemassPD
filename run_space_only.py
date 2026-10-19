"""Aggiorna SOLO The Space Cinema (Limena), eseguendo lo scraper dal tuo PC.

Gli altri cinema restano com'erano nell'ultimo run completo (docs/data.json),
gli eventi personalizzati vengono riusati da data.json, e docs/ viene rigenerato.
Non fa commit ne' push: li fai tu con git, come descritto nel messaggio.

Uso (dalla cartella della repo):
    python run_space_only.py
"""
import json
import os
import sys
import traceback

import yaml

from custom_events import CustomEvent
from movies_from_json import load_movies
from render_html import render
from scrapers import space_cinema
from enrich_tmdb import enrich_movies
from utils import merge_movies, tidy_title

SPACE_NAME = "The Space (Limena)"
# nome precedente in data.json: le proiezioni salvate con questo nome vanno tolte, altrimenti restano duplicate
OLD_SPACE_NAMES = {"The Space Cinema (Limena)", SPACE_NAME}


def load_custom_events(data_path: str):
    """Rilegge gli eventi personalizzati dall'ultimo data.json: in locale non
    abbiamo il token GitHub per rileggere le Issue, e non vogliamo perderli."""
    if not os.path.exists(data_path):
        return []
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    events = []
    for ed in data.get("custom_events", []):
        events.append(CustomEvent(
            title=ed.get("title") or "Evento",
            text=ed.get("text") or "",
            date=ed.get("date"),
            time=ed.get("time"),
            photo_url=ed.get("photo_url"),
            flags=ed.get("flags") or [],
            source_url=ed.get("source_url"),
        ))
    return events


def _reuse_known_info(space_movies, previous) -> None:
    """Riempie i campi mancanti dei film di The Space con quelli gia' salvati in
    data.json per lo stesso film (stesso titolo normalizzato)."""
    known = {m.norm_key(): m for m in previous}
    for m in space_movies:
        old = known.get(m.norm_key())
        if not old:
            continue
        for f in ("poster_url", "tmdb_url", "director", "duration_min", "trailer_url",
                  "letterboxd_url", "trailer_search_url"):
            if not getattr(m, f) and getattr(old, f):
                setattr(m, f, getattr(old, f))


def main() -> int:
    base = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(base, "docs")
    data_path = os.path.join(out_dir, "data.json")

    with open(os.path.join(base, "config.yaml"), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    space_cfg = next(c for c in config["cinemas"] if c.get("type") == "space_cinema")

    # 1) The Space: scarico la programmazione dal browser del tuo PC
    print("-> Scraping The Space Cinema (Limena) ...")
    try:
        space_movies = space_cinema.scrape(space_cfg["url"], SPACE_NAME)
    except Exception as e:
        print(f"[ERRORE] The Space: {type(e).__name__}: {e}")
        traceback.print_exc()
        print("docs/ NON e' stato modificato.")
        return 1
    n_space = sum(len(m.showtimes) for m in space_movies)
    print(f"   trovati {len(space_movies)} film, {n_space} orari")
    if n_space == 0:
        print("docs/ NON e' stato modificato (nessun orario trovato).")
        return 1

    # 2) gli altri cinema: film dell'ultimo run completo, senza le vecchie proiezioni di The Space
    movies = load_movies(data_path)

    # 2b) locandina/regista/link gia' trovati in passato (da TMDB nel run in cloud)
    #     per gli stessi film: li riuso, cosi' non spariscono a ogni aggiornamento locale
    _reuse_known_info(space_movies, movies)
    tmdb_key = os.environ.get("TMDB_API_KEY") or config.get("tmdb_api_key")
    if tmdb_key:
        print("-> Completo con TMDB i dati mancanti di The Space ...")
    else:
        print("[i] Nessuna TMDB_API_KEY sul PC: i film nuovi di The Space avranno la locandina "
              "solo se il sito la fornisce (o dal prossimo run in cloud).")
    try:
        enrich_movies(space_movies, tmdb_key)
    except Exception as e:
        print(f"   [!] arricchimento TMDB non riuscito: {type(e).__name__}: {e}")

    for m in movies:
        m.showtimes = [s for s in m.showtimes if s.cinema not in OLD_SPACE_NAMES]
    movies = [m for m in movies if m.showtimes]
    merged = merge_movies([movies, space_movies])
    merged = merge_movies([merged], key=lambda m: m.tmdb_url or m.norm_key())
    for m in merged:
        m.title = tidy_title(m.title)
    print(f"   film totali in pagina: {len(merged)}")

    # 3) rigenero la pagina con gli eventi personalizzati gia' presenti
    custom_events = load_custom_events(data_path)
    print(f"   eventi personalizzati riusati: {len(custom_events)}")
    render(merged, custom_events, out_dir, cinemas_note="")
    print(f"-> Pagina aggiornata: {out_dir}/index.html")
    print("Ora committa e pusha docs/ (vedi le istruzioni).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
