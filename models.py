"""Modelli dati condivisi da tutti gli scraper."""
from dataclasses import dataclass, field
from typing import Optional, List
import re


@dataclass
class Showtime:
    date: str  # "YYYY-MM-DD"
    time: str  # "HH:MM"
    cinema: str
    price: Optional[str] = None
    room: Optional[str] = None
    note: Optional[str] = None  # es. "V.O.S.", "Ingresso 6,50 €"
    booking_url: Optional[str] = None
    date_uncertain: bool = False  # True se non siamo sicuri della data esatta


@dataclass
class Movie:
    title: str
    director: Optional[str] = None
    cast: List[str] = field(default_factory=list)
    duration_min: Optional[int] = None
    poster_url: Optional[str] = None
    trailer_url: Optional[str] = None          # link diretto (se lo troviamo con certezza)
    trailer_search_url: Optional[str] = None   # fallback: link di ricerca YouTube, sempre disponibile
    letterboxd_url: Optional[str] = None       # link di ricerca Letterboxd, sempre disponibile
    tmdb_url: Optional[str] = None             # link diretto alla scheda TMDB (richiede TMDB_API_KEY)
    detail_url: Optional[str] = None           # pagina del film sul sito del cinema
    showtimes: List[Showtime] = field(default_factory=list)

    def norm_key(self) -> str:
        """Chiave normalizzata per riconoscere lo stesso film su cinema diversi."""
        t = self.title.lower()
        t = re.sub(r"\(.*?\)", "", t)  # rimuove parentesi (es. anno, ried.)
        t = re.sub(r"[^a-z0-9]+", " ", t)
        return t.strip()
