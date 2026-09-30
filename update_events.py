"""Aggiornamento "leggero": rilegge gli eventi personalizzati dalle Issue
GitHub e rigenera la pagina, riusando i film dell'ultimo run completo
(docs/data.json) senza ri-scaricare i siti dei cinema. Pensato per essere
lanciato spesso (ogni 30 minuti) senza sprecare richieste verso i siti dei
cinema ne' chiamate TMDB. Vedi .github/workflows/check-events.yml.
"""
import os

from custom_events import fetch_custom_events
from movies_from_json import load_generated_at, load_movies
from render_html import render


def main() -> None:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(base_dir, "docs")
    data_path = os.path.join(out_dir, "data.json")

    print(f"-> Riuso i film dell'ultimo run completo (generato il: {load_generated_at(data_path)})")
    movies = load_movies(data_path)
    print(f"   {len(movies)} film in cache")

    print("-> Lettura eventi personalizzati (Issue GitHub con label 'evento') ...")
    custom_events = fetch_custom_events()
    print(f"   trovati {len(custom_events)} eventi personalizzati")

    render(movies, custom_events, out_dir, cinemas_note="")
    print(f"-> Pagina rigenerata in {out_dir}/index.html")


if __name__ == "__main__":
    main()
