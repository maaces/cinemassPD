"""Eventi personalizzati: foto + testo libero + data/ora, caricati da te
usando le Issue di GitHub come "casella di posta" (nessun backend da gestire).

Come aggiungerne uno dal telefono (Android o iPhone), passo per passo:
  1. Nel repository, una volta sola: Issues -> Labels -> New label -> crea
     una label chiamata esattamente "evento".
  2. Apri l'app GitHub -> il tuo repository -> tab Issues -> icona "+".
  3. Titolo: una breve descrizione (es. "Proiezione speciale in giardino").
  4. Corpo (Description): sulla PRIMA RIGA scrivi data e ora nel formato
         GG/MM/AAAA HH:MM        (es. 30/09/2026 20:30)
     Dalla seconda riga in poi scrivi quello che vuoi (testo libero).
     Poi tocca l'icona della fotocamera/galleria per allegare una foto:
     GitHub la carica e la mostra automaticamente nel corpo della issue.
  5. Aggiungi la label "evento" alla issue e pubblicala.
  6. Al prossimo "Run workflow" l'evento comparira' nella pagina, nella
     posizione cronologica corretta insieme ai film.

Per toglierlo dalla pagina puoi chiudere la issue a mano, oppure non fare
nulla: gli eventi il cui orario e' gia' passato (con un margine di 2 ore)
vengono chiusi automaticamente in automatico al primo aggiornamento
successivo alla data dell'evento.
"""
import datetime as dt
import os
import re
from dataclasses import dataclass
from typing import List, Optional
from zoneinfo import ZoneInfo

import requests

from calendar_links import DEFAULT_DURATION_MIN

ROME = ZoneInfo("Europe/Rome")
DATE_TIME_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2})[:.](\d{2})")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")


@dataclass
class CustomEvent:
    title: str
    text: str
    date: Optional[str]   # "YYYY-MM-DD"
    time: Optional[str]   # "HH:MM"
    photo_url: Optional[str]
    source_url: Optional[str] = None


def _is_past(date_str: Optional[str], time_str: Optional[str]) -> bool:
    """Un evento e' considerato passato quando e' trascorso il suo orario
    di inizio + 5 ore (margine per consentire di completare l'evento/serata),
    cosi' resta visibile anche durante e subito dopo l'evento."""
    if not date_str or not time_str:
        return False  # senza orario non possiamo saperlo: lo teniamo
    try:
        y, mo, d = (int(x) for x in date_str.split("-"))
        h, mi = (int(x) for x in time_str.split(":"))
    except ValueError:
        return False
    start = dt.datetime(y, mo, d, h, mi, tzinfo=ROME)
    end = start + dt.timedelta(hours=5)  # 5 ore di margine
    return end < dt.datetime.now(ROME)


def _close_issue(repo: str, token: str, issue_number: int, title: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.patch(url, headers=headers, json={"state": "closed"}, timeout=15)
        if r.ok:
            print(f"[i] Issue #{issue_number} '{title}' e' nel passato: chiusa automaticamente.")
        else:
            print(f"[!] Non sono riuscito a chiudere la issue #{issue_number}: {r.status_code}")
    except requests.RequestException as e:
        print(f"[!] Non sono riuscito a chiudere la issue #{issue_number}: {e}")


def fetch_custom_events(label: str = "evento") -> List[CustomEvent]:
    """Legge le issue aperte con la label indicata. Richiede GITHUB_TOKEN e
    GITHUB_REPOSITORY, entrambe impostate automaticamente da GitHub Actions:
    in locale (senza Actions) restituisce semplicemente una lista vuota."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return []

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/issues"
    params = {"state": "open", "labels": label, "per_page": 100}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        issues = r.json()
    except requests.RequestException as e:
        print(f"[!] Impossibile leggere le issue per gli eventi personalizzati: {e}")
        return []

    events = []
    for issue in issues:
        if "pull_request" in issue:
            continue  # l'endpoint /issues restituisce anche le pull request
        body = issue.get("body") or ""
        lines = body.splitlines()
        date_str = time_str = None
        rest = body

        if lines:
            m = DATE_TIME_RE.search(lines[0])
            if m:
                gg, mm, aaaa, hh, mi = m.groups()
                date_str = f"{aaaa}-{mm}-{gg}"
                time_str = f"{int(hh):02d}:{mi}"
                rest = "\n".join(lines[1:])
            else:
                print(f"[!] Issue #{issue.get('number')} '{issue.get('title')}': "
                      f"prima riga senza data/ora nel formato GG/MM/AAAA HH:MM, "
                      f"la mostro senza orario (finira' in fondo alla pagina).")

        img_match = IMAGE_RE.search(body)
        photo_url = img_match.group(1) if img_match else None
        text = IMAGE_RE.sub("", rest).strip()

        if _is_past(date_str, time_str):
            _close_issue(repo, token, issue["number"], issue.get("title") or "Evento")
            continue  # non lo includiamo in questo aggiornamento della pagina

        events.append(CustomEvent(
            title=issue.get("title") or "Evento",
            text=text,
            date=date_str,
            time=time_str,
            photo_url=photo_url,
            source_url=issue.get("html_url"),
        ))
    return events
