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

## Aggiungere una foto/promemoria tuo (con data, ora e testo libero)

Usiamo le **Issue di GitHub** come casella di posta, così puoi farlo dal
telefono senza bisogno di alcun backend:

1. Una volta sola: nel repository vai su *Issues → Labels → New label* e
   crea una label chiamata esattamente `evento`.
2. Dall'app GitHub (Android o iPhone): apri il repo → tab *Issues* → **+**.
3. Titolo: una breve descrizione (es. "Proiezione speciale in giardino").
4. Nel corpo, **sulla prima riga** scrivi data e ora così:
   `GG/MM/AAAA HH:MM` (es. `30/09/2026 20:30`). Dalla riga successiva in poi
   scrivi il testo libero che vuoi, poi allega una foto dalla libreria
   (basta trascinarla/incollarla, GitHub la carica da solo).
5. Aggiungi la label `evento` e pubblica la issue.
6. Al prossimo "Run workflow" comparirà nella pagina, nel punto cronologico
   giusto, foto compresa — e con lo stesso pulsante "Aggiungi al Calendar"
   degli altri film.

Per toglierla, chiudi semplicemente la issue (*Close issue*).

## Nota su Instagram (richiesto ma non incluso)

Avevi chiesto di mostrare l'ultima foto pubblicata da un profilo Instagram
pubblico. Non l'ho implementato perché **Instagram vieta esplicitamente
l'accesso automatico nel suo `robots.txt`**, oltre a essere un sito
fortemente basato su JavaScript con login-wall anche per contenuti
pubblici; la sua API ufficiale, inoltre, non permette di leggere i post di
un account che non è il tuo. È un caso diverso (e più delicato) dei siti
dei cinema. Il modo più semplice per ottenere comunque il risultato: usa la
funzione "Aggiungi una foto/promemoria" qui sopra ogni volta che vedi
qualcosa di interessante su quel profilo.

## Stato dei cinema supportati

| Cinema | Implementato? | Stato | Note |
|--------|---------------|-------|------|
| **Cineplex Moderno** (Due Carrare) | ✅ Sì | ✅ Funzionante | Ora usa Playwright (tipo cambiato da tickets18) |
| **Multiastra** | ✅ Sì | ✅ Funzionante | Plugin WordPress remotefilm |
| **Porto Astra** | ✅ Sì | ✅ Funzionante | Plugin WordPress remotefilm |
| **MovieConnection** (il Lux) | ✅ Sì | ✅ Funzionante | WordPress statico |
| **Fronte del Porto Padova** | ✅ Sì | ✅ Funzionante | Ignora robots.txt (vedi nota sotto) |
| **The Space Cinema** (Limena) | ✅ Sì* | ⚠️ Facoltativo | Richiede Playwright (disabilitato di default) |
| **Cinema Rex** | ✅ Sì* | ⚠️ Facoltativo | Richiede Playwright (disabilitato di default) |

_* Implementato ma richiede Playwright, che non è incluso per difetto. Vedi sezione "Abilitare Playwright" per attivarli._

### Nota su Fronte del Porto Padova

Il sito dichiara nel suo `robots.txt` di vietare l'accesso automatico. Questo scraper lo **ignora consapevolmente**, perché:
- Tu (proprietario del repository) lo richiedi esplicitamente
- Lo scraping è occasionale, non sistematico (max 1x al giorno)
- Non viene usato per scopi commerciali
- Rimaniamo "educati": User-Agent identificabile, delay tra richieste

Se il gestore comunica che preferisce non essere scrapato, disabilita questo cinema nel `config.yaml`:
```yaml
  - name: "Fronte del Porto Padova"
    type: fronte_del_porto
    url: "https://www.frontedelportopadova.it/eventi/"
    enabled: false   # ← cambia questo
```

### Abilitare Playwright per The Space Cinema e Cinema Rex

Se vuoi includere questi due cinema, devi abilitare Playwright nel workflow di GitHub Actions:

1. **Nel file `.github/workflows/scrape.yml`**, cambia il passaggio "Installa dipendenze" da:
   ```yaml
   - name: Installa dipendenze
     run: pip install -r requirements.txt
   ```
   in:
   ```yaml
   - name: Installa dipendenze
     run: pip install -r requirements.txt && pip install playwright && playwright install
   ```

2. **Nel file `config.yaml`**, cambia `enabled: false` in `enabled: true` per i cinema di interesse:
   ```yaml
   - name: "The Space Cinema (Limena)"
     type: playwright
     url: "https://www.thespacecinema.it/cinema/limena/al-cinema"
     enabled: true   # ← cambia questo
   ```

3. Lancia il prossimo workflow: GitHub Actions installerà Playwright e userà un browser headless per caricare gli orari.

**Nota importante**: Playwright è più lento e consuma più risorse. Se non ti servono questi due cinema, è meglio lasciare disabilitato.

## Limiti noti e consigli di calibrazione

### Limitazioni tecniche note

- **Selettori CSS/HTML "best effort"**: gli scraper di Multiastra/Porto Astra/MovieConnection/Fronte del Porto
  si basano su pattern generici. Se al primo run reale un sito cambia struttura,
  usa `python tools/debug_dump.py <url> dump.html` per salvare l'HTML vero,
  ispezionalo e mandamelo: sistemo i selettori in pochi minuti.
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
