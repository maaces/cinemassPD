"""Eventi personalizzati: foto + testo libero + data/ora, caricati da te
usando le Issue di GitHub come "casella di posta" (nessun backend da gestire).

Come aggiungerne uno dal telefono (Android o iPhone), passo per passo:
  1. Nel repository, una volta sola: Issues -> Labels -> New label -> crea
     una label chiamata esattamente "evento".
  2. Apri l'app GitHub -> il tuo repository -> tab Issues -> icona "+".
  3. Titolo: una breve descrizione (es. "Proiezione speciale in giardino").
  4. Corpo (Description): sulla PRIMA RIGA scrivi data e ora nel formato
         GG/MM/AAAA HH:MM        (es. 30/09/2026 20:30)
     Dalla seconda riga in poi scrivi quello che vuoi, poi allega una foto.
  5. Aggiungi la label "evento" alla issue. Puoi aggiungere ANCHE altre
     label a piacere (es. "famiglia", "speciale"): diventano "flag"
     selezionabili nei filtri della pagina.
  6. Pubblica la issue. Al prossimo aggiornamento comparira' nella pagina.

Per toglierlo dalla pagina puoi chiudere la issue a mano, oppure non fare
nulla: gli eventi il cui orario e' gia' passato (con un margine di 5 ore)
vengono chiusi automaticamente al primo aggiornamento successivo.

NOTA SULLE FOTO: GitHub inserisce l'immagine caricata in una di tre forme
diverse a seconda di come l'hai allegata (app mobile, trascinamento nel
browser, copia-incolla nel browser):
  1. markdown:  ![qualcosa](https://...)
  2. tag HTML:  <img src="https://..." ...>
  3. link semplice (raro): [qualcosa](https://....jpg)
Le cerchiamo tutte e tre, in questo ordine, sia nel corpo della issue sia
nei commenti successivi (nel caso l'avessi aggiunta dopo la creazione).
"""
import datetime as dt
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional
from zoneinfo import ZoneInfo

import requests

from calendar_links import DEFAULT_DURATION_MIN

ROME = ZoneInfo("Europe/Rome")
DATE_TIME_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2})[:.](\d{2})")

IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")
IMAGE_HTML_RE = re.compile(r'<img\b[^>]*?src=["\'](https?://[^"\']+)["\'][^>]*>', re.IGNORECASE)
IMAGE_LINK_RE = re.compile(
    r"(?<!!)\[[^\]]*\]\((https?://[^)\s]+\.(?:png|jpe?g|gif|webp|heic|heif))\)", re.IGNORECASE
)


@dataclass
class CustomEvent:
    title: str
    text: str
    date: Optional[str]   # "YYYY-MM-DD"
    time: Optional[str]   # "HH:MM"
    photo_url: Optional[str]
    flags: List[str] = field(default_factory=list)
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
    end = start + dt.timedelta(hours=5)
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


def _find_first_image(*texts: str) -> Optional[str]:
    """Cerca un'immagine nelle forme markdown / HTML / link semplice, nel
    primo testo (tra quelli passati, nell'ordine dato) in cui la trova."""
    for text in texts:
        if not text:
            continue
        for pattern in (IMAGE_MD_RE, IMAGE_HTML_RE, IMAGE_LINK_RE):
            m = pattern.search(text)
            if m:
                return m.group(1)
    return None


def _strip_images(text: str) -> str:
    text = IMAGE_MD_RE.sub("", text)
    text = IMAGE_HTML_RE.sub("", text)
    text = IMAGE_LINK_RE.sub("", text)
    return text


def _fetch_comments(repo: str, token: str, issue_number: int) -> List[str]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    try:
        r = requests.get(url, headers=headers, params={"per_page": 100}, timeout=15)
        r.raise_for_status()
        return [c.get("body") or "" for c in r.json()]
    except requests.RequestException as e:
        print(f"[!] Impossibile leggere i commenti della issue #{issue_number}: {e}")
        return []


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
        number = issue.get("number")
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
                print(f"[!] Issue #{number} '{issue.get('title')}': prima riga senza data/ora "
                      f"nel formato GG/MM/AAAA HH:MM, la mostro senza orario "
                      f"(finira' in fondo alla pagina).")

        comments = _fetch_comments(repo, token, number) if number else []
        photo_url = _find_first_image(body, *comments)
        text = _strip_images(rest).strip()

        flags = [lbl.get("name") for lbl in issue.get("labels", [])
                 if lbl.get("name") and lbl.get("name") != label]

        if _is_past(date_str, time_str):
            _close_issue(repo, token, number, issue.get("title") or "Evento")
            continue  # non lo includiamo in questo aggiornamento della pagina

        events.append(CustomEvent(
            title=issue.get("title") or "Evento",
            text=text,
            date=date_str,
            time=time_str,
            photo_url=photo_url,
            flags=flags,
            source_url=issue.get("html_url"),
        ))
    return events
