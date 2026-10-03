"""Lettura di date e orari scritti in italiano a testo libero, come li
scrivono Esperia e Piccolo Teatro:

    "VENERDI 2 Ottobre - ore 21.00, DOMENICA 4 Ottobre - ore 18.30"
    "sabato 3 ottobre ore 21.15 domenica 4 ottobre ore 18.45 e 21.15"
    "SABATO 3 ottobre - ore 21:00 - DOMENICA 4 ottobre ore 21:00"

Regole (volutamente semplici e prudenti):
  - una data e' "<giorno> <nome del mese>" (il nome del giorno della settimana
    NON serve: sul sito ci sono refusi tipo "mercoldi'")
  - un orario e' valido solo se preceduto da "ore" (cosi' i prezzi "6.00 euro"
    non vengono scambiati per orari); dopo il primo, "e 21.15" / ", 21.15"
    aggiungono altri orari alla stessa data
  - ogni orario appartiene all'ULTIMA data letta prima di lui
  - l'anno non c'e': e' quello corrente, oppure il prossimo se la data
    sarebbe piu' di ~6 mesi nel passato
"""
import datetime as dt
import re
from typing import List, Optional, Tuple

MONTHS = {
    "gennaio": 1, "gen": 1, "febbraio": 2, "feb": 2, "marzo": 3, "mar": 3,
    "aprile": 4, "apr": 4, "maggio": 5, "mag": 5, "giugno": 6, "giu": 6,
    "luglio": 7, "lug": 7, "agosto": 8, "ago": 8, "settembre": 9, "set": 9, "sett": 9,
    "ottobre": 10, "ott": 10, "novembre": 11, "nov": 11, "dicembre": 12, "dic": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))

_DATE = rf"(?P<day>\d{{1,2}})\s*°?\s*(?P<month>{_MONTH_ALT})\b\.?"
_TIME = (r"ore\s*(?P<h>\d{1,2})(?:[.:](?P<m>\d{2}))?"
         r"(?P<more>(?:\s*(?:,|e|/)\s*(?:alle\s+)?(?:ore\s+)?\d{1,2}[.:]\d{2})*)")
TOKEN_RE = re.compile(rf"(?P<date>{_DATE})|(?P<time>{_TIME})", re.I)
EXTRA_TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})")


def _resolve_year(day: int, month: int, today: dt.date) -> Optional[dt.date]:
    try:
        d = dt.date(today.year, month, day)
    except ValueError:
        return None
    if (today - d).days > 180:  # es. oggi a dicembre, data "10 gennaio"
        try:
            d = dt.date(today.year + 1, month, day)
        except ValueError:
            return None
    return d


def parse_showtimes(text: str, today: Optional[dt.date] = None) -> List[Tuple[dt.date, str]]:
    """Ritorna [(data, 'HH:MM'), ...] senza doppioni, in ordine di comparsa."""
    today = today or dt.date.today()
    out: List[Tuple[dt.date, str]] = []
    current: Optional[dt.date] = None
    for m in TOKEN_RE.finditer(text):
        if m.group("date"):
            current = _resolve_year(int(m.group("day")), MONTHS[m.group("month").lower()], today)
        elif m.group("time") and current:
            times = [(int(m.group("h")), int(m.group("m") or 0))]
            times += [(int(h), int(mi)) for h, mi in EXTRA_TIME_RE.findall(m.group("more") or "")]
            for h, mi in times:
                if 0 <= h < 24 and 0 <= mi < 60:
                    item = (current, f"{h:02d}:{mi:02d}")
                    if item not in out:
                        out.append(item)
    return out
