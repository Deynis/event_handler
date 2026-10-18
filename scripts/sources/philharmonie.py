"""Parseur de la programmation de la Philharmonie Luxembourg.

Source : le sitemap du site (autorisé par robots.txt, contrairement aux pages
de liste paginées `?page=N` qui sont interdites). Chaque fiche d'événement est
ensuite ouverte, à 1 requête par seconde, et lue via :
- la balise og:title « Titre | 06.03.2027 19:30 » (titre, date, heure) ;
- le bloc « Détails » (salle) ;
- l'attribut data-is-kids du titre : les événements jeune public (Kids' Phil,
  familles, scolaires, Familljefestival) sont écartés.

Pour ne pas rouvrir ~400 fiches à chaque passage, un cache
(data/philharmonie-cache.json) garde le résultat de chaque fiche avec la date
« lastmod » du sitemap : une fiche n'est relue que si elle est nouvelle ou a
été modifiée.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib import robotparser

import requests
from bs4 import BeautifulSoup

from common import make_id, norm, now_paris, paris_iso

LIEU = "Philharmonie Luxembourg"
VILLE = "Luxembourg"
BASE = "https://www.philharmonie.lu"
SITEMAP_URL = BASE + "/sitemap/fr-lu.xml"
USER_AGENT = "culture-widget/1.0 (agenda personnel; +https://github.com/Deynis/event_handler)"
CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "philharmonie-cache.json"
MAX_FETCH = 500          # garde-fou : nombre maximal de fiches ouvertes par passage
MAX_FAILURE_RATE = 0.2   # au-delà, on considère que le site a changé

# Fiches directes d'une saison : /fr/programme/2026-27/<slug>-<id hexadécimal 16>
# (les sous-dossiers abonnements/ et festival/ sont des pages de regroupement).
EVENT_URL = re.compile(r"^https://www\.philharmonie\.lu/fr/programme/(20\d{2})-(\d{2})/[a-z0-9-]+-[0-9a-f]{16}$")
SITEMAP_ENTRY = re.compile(r"<url>\s*<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", re.S)
OG_TITLE = re.compile(r"^(.*)\s+\|\s+(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?\s*$")


# ---------- Sitemap ----------

def season_is_current(start_year: int, end_suffix: int, today: date) -> bool:
    """Une saison « 2026-27 » se termine l'été 2027 : on l'ignore une fois le 31 juillet passé."""
    end_year = start_year // 100 * 100 + end_suffix
    if end_year < start_year:
        end_year += 100
    return date(end_year, 7, 31) >= today


def parse_sitemap(xml: str, today: date) -> dict[str, str]:
    """Retourne {url de fiche: lastmod} pour les saisons en cours ou à venir."""
    entries = {}
    for loc, lastmod in SITEMAP_ENTRY.findall(xml):
        loc = loc.strip()
        m = EVENT_URL.match(loc)
        if m and season_is_current(int(m.group(1)), int(m.group(2)), today):
            entries[loc] = (lastmod or "").strip()
    return entries


# ---------- Fiche d'événement ----------

def parse_event_page(html: str, url: str) -> dict | None:
    """Analyse une fiche. Retourne l'événement, ou None s'il est jeune public.

    Lève ValueError si la fiche n'a pas le format attendu.
    """
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if h1 is not None and norm(h1.get("data-is-kids", "")) == "true":
        return None

    og = soup.find("meta", attrs={"property": "og:title"})
    m = OG_TITLE.match(og.get("content", "").strip()) if og else None
    if not m:
        raise ValueError("og:title absent ou sans date")
    title = m.group(1).strip()
    day, month, year = int(m.group(2)), int(m.group(3)), int(m.group(4))
    has_time = m.group(5) is not None
    start = datetime(year, month, day, int(m.group(5) or 0), int(m.group(6) or 0))

    specs = {}
    for li in soup.select(".event-details__spec"):
        label = li.select_one(".event-details__spec-label")
        value = li.select_one(".event-details__spec-value")
        if label and value:
            specs[norm(label.get_text())] = value.get_text(" ", strip=True)

    event = {
        "id": make_id(LIEU, start, title),
        "lieu": LIEU,
        "ville": VILLE,
        "categorie": "concert",
        "titre": title,
        "debut": paris_iso(start),
    }
    if not has_time:
        event["fin"] = paris_iso(start.replace(hour=23, minute=59, second=59))
        event["jour_entier"] = True
    if specs.get("salle"):
        event["note"] = specs["salle"]
    event["url"] = url
    return event


# ---------- Cache ----------

def load_cache(path: Path = CACHE_FILE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save_cache(cache: dict, path: Path = CACHE_FILE) -> None:
    text = json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=1)
    path.write_text(text + "\n", encoding="utf-8")


def is_past(event: dict | None, today: date) -> bool:
    return event is not None and datetime.fromisoformat(event.get("fin") or event["debut"]).date() < today


# ---------- Réseau ----------

def check_robots(session: requests.Session, sample_url: str) -> None:
    try:
        r = session.get(BASE + "/robots.txt", timeout=15)
        if r.status_code != 200:
            return
        rp = robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
    except requests.RequestException:
        return
    for url in (SITEMAP_URL, sample_url):
        if not rp.can_fetch(USER_AGENT, url):
            raise RuntimeError(f"robots.txt interdit l'accès à {url}")


def fetch_events(pause: float = 1.0) -> list[dict]:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    today = now_paris().date()

    r = session.get(SITEMAP_URL, timeout=30)
    r.raise_for_status()
    entries = parse_sitemap(r.text, today)
    if not entries:
        raise RuntimeError("aucune fiche d'événement dans le sitemap : sa structure a probablement changé")
    check_robots(session, next(iter(entries)))

    old_cache = load_cache()
    cache = {}
    to_fetch = []
    for url, lastmod in entries.items():
        cached = old_cache.get(url)
        if cached and (cached.get("lastmod") == lastmod or is_past(cached.get("event"), today)):
            cache[url] = cached
        else:
            to_fetch.append(url)
    print(f"  {len(entries)} fiche(s) au sitemap, {len(cache)} en cache, {len(to_fetch)} à lire")

    if len(to_fetch) > MAX_FETCH:
        print(f"  plus de {MAX_FETCH} fiches à lire : le reste le sera au prochain passage")
        to_fetch = to_fetch[:MAX_FETCH]

    failures = 0
    for i, url in enumerate(to_fetch):
        if i:
            time.sleep(pause)
        try:
            page = session.get(url, timeout=20)
            page.raise_for_status()
            page.encoding = "utf-8"
            event = parse_event_page(page.text, url)
        except (requests.RequestException, ValueError) as exc:
            failures += 1
            print(f"  fiche ignorée ({exc}) : {url}", file=sys.stderr)
            if url in old_cache:
                cache[url] = old_cache[url]  # on garde l'ancienne lecture
            continue
        cache[url] = {"lastmod": entries[url], "event": event}

    if to_fetch and failures > MAX_FAILURE_RATE * len(to_fetch):
        raise RuntimeError(f"{failures}/{len(to_fetch)} fiches illisibles : la mise en page a probablement changé")

    save_cache(cache)
    events = [c["event"] for c in cache.values() if c.get("event") and not is_past(c["event"], today)]
    kids = sum(1 for c in cache.values() if c.get("event") is None)
    print(f"  {kids} événement(s) jeune public écarté(s)")
    if not events:
        raise RuntimeError("aucun événement trouvé : la mise en page du site a probablement changé")
    return events
