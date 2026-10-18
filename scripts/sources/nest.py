"""Parseur de la programmation du NEST (CDN transfrontalier de Thionville-Grand Est).

Source : la page de saison (lien « saison/26-27 » trouvé sur l'accueil), qui
liste les spectacles et leurs genres (Théâtre, En famille...), puis la fiche de chaque spectacle (1 requête par seconde),
dont le bloc « Séances » donne chaque représentation :
    <strong>Théâtre de Thionville - grande salle</strong><br/>
    <span>mardi 4 mai à 20<abbr>h</abbr></span>
Les séances n'ont pas d'année : elle est déduite de la saison (août à décembre
-> première année, janvier à juillet -> seconde). « à 00h » signifie « sans
heure » (période de tournée, par exemple dans les lycées).
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date, datetime, time as dtime
from urllib import robotparser

import requests
from bs4 import BeautifulSoup

from common import make_id, month_num, norm, paris_iso

LIEU = "NEST"
VILLE = "Thionville"
BASE = "https://www.nest-theatre.fr"
USER_AGENT = "culture-widget/1.0 (agenda personnel; +https://github.com/Deynis/event_handler)"

SEASON_LINK = re.compile(r"^https://www\.nest-theatre\.fr/saison/(\d{2})-(\d{2})$")
SHOW_LINK = re.compile(r"^https://www\.nest-theatre\.fr/saison/\d{2}-\d{2}/[a-z0-9-]+-\d+$")
SEANCE = re.compile(r"(\d{1,2})(?:er)?\s+([A-Za-zÀ-ÿ]+)\.?(?:\s+(20\d{2}))?(?:\s+à\s+(\d{1,2})\s*h\s*(\d{2})?)?", re.I)


# ---------- Analyse ----------

def season_years(html: str) -> list[tuple[str, int]]:
    """Liens de saison de l'accueil : [(url, première année)], ex. (…/saison/26-27, 2026)."""
    soup = BeautifulSoup(html, "html.parser")
    seasons = {}
    for a in soup.find_all("a", href=True):
        m = SEASON_LINK.match(a["href"].rstrip("/"))
        if m:
            seasons[m.group(0)] = 2000 + int(m.group(1))
    return sorted(seasons.items(), key=lambda s: s[1])


def show_links(html: str) -> dict[str, list[str]]:
    """Cartes de la page de saison : {url de la fiche: genres de la carte}."""
    soup = BeautifulSoup(html, "html.parser")
    shows: dict[str, list[str]] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].rstrip("/")
        if SHOW_LINK.match(href) and href not in shows:
            shows[href] = [s.get_text(strip=True) for s in a.select(".tag span span") if s.get_text(strip=True)]
    return shows


def parse_seance(text: str, first_year: int):
    """« mardi 4 mai à 20h30 » -> (datetime, a_une_heure) ; None si illisible."""
    m = SEANCE.search(text)
    if not m:
        return None
    month = month_num(m.group(2))
    if not month:
        return None
    year = int(m.group(3)) if m.group(3) else (first_year if month >= 8 else first_year + 1)
    hour, minute = int(m.group(4) or 0), int(m.group(5) or 0)
    try:
        day = date(year, month, int(m.group(1)))
    except ValueError:
        return None
    if hour == 0 and minute == 0:
        return datetime.combine(day, dtime.min), False
    return datetime.combine(day, dtime(hour, minute)), True


def ville_of(place: str | None) -> str:
    """« Escher Theater – Théâtre d'Esch, Esch-sur-Alzette » -> « Esch-sur-Alzette ».

    Sans virgule, la ville n'est sûre que si le lieu la nomme (« Théâtre de
    Thionville ») ; sinon (« salle des fêtes de Fontoy ») on reste vague.
    """
    if place and "," in place:
        return place.rsplit(",", 1)[1].strip()
    if place is None or "thionville" in norm(place):
        return VILLE
    return "Environs de Thionville"


def map_category(tags: list[str]) -> str:
    n = " ".join(norm(t) for t in tags)
    if "concert" in n or "musique" in n:
        return "concert"
    if "festival" in n:
        return "festival"
    return "spectacle"


def parse_show(html: str, url: str, first_year: int, tags: list[str] = ()) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    header = soup.select_one(".header_fiche h1") or soup.find("h1")
    if header is None:
        raise ValueError("titre introuvable")
    title = re.sub(r"\s+", " ", header.get_text(" ", strip=True))
    default_place = soup.select_one(".pratique .lieu")
    default_place = default_place.get_text(" ", strip=True) if default_place else None

    events = []
    for block in soup.select(".pratique_sub_section"):
        heading = block.find("h4")
        if not heading or norm(heading.get_text()) != "seances":
            continue
        for li in block.select("li"):
            strong = li.find("strong")
            place = strong.get_text(" ", strip=True) if strong else default_place
            if place and norm(place) == "en attente":
                place = "Lieu à confirmer"
            when = li.find("span")
            parsed = parse_seance(when.get_text(" ", strip=True) if when else li.get_text(" ", strip=True), first_year)
            if parsed is None:
                continue
            start, has_time = parsed
            if not has_time and not strong:
                continue  # borne d'une période de tournée (lycées, villages), pas une représentation publique
            event = {
                "id": make_id(LIEU, start, title),
                "lieu": LIEU,
                "ville": ville_of(place),
                "categorie": map_category(tags),
                "titre": title,
                "debut": paris_iso(start),
            }
            if not has_time:
                event["fin"] = paris_iso(start.replace(hour=23, minute=59, second=59))
                event["jour_entier"] = True
            notes = [p for p in (place, " / ".join(tags)) if p]
            if notes:
                event["note"] = " - ".join(notes)
            event["url"] = url
            events.append(event)
    return events


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
    if not rp.can_fetch(USER_AGENT, BASE + "/saison/"):
        raise RuntimeError("robots.txt interdit l'accès aux pages de saison")


def fetch_events(pause: float = 1.0) -> list[dict]:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    check_robots(session)

    def get(url: str) -> str:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        r.encoding = "utf-8"
        time.sleep(pause)
        return r.text

    seasons = season_years(get(BASE + "/"))
    if not seasons:
        raise RuntimeError("aucun lien de saison sur l'accueil : la mise en page a probablement changé")

    events, failures, shows = [], 0, 0
    for season_url, first_year in seasons:
        links = show_links(get(season_url))
        print(f"  {season_url} : {len(links)} spectacle(s)")
        for url, tags in links.items():
            shows += 1
            try:
                events.extend(parse_show(get(url), url, first_year, tags))
            except (requests.RequestException, ValueError) as exc:
                failures += 1
                print(f"  fiche ignorée ({exc}) : {url}", file=sys.stderr)

    if shows and failures > 0.2 * shows:
        raise RuntimeError(f"{failures}/{shows} fiches illisibles : la mise en page a probablement changé")
    if not events:
        raise RuntimeError("aucune séance trouvée : la mise en page a probablement changé")
    return events
