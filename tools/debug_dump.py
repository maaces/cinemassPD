"""Strumento di calibrazione: scarica l'HTML grezzo di una pagina e lo salva
su disco. Utile se uno scraper smette di funzionare dopo che un sito cambia
struttura: ispeziona il file (o incollalo/allegalo in chat a Claude) per
sistemare i selettori in scrapers/*.py.

Uso:
    python tools/debug_dump.py https://multiastra.it/ dump_multiastra.html
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import get_session, polite_get  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python tools/debug_dump.py <url> [file_output.html]")
        sys.exit(1)
    url = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "dump.html"
    session = get_session()
    resp = polite_get(session, url, delay=0)
    with open(out, "w", encoding="utf-8") as f:
        f.write(resp.text)
    print(f"Salvato in {out} ({len(resp.text)} caratteri)")


if __name__ == "__main__":
    main()
