"""Genera docs/index.html: pagina mobile-friendly organizzata per GIORNO e
poi per fasce orarie di MEZZ'ORA (es. "21:30" raggruppa 21:30-21:59). Se
piu' film (o eventi personalizzati) cadono nella stessa fascia, vengono
mostrati affiancati nella stessa riga (una griglia che va a capo se non
entrano tutti). Ogni card mostra comunque il proprio orario esatto, e le
card dentro una fascia sono ordinate per orario crescente. Le fasce senza
nulla dentro non vengono create (nessuna riga vuota).

La pagina include due barre di filtro (chip cliccabili, JS puro):
  - per CINEMA (comprese le "schede" degli eventi personalizzati, come
    categoria a se')
  - per FLAG degli eventi personalizzati (le label delle Issue, "evento"
    esclusa) - compare solo se ne esiste almeno una tra gli eventi correnti

Genera anche docs/ics/*.ics (un file per proiezione/evento) e
docs/data.json (dati grezzi: sia per un futuro display ESP32, sia per il
workflow "leggero" che aggiorna solo gli eventi personalizzati senza
re-interrogare i siti dei cinema, vedi update_events.py).
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
from collections import defaultdict
from functools import lru_cache
from typing import List, Optional
from zoneinfo import ZoneInfo

from calendar_links import google_calendar_link, ics_content
from custom_events import CustomEvent
from models import Movie, Showtime, title_key

WEEKDAYS_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
MONTHS_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
             "agosto", "settembre", "ottobre", "novembre", "dicembre"]
CUSTOM_SOURCE = "__custom__"

# Anteprima dei link (Open Graph): WhatsApp, Telegram, iMessage... la leggono dall'<head>.
# Per cambiare l'immagine basta mettere un altro file in docs/ e cambiare OG_IMAGE
# (consigliato PNG/JPG >= 600x315, meglio 1200x630; l'URL deve essere assoluto).
SITE_URL = "https://maaces.github.io/cinemassPD/"
OG_TITLE = "CineMass PD"
OG_DESCRIPTION = "Tutte le programmazioni, ora in un unico posto"
OG_IMAGE = SITE_URL + "og-image.jpg"   # file in docs/
OG_IMAGE_SIZE = (1200, 630)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-") or "item"


def _esc(text) -> str:
    return html.escape(str(text)) if text else ""


def _esc_attr(text) -> str:
    """Come _esc, ma pensato per un attributo HTML (es. data-cinema)."""
    return html.escape(str(text), quote=True) if text else ""


URL_RE = re.compile(r"(https?://[^\s<>\"']+)")


def _linkify(text) -> str:
    """Escapa il testo e trasforma in link cliccabili gli URL che contiene."""
    if not text:
        return ""
    parts = URL_RE.split(str(text))  # i gruppi catturati (URL) finiscono alle posizioni dispari
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            url = part.rstrip(".,;:!?)")  # la punteggiatura finale non fa parte del link
            trailing = part[len(url):]
            out.append(f'<a href="{_esc_attr(url)}" target="_blank" rel="noopener">{_esc(url)}</a>{_esc(trailing)}')
        else:
            out.append(_esc(part))
    return "".join(out)


@lru_cache(maxsize=1)
def _cinema_websites() -> dict:
    """Mappa nome cinema -> sito ufficiale, dal campo 'website' di config.yaml.
    Letta qui (e non passata da main.py) cosi' anche update_events.py la usa."""
    import yaml
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {c["name"]: c["website"] for c in cfg.get("cinemas", [])
            if c.get("name") and c.get("website")}


@lru_cache(maxsize=1)
def _cinema_maps() -> dict:
    """Mappa nome cinema -> link Google Maps, dal campo 'maps' di config.yaml."""
    import yaml
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {c["name"]: c["maps"] for c in cfg.get("cinemas", [])
            if c.get("name") and c.get("maps")}


def _cinema_html(name: str) -> str:
    """Nome del cinema, cliccabile verso il sito ufficiale se e' noto."""
    site = _cinema_websites().get(name)
    if not site:
        return _esc(name)
    return f'<a href="{_esc_attr(site)}" target="_blank" rel="noopener">{_esc(name)}</a>'


def _format_date_it(date_str: str) -> str:
    try:
        y, mo, d = (int(x) for x in date_str.split("-"))
        wd = WEEKDAYS_IT[dt.date(y, mo, d).weekday()]
        return f"{wd} {d} {MONTHS_IT[mo - 1]}"
    except (ValueError, AttributeError):
        return date_str


WEEKDAYS_SHORT_IT = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]


def _day_suffix_html(date_str: Optional[str], uncertain: bool = False) -> str:
    """' - LUN 19' accanto all'orario, mostrato solo nella card ingrandita (vedi CSS .mc-day).
    Vuoto se la data non e' valida o non riconosciuta."""
    if uncertain or not date_str or date_str == "data-da-verificare":
        return ""
    try:
        y, mo, d = (int(x) for x in date_str.split("-"))
        wd = WEEKDAYS_SHORT_IT[dt.date(y, mo, d).weekday()]
    except (ValueError, AttributeError, IndexError):
        return ""
    return f'<span class="mc-day"> - {wd} {d}</span>'


def _short_id(*parts) -> str:
    """ID corto (6 caratteri base36) di una card, ricavato dai dati (cinema, titolo, data, ora):
    e' la parte dopo '#p=' del link condiviso. Non dipende dall'ordine ne' da un contatore, quindi
    lo stesso dato produce sempre lo stesso id tra un aggiornamento e l'altro."""
    digest = hashlib.sha1("|".join(str(p or "") for p in parts).encode("utf-8")).hexdigest()
    n, out = int(digest, 16), ""
    while len(out) < 6:
        n, r = divmod(n, 36)
        out += "0123456789abcdefghijklmnopqrstuvwxyz"[r]
    return out


def _unique_id(base: str, used: set) -> str:
    """Se due card producessero lo stesso id (proiezioni identiche, o una collisione di hash
    molto improbabile) la seconda riceve il suffisso -2, -3, ..."""
    cid, n = base, 2
    while cid in used:
        cid = f"{base}-{n}"
        n += 1
    used.add(cid)
    return cid


def _share_when(date_str: Optional[str], time_str: Optional[str], uncertain: bool = False) -> str:
    """'Sabato 24 ottobre · 21:30' per il testo di condivisione (parti mancanti omesse)."""
    parts = []
    if date_str and date_str != "data-da-verificare" and not uncertain:
        parts.append(_format_date_it(date_str))
    if time_str:
        parts.append(time_str)
    return " · ".join(parts)


def _half_hour_bucket(time_str: Optional[str]) -> Optional[str]:
    """'21:35' -> '21:30', '21:05' -> '21:00'. None se l'orario non e' valido."""
    if not time_str:
        return None
    try:
        h, m = (int(x) for x in time_str.split(":"))
        return f"{h:02d}:{'30' if m >= 30 else '00'}"
    except ValueError:
        return None


def _write_ics(movie: Movie, showtime: Showtime, ics_dir: str, base_name: str) -> Optional[str]:
    content = ics_content(movie, showtime)
    if not content:
        return None
    fname = f"{base_name}.ics"
    with open(os.path.join(ics_dir, fname), "w", encoding="utf-8") as f:
        f.write(content)
    return f"ics/{fname}"


def _movie_card_html(m: Movie, st: Showtime, ics_dir: str, idx: int, card_id: str = "") -> str:
    gcal = google_calendar_link(m, st)
    ics_link = _write_ics(m, st, ics_dir, f"{_slug(m.title)}-{st.date}-{st.time.replace(':', '')}-{idx}")

    poster_html = (f'<img class="poster" src="{_esc(m.poster_url)}" alt="" loading="lazy">'
                   if m.poster_url else '<div class="poster poster-placeholder">🎬</div>')
    director_html = f'<div class="director">Regia: <bdi>{_esc(m.director)}</bdi></div>' if m.director else ""
    duration_html = f'{m.duration_min} min' if m.duration_min else ""
    price_note = " · ".join(x for x in [st.price, st.note] if x)

    links = []
    if m.tmdb_url:
        links.append(f'<a href="{_esc(m.tmdb_url)}" target="_blank" rel="noopener">🎬 TMDB</a>')
    elif m.detail_url:
        links.append(f'<a href="{_esc(m.detail_url)}" target="_blank" rel="noopener">ℹ️ Scheda</a>')
    if m.trailer_url:
        links.append(f'<a href="{_esc(m.trailer_url)}" target="_blank" rel="noopener">▶️ Trailer</a>')
    elif m.trailer_search_url:
        links.append(f'<a href="{_esc(m.trailer_search_url)}" target="_blank" rel="noopener">🔍 Cerca trailer</a>')
    if m.letterboxd_url:
        links.append(f'<a href="{_esc(m.letterboxd_url)}" target="_blank" rel="noopener">🔍 Letterboxd</a>')

    buttons = []
    maps_link = _cinema_maps().get(st.cinema)
    if maps_link:
        buttons.append(f'<a class="btn" href="{_esc(maps_link)}" target="_blank" rel="noopener">📍 Maps</a>')
    if gcal:
        buttons.append(f'<a class="btn btn-alt" href="{_esc(gcal)}" target="_blank" rel="noopener">📅 Calendar</a>')
    if ics_link:
        buttons.append(f'<a class="btn btn-alt" href="{_esc(ics_link)}">🍎 Calendario iPhone</a>')

    return f"""
      <div class="mini-card" data-id="{_esc_attr(card_id)}" data-source="{_esc_attr(st.cinema)}" data-movie="{_esc_attr(m.title)}"
           data-share-title="{_esc_attr(m.title)}" data-share-when="{_esc_attr(_share_when(st.date, st.time, st.date_uncertain))}"
           data-share-cinema="{_esc_attr(st.cinema)}">
        <div class="mc-head">
          {poster_html}
          <div class="mc-title">
            <div class="mc-time">{_esc(st.time)}{_day_suffix_html(st.date, st.date_uncertain)}</div>
            <div class="mc-name">{_esc(m.title)}</div>
            {director_html}
            <div class="meta">{_esc(duration_html)}</div>
          </div>
        </div>
        <div class="mc-cinema">📍 {_cinema_html(st.cinema)}{(' · ' + _esc(price_note)) if price_note else ''}</div>
        <div class="links">{' · '.join(links)}</div>
        <div class="mc-actions">{' '.join(buttons)}</div>
      </div>"""


def _custom_card_html(ce: CustomEvent, ics_dir: str, idx: int, card_id: str = "") -> str:
    gcal_link = None
    ics_link = None
    if ce.date and ce.time:
        fake_movie = Movie(title=ce.title, duration_min=120, detail_url=ce.source_url)
        fake_showtime = Showtime(date=ce.date, time=ce.time, cinema="Evento personale")
        gcal_link = google_calendar_link(fake_movie, fake_showtime)
        ics_link = _write_ics(fake_movie, fake_showtime, ics_dir, f"evento-{_slug(ce.title)}-{idx}")

    time_html = f'<div class="mc-time">{_esc(ce.time)}{_day_suffix_html(ce.date)}</div>' if ce.time else ""
    photo_html = f'<img class="custom-photo" src="{_esc(ce.photo_url)}" alt="" loading="lazy">' if ce.photo_url else ""
    text_html = f'<div class="custom-text">{_linkify(ce.text)}</div>' if ce.text else ""
    flags_html = ("<div class=\"flags\">" + " ".join(f'<span class="flag-pill">{_esc(f)}</span>' for f in ce.flags)
                  + "</div>") if ce.flags else ""
    buttons = []
    if gcal_link:
        buttons.append(f'<a class="btn btn-alt" href="{_esc(gcal_link)}" target="_blank" rel="noopener">📅 Calendar</a>')
    if ics_link:
        buttons.append(f'<a class="btn btn-alt" href="{_esc(ics_link)}">🍎 Calendario iPhone</a>')

    flags_attr = _esc_attr(",".join(ce.flags))
    return f"""
      <div class="mini-card custom-card" data-id="{_esc_attr(card_id)}" data-source="{CUSTOM_SOURCE}" data-flags="{flags_attr}"
           data-share-title="{_esc_attr(ce.title)}" data-share-when="{_esc_attr(_share_when(ce.date, ce.time))}">
        {time_html}
        {photo_html}
        <div class="mc-name">📌 {_esc(ce.title)}</div>
        {flags_html}
        {text_html}
        <div class="mc-actions">{' '.join(buttons)}</div>
      </div>"""


def _filter_bar(id_: str, label: str, values, data_attr: str, sites: Optional[dict] = None) -> str:
    if not values:
        return ""
    sites = sites or {}
    chips = [f'<button class="filter-chip active" data-{data_attr}-all>Tutti</button>']
    for v in values:
        chips.append(f'<button class="filter-chip" data-{data_attr}="{_esc_attr(v)}">{_esc(v)}</button>')
        if v in sites:  # ↗ accanto al chip: apre il sito ufficiale senza attivare il filtro
            chips.append(f'<a class="chip-link" href="{_esc_attr(sites[v])}" target="_blank" rel="noopener" '
                         f'title="Sito ufficiale">↗</a>')
    return f"""
    <div class="filter-bar" id="{id_}">
      <span class="filter-label">{_esc(label)}</span>
      {' '.join(chips)}
    </div>"""


FILTER_JS = """
<script>
(function () {
  function setupGroup(barId, dataAttr, matchFn) {
    var bar = document.getElementById(barId);
    if (!bar) return;
    var allBtn = bar.querySelector('[data-' + dataAttr + '-all]');
    var chips = Array.prototype.slice.call(bar.querySelectorAll('[data-' + dataAttr + ']'));

    function selected() {
      return chips.filter(function (c) { return c.classList.contains('active'); })
                  .map(function (c) { return c.getAttribute('data-' + dataAttr); });
    }
    function refreshAllState() {
      var any = chips.some(function (c) { return c.classList.contains('active'); });
      allBtn.classList.toggle('active', !any);
    }
    allBtn.addEventListener('click', function () {
      chips.forEach(function (c) { c.classList.remove('active'); });
      allBtn.classList.add('active');
      applyFilters();
    });
    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        chip.classList.toggle('active');
        refreshAllState();
        applyFilters();
      });
    });
    return { selected: selected };
  }

  var sourceGroup = setupGroup('filter-sources', 'source', null);
  var movieGroup = setupGroup('filter-movies', 'movie', null);
  var flagGroup = setupGroup('filter-flags', 'flag', null);

  // bottone "Seleziona film": mostra/nasconde il pannello con i chip dei film
  var moviesToggle = document.getElementById('movies-toggle');
  var moviesPanel = document.getElementById('movies-panel');
  function updateMoviesToggle() {
    if (!moviesToggle || !moviesPanel) return;
    var n = movieGroup ? movieGroup.selected().length : 0;
    moviesToggle.textContent = '🎞️ Seleziona film' + (n ? ' (' + n + ')' : '') + (moviesPanel.hidden ? ' ▾' : ' ▴');
    moviesToggle.classList.toggle('active', n > 0);
    moviesToggle.setAttribute('aria-expanded', moviesPanel.hidden ? 'false' : 'true');
  }
  if (moviesToggle && moviesPanel) {
    moviesToggle.addEventListener('click', function () {
      moviesPanel.hidden = !moviesPanel.hidden;
      updateMoviesToggle();
    });
    updateMoviesToggle();
  }

  window.applyFilters = function () {
    var sel = sourceGroup ? sourceGroup.selected() : [];
    var moviesSel = movieGroup ? movieGroup.selected() : [];
    var flagsSel = flagGroup ? flagGroup.selected() : [];
    updateMoviesToggle();

    document.querySelectorAll('.mini-card').forEach(function (card) {
      var src = card.getAttribute('data-source');
      var okSource = sel.length === 0 || sel.indexOf(src) !== -1;

      // con almeno un film selezionato si vedono solo quei film: gli eventi (senza data-movie) spariscono
      var okMovie = true;
      if (moviesSel.length > 0) {
        okMovie = card.hasAttribute('data-movie') &&
                  moviesSel.indexOf(card.getAttribute('data-movie')) !== -1;
      }

      var okFlags = true;
      if (flagsSel.length > 0) {
        if (card.hasAttribute('data-flags')) {
          var cardFlags = (card.getAttribute('data-flags') || '').split(',');
          okFlags = flagsSel.some(function (f) { return cardFlags.indexOf(f) !== -1; });
        } else {
          okFlags = true; // i film non hanno flag: il filtro flag non li nasconde
        }
      }
      card.style.display = (okSource && okMovie && okFlags) ? '' : 'none';
    });

    document.querySelectorAll('.time-row').forEach(function (row) {
      var anyVisible = Array.prototype.slice.call(row.querySelectorAll('.mini-card'))
                             .some(function (c) { return c.style.display !== 'none'; });
      row.style.display = anyVisible ? '' : 'none';
    });
    document.querySelectorAll('.day').forEach(function (day) {
      var anyVisible = Array.prototype.slice.call(day.querySelectorAll('.mini-card'))
                             .some(function (c) { return c.style.display !== 'none'; });
      day.style.display = anyVisible ? '' : 'none';
    });
  };
})();
</script>
"""


CARD_ZOOM_JS = """
<script>
(function () {
  // Click su una card -> ne mostra una copia ingrandita sopra la pagina.
  // Click fuori dalla copia (sullo sfondo scuro), sulla X o tasto Esc -> chiude.
  var overlay = null, lastCard = null, toastTimer = null;

  // --- condivisione: link diretto alla card (#p=<id>) + testo "link / film / data / cinema" ---
  function toast(msg) {
    var t = document.getElementById('share-toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'share-toast';
      t.className = 'share-toast';
      t.setAttribute('role', 'status');
      document.body.appendChild(t);
    }
    t.textContent = msg;
    requestAnimationFrame(function () { t.classList.add('show'); });
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove('show'); }, 2200);
  }

  function legacyCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) {}
    ta.remove();
    return ok;
  }

  function copyText(text) {
    function fallback() { toast(legacyCopy(text) ? 'Copiato negli appunti' : 'Impossibile copiare il testo'); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { toast('Copiato negli appunti'); }, fallback);
    } else {
      fallback();
    }
  }

  function shareText(card) {
    var custom = card.getAttribute('data-source') === '__custom__';
    var lines = ['\\ud83d\\udc49 ' + location.href.split('#')[0] + '#p=' + card.getAttribute('data-id'), ''];
    var title = card.getAttribute('data-share-title');
    var when = card.getAttribute('data-share-when');
    var cinema = card.getAttribute('data-share-cinema');
    if (title) lines.push((custom ? '\\ud83d\\udccc ' : '\\ud83c\\udfac ') + title);
    if (when) lines.push('\\ud83d\\udcc5 ' + when);
    if (cinema) lines.push('\\ud83d\\udccd ' + cinema);
    return lines.join('\\n');
  }

  function shareCard(card) {
    var text = shareText(card);
    if (navigator.share) {
      // solo "text": cosi' l'ordine (link, film, data, cinema) resta quello voluto in tutte le app
      navigator.share({ text: text }).catch(function (err) {
        if (err && err.name === 'AbortError') return; // l'utente ha chiuso il menu
        copyText(text);
      });
    } else {
      copyText(text);
    }
  }

  function close(keepHash) {
    if (!overlay) return;
    var o = overlay;
    overlay = null;
    o.classList.remove('open');
    document.body.classList.remove('zoom-lock');
    setTimeout(function () { o.remove(); }, 180);
    if (lastCard) lastCard.focus({ preventScroll: true });
    if (keepHash !== true && /^#p=/.test(location.hash)) {
      history.replaceState(null, '', location.pathname + location.search); // un reload non riapre la card
    }
  }

  function open(card) {
    close(true);
    lastCard = card;
    overlay = document.createElement('div');
    overlay.className = 'card-zoom';
    var clone = card.cloneNode(true);
    clone.removeAttribute('tabindex');
    clone.style.display = '';
    clone.setAttribute('role', 'dialog');
    clone.setAttribute('aria-modal', 'true');
    var x = document.createElement('button');
    x.type = 'button';
    x.className = 'card-zoom-close';
    x.setAttribute('aria-label', 'Chiudi');
    x.textContent = '\u2715';
    x.addEventListener('click', close);
    var sh = document.createElement('button');
    sh.type = 'button';
    sh.className = 'card-zoom-share';
    sh.setAttribute('aria-label', 'Condividi');
    sh.title = 'Condividi';
    sh.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 15V3"/>' +
      '<path d="M8 7l4-4 4 4"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>';
    sh.addEventListener('click', function () { shareCard(card); });
    var tools = document.createElement('div');
    tools.className = 'card-zoom-tools';
    tools.appendChild(x);
    tools.appendChild(sh);   // Condividi sotto la X
    clone.insertBefore(tools, clone.firstChild);
    overlay.appendChild(clone);
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
    document.body.appendChild(overlay);
    document.body.classList.add('zoom-lock');
    requestAnimationFrame(function () { overlay && overlay.classList.add('open'); });
    x.focus({ preventScroll: true });
  }

  document.querySelectorAll('.time-items .mini-card').forEach(function (card) {
    card.setAttribute('tabindex', '0');
    card.addEventListener('click', function (e) {
      if (e.target.closest('a, button')) return; // i link nella card funzionano come prima
      open(card);
    });
    card.addEventListener('keydown', function (e) {
      if ((e.key === 'Enter' || e.key === ' ') && e.target === card) { e.preventDefault(); open(card); }
    });
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });

  // Link condiviso (#p=<id>): apre direttamente la card ingrandita.
  function openFromHash() {
    var m = /^#p=([^&]+)/.exec(location.hash);
    if (!m) return;
    var id;
    try { id = decodeURIComponent(m[1]); } catch (e) { id = m[1]; }
    var cards = document.querySelectorAll('.time-items .mini-card');
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].getAttribute('data-id') === id) {
        cards[i].scrollIntoView({ block: 'center' });
        open(cards[i]);
        return;
      }
    }
    toast('Questa proiezione non \\u00e8 pi\\u00f9 in programmazione');
    history.replaceState(null, '', location.pathname + location.search);
  }
  window.addEventListener('hashchange', openFromHash);
  openFromHash();
})();
</script>
"""


def render(movies: List[Movie], custom_events: List[CustomEvent], out_dir: str, cinemas_note: str = "") -> None:
    ics_dir = os.path.join(out_dir, "ics")
    os.makedirs(ics_dir, exist_ok=True)
    # ricrea da zero i .ics: senza questo passo i file delle proiezioni gia' passate si accumulerebbero
    for old in os.listdir(ics_dir):
        if old.endswith(".ics"):
            os.remove(os.path.join(ics_dir, old))

    # tutto cio' che e' prima di oggi (ora italiana) non viene mostrato
    today_iso = dt.datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d")

    def _is_past(date_str: Optional[str]) -> bool:
        return bool(date_str) and date_str != "data-da-verificare" and date_str < today_iso

    # timeline[data][fascia_mezz'ora] = lista di (orario_esatto, html_card)
    timeline = defaultdict(lambda: defaultdict(list))
    uncertain_html = []
    json_movies, json_events = [], []
    seen_cinemas = []
    seen_flags = []
    counter = 0
    used_ids = set()

    for m in movies:
        json_showtimes = []
        for st in m.showtimes:
            if _is_past(st.date):
                continue
            json_showtimes.append({"date": st.date, "time": st.time, "cinema": st.cinema,
                                    "price": st.price, "note": st.note, "date_uncertain": st.date_uncertain})
            if st.cinema and st.cinema not in seen_cinemas:
                seen_cinemas.append(st.cinema)
            counter += 1
            card_id = _unique_id(_short_id(st.cinema, title_key(m.title), st.date, st.time), used_ids)
            card = _movie_card_html(m, st, ics_dir, counter, card_id)
            bucket = _half_hour_bucket(st.time)
            if st.date_uncertain or not st.date or st.date == "data-da-verificare" or not bucket:
                uncertain_html.append(card)
            else:
                timeline[st.date][bucket].append((st.time, card))
        if json_showtimes:
            json_movies.append({
                "title": m.title, "director": m.director, "duration_min": m.duration_min,
                "poster_url": m.poster_url, "trailer_url": m.trailer_url,
                "trailer_search_url": m.trailer_search_url, "letterboxd_url": m.letterboxd_url,
                "tmdb_url": m.tmdb_url, "detail_url": m.detail_url, "showtimes": json_showtimes,
            })

    for ce in custom_events:
        if _is_past(ce.date):
            continue
        counter += 1
        card_id = _unique_id(_short_id("evento", title_key(ce.title), ce.date, ce.time), used_ids)
        card = _custom_card_html(ce, ics_dir, counter, card_id)
        bucket = _half_hour_bucket(ce.time)
        if ce.date and bucket:
            timeline[ce.date][bucket].append((ce.time, card))
        else:
            uncertain_html.append(card)
        for f in ce.flags:
            if f not in seen_flags:
                seen_flags.append(f)
        json_events.append({"title": ce.title, "text": ce.text, "date": ce.date, "time": ce.time,
                             "photo_url": ce.photo_url, "flags": ce.flags, "source_url": ce.source_url})

    sections = []
    for date_str in sorted(timeline.keys()):
        rows = []
        for bucket in sorted(timeline[date_str].keys()):
            entries = sorted(timeline[date_str][bucket], key=lambda pair: pair[0])
            items = "".join(html_fragment for _, html_fragment in entries)
            rows.append(f"""
          <div class="time-row">
            <div class="time-label">{_esc(bucket)}</div>
            <div class="time-items">{items}</div>
          </div>""")
        sections.append(f"""
        <section class="day">
          <h2>{_esc(_format_date_it(date_str))}</h2>
          {''.join(rows)}
        </section>""")

    if uncertain_html:
        sections.append(f"""
        <section class="day">
          <h2>⚠️ Orari da verificare</h2>
          <div class="time-row"><div class="time-items">{''.join(uncertain_html)}</div></div>
        </section>""")

    source_values = list(seen_cinemas)
    if custom_events:
        source_values.append(CUSTOM_SOURCE)
    sources_bar = _filter_bar("filter-sources", "🎥 Cinema", source_values, "source")
    # barra dei film: un chip per titolo con almeno una proiezione, in ordine alfabetico
    movie_titles = sorted({j["title"] for j in json_movies}, key=lambda t: t.lower())
    movies_bar = _filter_bar("filter-movies", "Film", movie_titles, "movie")
    if movies_bar:  # i chip dei film restano nascosti finche' non si preme "Seleziona film"
        movies_bar = f"""
    <div class="filter-bar">
      <button class="filter-chip" id="movies-toggle" type="button" aria-expanded="false" aria-controls="movies-panel">🎞️ Seleziona film ▾</button>
    </div>
    <div id="movies-panel" hidden>{movies_bar}</div>"""
    # il chip degli eventi personalizzati ha un'etichetta leggibile, non "__custom__":
    sources_bar = sources_bar.replace(
        f'data-source="{CUSTOM_SOURCE}">{_esc(CUSTOM_SOURCE)}<', f'data-source="{CUSTOM_SOURCE}">📌 Eventi personali<'
    )
    flags_bar = _filter_bar("filter-flags", "🍿 Eventi", seen_flags, "flag")

    now = dt.datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y alle %H:%M")
    html_doc = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="icon" type="image/png" href="/cinemassPD/favicon-96x96.png?v=20261012" sizes="96x96" />
<link rel="icon" type="image/svg+xml" href="/cinemassPD/favicon.svg?v=20261012" />
<link rel="shortcut icon" href="/cinemassPD/favicon.ico?v=20261012" />
<link rel="apple-touch-icon" sizes="180x180" href="/cinemassPD/apple-touch-icon.png?v=20261012" />
<meta name="apple-mobile-web-app-title" content="cinemassPD" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="theme-color" content="#a02a13" />
<link rel="manifest" href="/cinemassPD/manifest.json?v=20261012" />
<title>CinemassPD</title>
<meta property="og:type" content="website" />
<meta property="og:url" content="{_esc_attr(SITE_URL)}" />
<meta property="og:title" content="{_esc_attr(OG_TITLE)}" />
<meta property="og:description" content="{_esc_attr(OG_DESCRIPTION)}" />
<meta property="og:image" content="{_esc_attr(OG_IMAGE)}" />
<meta property="og:image:width" content="{OG_IMAGE_SIZE[0]}" />
<meta property="og:image:height" content="{OG_IMAGE_SIZE[1]}" />
<style>
  :root {{
    --bg: #fafafa; --fg: #1a1a1a; --card: #ffffff; --border: #e5e5e5;
    --accent: #2c5f8a; --muted: #6b6b6b;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #14161a; --fg: #f0f0f0; --card: #1e2126; --border: #2c2f36; --accent: #7fb0e0; --muted: #9a9a9a; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--fg);
    font-family: -apple-system, Roboto, Segoe UI, sans-serif;
    padding: env(safe-area-inset-top,0) 12px env(safe-area-inset-bottom,0);
  }}
  header {{ padding: 20px 4px 8px; }}
  header h1 {{ margin: 0 0 4px; font-size: 1.4rem; }}
  header p {{ margin: 0; color: var(--muted); font-size: 0.85rem; }}
  .filter-bar {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 10px 0 2px; }}
  .filter-label {{ font-size: 0.75rem; color: var(--muted); margin-right: 2px; }}
  .filter-chip {{
    font: inherit; font-size: 0.75rem; padding: 5px 10px; border-radius: 999px;
    border: 1px solid var(--border); background: var(--card); color: var(--fg);
    cursor: pointer;
  }}
  .filter-chip.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
  [hidden] {{ display: none !important; }}
  .chip-link {{ font-size: 0.8rem; color: var(--accent); text-decoration: none; padding: 0 4px 0 0; align-self: center; }}
  .mc-cinema a {{ color: var(--accent); text-decoration: none; }}
  .mc-cinema a:hover {{ text-decoration: underline; }}
  .day {{ margin: 22px 0; }}
  /* intestazione del giorno "appiccicata" in alto: resta fissa finche' la sezione e' visibile,
     poi il giorno successivo la spinge via (sticky e' limitato al contenitore .day) */
  .day h2 {{
    position: sticky; top: env(safe-area-inset-top, 0px); z-index: 10;
    margin: 0; padding: 10px 4px 6px; background: var(--bg);
    font-size: 1.05rem; border-bottom: 2px solid var(--accent);
  }}
  .time-row {{ display: flex; gap: 10px; margin: 14px 0; align-items: flex-start; }}
  .time-label {{ flex: 0 0 48px; font-weight: 700; font-size: 0.85rem; padding-top: 10px; color: var(--muted); }}
  .time-items {{ display: flex; flex-wrap: wrap; gap: 10px; flex: 1; }}
  .time-items {{ min-width: 0; }}
  .mini-card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 10px; flex: 1 1 190px; max-width: 240px; min-width: 0;
    overflow-wrap: anywhere; word-break: break-word;
  }}
  .mini-card a {{ word-break: break-all; }}
  .custom-text a {{ color: var(--accent); }}
  .mc-head {{ display: flex; gap: 8px; }}
  .poster {{ width: 52px; height: 76px; object-fit: cover; border-radius: 6px; flex-shrink: 0; }}
  .poster-placeholder {{ display: flex; align-items: center; justify-content: center; background: var(--border); font-size: 1.4rem; }}
  .mc-time {{ font-weight: 700; font-size: 0.85rem; color: var(--accent); }}
  .mc-name {{ font-weight: 600; font-size: 0.92rem; line-height: 1.2; }}
  .director {{ font-size: 0.78rem; color: var(--muted); }}
  .meta {{ font-size: 0.75rem; color: var(--muted); }}
  .mc-cinema {{ font-size: 0.78rem; margin-top: 6px; color: var(--muted); }}
  .links {{ font-size: 0.75rem; margin-top: 4px; }}
  .links a {{ color: var(--accent); text-decoration: none; }}
  .mc-actions {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }}
  .btn {{ font-size: 0.72rem; padding: 4px 8px; border-radius: 6px; background: var(--accent); color: #fff; text-decoration: none; white-space: nowrap; }}
  .btn-alt {{ background: transparent; border: 1px solid var(--accent); color: var(--accent); }}
  .custom-card {{ border-color: var(--accent); }}
  .custom-photo {{ width: 100%; max-height: 160px; object-fit: cover; border-radius: 8px; margin: 4px 0 6px; }}
  .custom-text {{ font-size: 0.8rem; margin-top: 4px; white-space: pre-line; }}
  .flags {{ margin-top: 4px; }}
  .flag-pill {{ display: inline-block; font-size: 0.68rem; background: var(--border); border-radius: 999px; padding: 2px 8px; margin: 2px 3px 0 0; }}
  footer {{ text-align: center; color: var(--muted); font-size: 0.75rem; padding: 24px 0 40px; }}
  /* card ingrandibile: click sulla card -> copia ingrandita in primo piano, click fuori per chiudere */
  .time-items .mini-card {{ cursor: zoom-in; transition: transform .12s ease, box-shadow .12s ease; }}
  .time-items .mini-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 14px rgba(0,0,0,.12); }}
  .card-zoom {{
    position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center;
    padding: 16px; background: rgba(0,0,0,.55); cursor: zoom-out;
    opacity: 0; transition: opacity .18s ease;
  }}
  .card-zoom.open {{ opacity: 1; }}
  .card-zoom .mini-card {{
    cursor: auto; flex: none; width: min(92vw, 440px); max-width: none; max-height: 88vh; overflow-y: auto;
    padding: 18px; border-radius: 16px; box-shadow: 0 18px 50px rgba(0,0,0,.35);
    transform: scale(.92); transition: transform .18s ease;
  }}
  .card-zoom.open .mini-card {{ transform: scale(1); }}
  .card-zoom .mini-card:hover {{ transform: scale(1); box-shadow: 0 18px 50px rgba(0,0,0,.35); }}
  .card-zoom .mc-head {{ gap: 14px; }}
  .card-zoom .poster {{ width: 120px; height: 176px; border-radius: 10px; font-size: 2.4rem; }}
  .mc-day {{ display: none; }}
  .card-zoom .mc-day {{ display: inline; }}
  .card-zoom .mc-time {{ font-size: 1.1rem; }}
  .card-zoom .mc-name {{ font-size: 1.3rem; margin: 2px 0 4px; }}
  .card-zoom .director, .card-zoom .meta {{ font-size: 0.92rem; }}
  .card-zoom .mc-cinema {{ font-size: 0.95rem; margin-top: 12px; }}
  .card-zoom .links {{ font-size: 0.92rem; margin-top: 8px; }}
  .card-zoom .mc-actions {{ margin-top: 14px; gap: 8px; }}
  .card-zoom .btn {{ font-size: 0.88rem; padding: 7px 12px; }}
  .card-zoom .custom-photo {{ width: 100%; height: auto; max-height: 70vh; object-fit: contain; background: var(--card-bg, transparent); }}
  .card-zoom .custom-text {{ font-size: 0.95rem; }}
  /* pulsanti in alto a destra: X e, sotto, Condividi. Un unico blocco float+sticky (come la X originale) */
  .card-zoom-tools {{
    position: sticky; top: 0; float: right; z-index: 2; margin: -8px -8px 0 8px;
    display: flex; flex-direction: column; gap: 8px;
  }}
  .card-zoom-close {{
    flex: none; width: 32px; height: 32px; padding: 0;
    border: none; border-radius: 999px; background: var(--border); color: var(--fg);
    font-size: 1.1rem; line-height: 1; cursor: pointer;
  }}
  .card-zoom-share {{
    flex: none; width: 32px; height: 32px; padding: 0;
    display: flex; align-items: center; justify-content: center;
    border: none; border-radius: 999px; background: var(--border); color: var(--fg); cursor: pointer;
  }}
  .card-zoom-share svg {{ width: 17px; height: 17px; }}
  .share-toast {{
    position: fixed; left: 50%; bottom: calc(24px + env(safe-area-inset-bottom, 0px)); z-index: 1100;
    transform: translate(-50%, 12px); opacity: 0; pointer-events: none; max-width: 90vw;
    padding: 9px 16px; border-radius: 999px; font-size: .85rem; text-align: center;
    background: var(--fg); color: var(--bg); transition: opacity .18s ease, transform .18s ease;
  }}
  .share-toast.show {{ opacity: 1; transform: translate(-50%, 0); }}
  body.zoom-lock {{ overflow: hidden; }}
</style>
</head>
<body>
<header>
  <h1>🎬 CinemassPD - Tutte le programmazioni, ora in un unico posto</h1>
  <p>Aggiornato il {now}. {_esc(cinemas_note)}</p>
  {sources_bar}
  {flags_bar}
  {movies_bar}
</header>
{''.join(sections) if sections else '<p>Nessun film trovato in questo aggiornamento.</p>'}
<footer>Generato automaticamente · dati raccolti dai siti dei singoli cinema · <a href="debug/report.txt">diagnostica</a></footer>
{FILTER_JS}
{CARD_ZOOM_JS}
<script>if ('serviceWorker' in navigator) {{ navigator.serviceWorker.register('/cinemassPD/sw.js').catch(function () {{}}); }}</script>
</body>
</html>"""

    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_doc)

    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": dt.datetime.now().isoformat(), "movies": json_movies,
                   "custom_events": json_events}, f, ensure_ascii=False, indent=2)
