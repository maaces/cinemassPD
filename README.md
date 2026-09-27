# Cinema Scraper

Raccoglie la programmazione di alcuni cinema, la mostra in una paginetta web
mobile-friendly, e permette di aggiungere le proiezioni che ti interessano al
Google Calendar (o come file .ics) con un tap. Pensato per essere lanciato
**quando vuoi tu**, dal telefono (Android o iPhone), senza bisogno di
server propri.

## Come funziona, in breve

1. Uno script Python (`main.py`) scarica la programmazione dai siti dei
   cinema configurati in `config.yaml`.
2. Se hai una chiave TMDB (gratuita), completa regista/durata/locandina/
   trailer quando il sito del cinema non li fornisce già.
3. Genera `docs/index.html`: una pagina con tutti i film, i loro orari, e
   per ognuno un pulsante "📅 Google Calendar" (apre l'app pre-compilata) e
   uno "⬇️ .ics" (per iPhone o altri calendari).
4. Tutto gira dentro **GitHub Actions** (gratis), non sul tuo telefono: lo
   lanci quando vuoi con un tap dall'app GitHub, e la pagina risultante è
   ospitata gratis da **GitHub Pages**.

Non serve tenere un PC acceso, non serve Termux, non serve Playwright sul
telefono: il lavoro pesante lo fa il server di GitHub.

## Setup (una tantum)

### 1. Crea il repository
1. Vai su [github.com/new](https://github.com/new), crea un repository
   (può essere privato).
2. Carica dentro tutti i file di questo progetto (via web upload, oppure
   `git init && git add . && git commit -m "init" && git push`).

### 2. (Consigliato) Ottieni una chiave TMDB
Serve per completare regista/durata/locandina/trailer quando mancano.
Gratis: registrati su [themoviedb.org](https://www.themoviedb.org/signup),
poi in *Impostazioni → API* richiedi una "API key (v3 auth)".

Nel repository GitHub: **Settings → Secrets and variables → Actions →
New repository secret** → nome `TMDB_API_KEY`, valore la chiave ottenuta.

Se salti questo passaggio, tutto funziona lo stesso: mancheranno solo
regista/durata per i cinema che non li pubblicano già loro (Cineplex
Moderno li dà già di suo, ad esempio).

### 3. Abilita GitHub Pages
**Settings → Pages → Build and deployment → Source: "Deploy from a
branch"** → branch `main`, cartella `/docs` → Save.
Dopo il primo run vedrai l'URL della tua pagina lì (tipo
`https://tuonome.github.io/tuorepo/`).

### 4. Primo avvio
**Actions → "Aggiorna programmazione cinema" → Run workflow** (pulsante in
alto a destra). Aspetta un minuto, poi apri l'URL di GitHub Pages.

## Uso quotidiano, dal telefono

Su Android e iPhone: apri l'app **GitHub** → il tuo repo → tab *Actions* →
"Aggiorna programmazione cinema" → **Run workflow**. Quando l'icona diventa
verde, apri il link della pagina (conviene salvarlo come segnalibro/icona
sulla home). Ogni film mostra i suoi orari con i pulsanti per aggiungerli
al calendario — esattamente il tipo di aggiornamento "on demand" che
volevi, senza automatismi in background.

## Limiti noti (importante)

- **The Space Cinema (Limena)** e **Cinema Rex**: i loro orari sono
  caricati via JavaScript dopo il caricamento della pagina, quindi non sono
  visibili a un semplice scraper HTTP. Per supportarli servirebbe
  aggiungere **Playwright** (browser headless) al workflow — fattibile su
  GitHub Actions (impossibile invece su Termux/telefono), ma non incluso in
  questa prima versione per tenerla semplice. Se vuoi, è il prossimo passo
  naturale.
- **Fronte del Porto Padova**: il sito dichiara esplicitamente nel suo
  `robots.txt` di non voler essere letto da bot automatici. Ho scelto di
  non includerlo per rispetto di quella policy; se gestisci tu quel sito o
  hai un accordo per l'accesso, si può aggiungere.
- **MovieConnection (il Lux)**: struttura statica e semplice da leggere, ma
  non ancora collegata a uno scraper dedicato in questa v1 — si può
  aggiungere facilmente su richiesta.
- **Selettori "best effort"**: gli scraper di Multiastra/Porto Astra
  (file `scrapers/wp_remotefilm.py`) individuano i giorni tramite le "tab"
  del sito assumendo una struttura comune (Bootstrap); se al primo vero
  avvio qualcosa risultasse mancante o con date sbagliate, usa
  `python tools/debug_dump.py <url> dump.html` per salvare l'HTML reale e
  mandamelo: sistemo i selettori in pochi minuti.
- Se un film compare su più cinema, viene unito in un'unica scheda con
  tutti gli orari (il confronto è per titolo normalizzato).

## Aggiungere un altro cinema della stessa piattaforma

Se trovi un altro cinema che usa `18tickets`/`18months.it` (stessa
struttura di Cineplex Moderno) o lo stesso plugin WordPress "remotefilm"
(stessa struttura di Multiastra/Porto Astra), basta aggiungere una voce in
`config.yaml`:

```yaml
  - name: "Nome Cinema"
    type: tickets18        # oppure wp_remotefilm
    url: "https://..."
    enabled: true
```

## Uso in locale (facoltativo, per test)

```bash
pip install -r requirements.txt
export TMDB_API_KEY=xxxxx   # opzionale
python main.py
# apri docs/index.html nel browser
```

## Idea futura: display fisico con l'ESP32

Ogni esecuzione scrive anche `docs/data.json` con tutti i dati in formato
semplice — pensato apposta per essere lo trovarti facile da far scaricare a
un ESP32 (via HTTPS, con `WiFiClientSecure` + un parser JSON leggero come
ArduinoJson) e mostrare su un piccolo display OLED/e-ink la programmazione
di stasera, senza che il microcontrollore debba fare scraping o parsing
HTML.
