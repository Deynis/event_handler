"""Parseur de la programmation de L'Arsenal (Cité musicale-Metz).

Source : page de programmation filtrée sur le lieu « Arsenal », paginée
(?page=2, 3, ...). Les pages BAM, Trinitaires et « Hors les murs » de la Cité
musicale ne sont pas retenues (l'unique lieu du widget ici est L'Arsenal).

Le parseur ne dépend d'aucune classe CSS : il repère les liens vers les fiches
d'événements, remonte jusqu'à la « carte » qui les contient, puis classe chaque
ligne de texte (titre, catégorie, dates, lieu, artistes, badges). Il résiste
donc à un changement de mise en page tant que le texte reste le même.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date, datetime, time as dtime
from urllib import robotparser
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from common import make_id, norm, paris_iso

LIEU = "L'Arsenal"
VILLE = "Metz"
BASE = "https://www.citemusicale-metz.fr"
LIST_URL = BASE + "/programmation/programmation-arsenal-jean-marie-rausch"
MAX_PAGES = 12
USER_AGENT = "culture-widget/1.0 (agenda personnel; +https://github.com/Deynis/event_handler)"

EVENT_LINK = "a[href*='/programmation/saison-']"
OTHER_VENUES = {"bam", "trinitaires", "hors les murs"}
VENUE_LINES = OTHER_VENUES | {"arsenal", "l'arsenal"}
CATEGORY_PREFIXES = (
    "concert", "exposition", "spectacle", "cine", "en famille", "extra dimanche",
    "week-end", "festival", "atelier", "visite", "conference", "rencontre",
)
BADGE_PREFIXES = ("complet", "dernieres places")

MONTHS = [
    ("janv", 1), ("fevr", 2), ("mars", 3), ("avr", 4), ("mai", 5), ("juin", 6),
    ("juil", 7), ("aout", 8), ("sept", 9), ("oct", 10), ("nov", 11), ("dec", 12),
]
DATE_PART = re.compile(r"(\d{1,2})\s*(?:er)?\s+([A-Za-zÀ-ÿ]{3,9})\.?(?:\s+(20\d{2}))?")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3])\s*h\s*([0-5]\d)?\b")


# ---------- Dates ----------

def month_num(word: str) -> int | None:
    w = norm(word).rstrip(".")
    for prefix, number in MONTHS:
        if w.startswith(prefix):
            return number
    return None


def parse_date_line(text: str):
    """Analyse « 6 oct. 2026, 20h », « 20 oct. 2026 » ou « 21 oct. → 22 oct. 2026 ».

    Retourne (début, fin, jour_entier) en dates naïves (heure de Paris), ou None.
    - une date avec heure : fin = None, jour_entier = False ;
    - une date sans heure ou une période : jour_entier = True, fin = 23:59:59 du dernier jour.
    """
    parts = []
    for m in DATE_PART.finditer(text):
        month = month_num(m.group(2))
        if month:
            parts.append((int(m.group(1)), month, int(m.group(3)) if m.group(3) else None, m))
    if not parts or parts[-1][2] is None:
        return None  # pas d'année : ce n'est pas une ligne de dates fiable

    last_day, last_month, last_year, last_match = parts[-1]
    resolved = []
    for day, month, year, _ in parts:
        if year is None:
            # « 20 déc. → 5 janv. 2027 » : le début est dans l'année précédente
            year = last_year if (month, day) <= (last_month, last_day) else last_year - 1
        resolved.append(date(year, month, day))

    start_day, end_day = resolved[0], resolved[-1]

    if end_day != start_day:
        return (datetime.combine(start_day, dtime.min),
                datetime.combine(end_day, dtime(23, 59, 59)), True)

    t = TIME_RE.search(text[last_match.end():])
    if t:
        return (datetime.combine(start_day, dtime(int(t.group(1)), int(t.group(2) or 0))), None, False)
    return (datetime.combine(start_day, dtime.min), datetime.combine(start_day, dtime(23, 59, 59)), True)


def safe_parse_date_line(text: str):
    try:
        return parse_date_line(text)
    except ValueError:  # date impossible (ex. 31 nov.)
        return None


# ---------- Catégories ----------

def map_category(raw: str | None) -> str:
    n = norm(raw or "")
    if n.startswith(("concert", "extra dimanche")):
        return "concert"
    if n.startswith("expo"):
        return "expo"
    if n.startswith("cine"):
        return "cinema"
    if n.startswith(("festival", "week-end")):
        return "festival"
    return "spectacle"  # spectacle, en famille, visite, atelier...


# ---------- Analyse de la page ----------

def _card_for(link, selector: str):
    """Remonte jusqu'au plus grand ancêtre qui ne contient que cet événement."""
    own = link.get("href")
    node = link
    while node.parent is not None and node.parent.name not in ("body", "html", "[document]"):
        hrefs = {a.get("href") for a in node.parent.select(selector)}
        if hrefs - {own}:
            break
        node = node.parent
    return node


def parse_card(card, url: str) -> dict | None:
    lines = [t for t in card.stripped_strings if t]
    heading = card.find(["h1", "h2", "h3", "h4"])
    title = heading.get_text(" ", strip=True) if heading else None

    dates = venue = category_raw = None
    others: list[str] = []
    badges: list[str] = []
    for line in lines:
        n = norm(line)
        if title and line == title:
            continue
        if dates is None and safe_parse_date_line(line):
            dates = safe_parse_date_line(line)
        elif n in VENUE_LINES:
            venue = n
        elif n.startswith(BADGE_PREFIXES):
            badges.append(line)
        elif category_raw is None and n.startswith(CATEGORY_PREFIXES):
            category_raw = line
        elif line not in others:
            others.append(line)

    if title is None and others:
        title = others.pop(0)
    if not title or dates is None:
        return None

    note_parts = []
    if category_raw:
        extra = re.search(r"\((.+)\)", category_raw)
        if extra:
            note_parts.append(extra.group(1).strip())
    note_parts.extend(others)
    note_parts.extend(badges)
    return {
        "url": url,
        "titre": title,
        "dates": dates,
        "venue": venue,
        "category_raw": re.sub(r"\s*\(.*\)\s*$", "", category_raw or "") or None,
        "note": " - ".join(note_parts) or None,
    }


def parse_listing(html: str, page_url: str = BASE) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards: dict[str, dict] = {}
    skipped = 0
    for link in soup.select(EVENT_LINK):
        url = urljoin(page_url, link.get("href", "")).split("#")[0]
        if url in cards:
            continue
        card = parse_card(_card_for(link, EVENT_LINK), url)
        if card is None:
            skipped += 1
            continue
        cards[url] = card
    if skipped:
        print(f"  {skipped} lien(s) ignoré(s) (pas de titre ou de date lisible)", file=sys.stderr)
    return list(cards.values())


def build_event(card: dict) -> dict | None:
    if card["venue"] in OTHER_VENUES:
        return None
    start, end, all_day = card["dates"]
    event = {
        "id": make_id(LIEU, start, card["titre"]),
        "lieu": LIEU,
        "ville": VILLE,
        "categorie": map_category(card["category_raw"]),
        "titre": card["titre"],
        "debut": paris_iso(start),
    }
    if end:
        event["fin"] = paris_iso(end)
    if all_day:
        event["jour_entier"] = True
    if card["note"]:
        event["note"] = card["note"]
    event["url"] = card["url"]
    return event


# ---------- Réseau ----------

def check_robots(session: requests.Session) -> None:
    try:
        r = session.get(BASE + "/robots.txt", timeout=15)
        if r.status_code != 200:
            return
        rp = robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
    except requests.RequestException:
        return
    if not rp.can_fetch(USER_AGENT, LIST_URL):
        raise RuntimeError("robots.txt interdit l'accès à la page de programmation")


def fetch_events(pause: float = 1.0) -> list[dict]:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    check_robots(session)

    cards: dict[str, dict] = {}
    for page in range(1, MAX_PAGES + 1):
        url = LIST_URL if page == 1 else f"{LIST_URL}?page={page}"
        r = session.get(url, timeout=20)
        if r.status_code == 404 and page > 1:
            break
        r.raise_for_status()
        r.encoding = "utf-8"
        found = parse_listing(r.text, url)
        new = [c for c in found if c["url"] not in cards]
        print(f"  page {page} : {len(found)} carte(s), {len(new)} nouvelle(s)")
        if not new:
            break
        for c in new:
            cards[c["url"]] = c
        time.sleep(pause)

    events = [e for e in (build_event(c) for c in cards.values()) if e]
    if not events:
        raise RuntimeError("aucun événement trouvé : la mise en page du site a probablement changé")
    return events
