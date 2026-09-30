"""Ricostruisce gli oggetti Movie da un docs/data.json gia' generato da un
run completo (main.py). Usato dal workflow "leggero" (update_events.py) per
poter ri-generare la pagina con gli eventi personalizzati aggiornati SENZA
dover ri-scaricare tutti i siti dei cinema ogni volta."""
import json
import os
from typing import List, Tuple

from custom_events import CustomEvent
from models import Movie, Showtime


def load_movies(path: str) -> List[Movie]:
    if not os.path.exists(path):
        print(f"[i] {path} non esiste ancora (nessun run completo precedente?): "
              f"partiamo con zero film.")
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movies = []
    for md in data.get("movies", []):
        m = Movie(
            title=md.get("title"),
            director=md.get("director"),
            duration_min=md.get("duration_min"),
            poster_url=md.get("poster_url"),
            trailer_url=md.get("trailer_url"),
            trailer_search_url=md.get("trailer_search_url"),
            letterboxd_url=md.get("letterboxd_url"),
            tmdb_url=md.get("tmdb_url"),
            detail_url=md.get("detail_url"),
        )
        for sd in md.get("showtimes", []):
            m.showtimes.append(Showtime(
                date=sd.get("date"), time=sd.get("time"), cinema=sd.get("cinema"),
                price=sd.get("price"), note=sd.get("note"),
                date_uncertain=bool(sd.get("date_uncertain")),
            ))
        movies.append(m)
    return movies


def load_generated_at(path: str) -> str:
    """Solo per messaggi diagnostici: quando risale l'ultimo run completo."""
    if not os.path.exists(path):
        return "mai"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("generated_at", "sconosciuto")
