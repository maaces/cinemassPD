"""Funzioni di utilità condivise da scraper e script principale."""
import re
import time
from typing import List, Optional

import requests

from models import Movie

# Pagine HTML grezze scaricate durante lo scraping del cinema corrente:
# main.py le salva (ripulite) in docs/debug/ per poter calibrare gli scraper.
DEBUG_PAGES = {}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",