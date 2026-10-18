"""Programmation du Kinepolis Thionville, récupérée en pilotant un vrai navigateur.

Le site de Kinepolis bloque les requêtes simples (page 403 « Suspicious Activity
Detected ») et même un Chromium sans fenêtre : le script ouvre donc une fenêtre
Chromium visible via Playwright, choisit tour à tour chaque date du sélecteur
« À la date » et lit les séances affichées (film, version, salle, heures).
La durée des films vient des données que la page embarque (Drupal.settings).

À lancer en local (pas dans GitHub Actions : l'IP d'un serveur serait bloquée) :
    pip install -r requirements-kinepolis.txt
    python -m playwright install chromium
    python scripts/scrape_kinepolis.py              # met à jour data/events.json
    python scripts/scrape_kinepolis.py --dry-run    # affiche sans écrire
    python scripts/scrape_kinepolis.py --max-dates 3
puis commit + push de data/events.json.
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime

import merge
from common import make_id, norm, paris_iso

LIEU = "Kinepolis Thionville"
VILLE = "Thionville"
BASE = "https://kinepolis.fr"
PAGE_URL = BASE + "/?complex=KTHIO&main_section=aujourd%27hui"
DATE_FILTER = ".date-filter > div:nth-child(1) > div:nth-child(2)"
PAUSE_MS = 1000  # entre deux dates, pour rester un visiteur ordinaire

# Lit les films et séances visibles (le filtre de date masque les autres).
READ_VISIBLE = """() => {
  const shown = el => el.offsetParent !== null;
  return [...document.querySelectorAll('.movie-container-wrapper-full')].filter(shown).map(card => {
    const link = card.querySelector('.movie-overview-title')?.closest('a');
    return {
      titre: card.querySelector('.movie-overview-title')?.textContent.trim(),
      href: link?.getAttribute('href'),
      salles: [...card.querySelectorAll('.movie-timeline-hall-wrapper')].filter(shown).map(h => ({
        version: h.querySelector('.movie-timeline-title')?.textContent.trim(),
        salle: h.querySelector('.movie-hall-wrapper')?.firstChild?.textContent.trim(),
        heures: [...h.querySelectorAll('.time-block')].filter(shown).map(t => t.textContent.trim()),
      })),
    };
  });
}"""

# Durée (minutes) par identifiant de film « corporateId », tirée des données de la page.
READ_DURATIONS = """() => {
  const v = (window.Drupal && Drupal.settings && Drupal.settings.variables) || {};
  const out = {};
  for (const key of ['current_movies', 'future_movies'])
    for (const f of (v[key] && v[key].films) || [])
      if (f.corporateId && f.duration) out[f.corporateId] = f.duration;
  return out;
}"""


def map_version(label: str | None) -> str | None:
    n = norm(label or "")
    if not n:
        return None
    if n.startswith("version francaise"):
        return "VF"
    if "sous" in n:  # « Version Allemande (Sous-titres : Français) », « (Sous-titres - Anglais) »
        return "VO ST anglais" if "anglais" in n else "VOST"
    if "originale" in n:
        return "VO"
    return label


def corporate_id(href: str | None) -> int | None:
    """/movies/detail/36821/HO00014610/0/les-miserables -> 36821"""
    parts = (href or "").strip("/").split("/")
    if len(parts) >= 3 and parts[0] == "movies" and parts[2].isdigit():
        return int(parts[2])
    return None


def build_events(day: date, cards: list[dict], durations: dict) -> list[dict]:
    events = []
    for card in cards:
        titre = re.sub(r"\s+", " ", card.get("titre") or "").strip()
        if not titre:
            continue
        url = BASE + card["href"] if card.get("href") else PAGE_URL
        duration = durations.get(str(corporate_id(card.get("href"))))
        for hall in card["salles"]:
            for hour in hall["heures"]:
                try:
                    h, m = (int(x) for x in hour.split(":"))
                except ValueError:
                    continue
                start = datetime(day.year, day.month, day.day, h, m)
                event = {
                    "id": make_id(LIEU, start, titre),
                    "lieu": LIEU,
                    "ville": VILLE,
                    "categorie": "cinema",
                    "titre": titre,
                    "debut": paris_iso(start),
                }
                if duration:
                    event["duree_min"] = duration
                version = map_version(hall.get("version"))
                if version:
                    event["version"] = version
                if hall.get("salle"):
                    event["note"] = hall["salle"]
                event["url"] = url
                events.append(event)
    return events


def accept_cookies(page) -> None:
    button = page.get_by_role("button", name="Tout accepter")
    if button.count():
        button.first.click()
        page.wait_for_timeout(500)


def fetch_events(max_dates: int | None = None, headless: bool = False) -> list[dict]:
    from playwright.sync_api import sync_playwright  # import tardif : les tests n'en ont pas besoin

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(locale="fr-FR")
        response = page.goto(PAGE_URL, wait_until="networkidle", timeout=60000)
        if response is None or response.status != 200:
            raise RuntimeError(f"page Kinepolis inaccessible (HTTP {response.status if response else '?'})")
        accept_cookies(page)

        selector = page.locator(DATE_FILTER)
        options = selector.locator("select option").evaluate_all(
            "opts => opts.map(o => ({value: o.value, label: o.textContent.trim()}))")
        options = [o for o in options if o["value"] != "all"][:max_dates]
        if not options:
            raise RuntimeError("sélecteur de date introuvable : la mise en page a probablement changé")
        durations = {str(k): v for k, v in page.evaluate(READ_DURATIONS).items()}

        events = []
        for i, option in enumerate(options):
            if i:
                page.wait_for_timeout(PAUSE_MS)
            selector.locator(".CaptionCont").click()
            selector.locator("li.opt", has_text=option["label"]).first.click()
            page.wait_for_timeout(500)
            day = date.fromisoformat(option["value"])
            found = build_events(day, page.evaluate(READ_VISIBLE), durations)
            print(f"  {option['label']} : {len(found)} séance(s)")
            events.extend(found)
        browser.close()

    if not events:
        raise RuntimeError("aucune séance trouvée : la mise en page a probablement changé")
    return events


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    headless = "--headless" in argv
    max_dates = int(argv[argv.index("--max-dates") + 1]) if "--max-dates" in argv else None

    print(f"[{LIEU}] récupération...")
    fresh = fetch_events(max_dates, headless)
    print(f"[{LIEU}] {len(fresh)} séance(s) récupérée(s)")
    if dry_run:
        for e in fresh[:15]:
            print(f"  {e['debut'][:16]}  {e['titre']}  ({e.get('version', '-')}, {e.get('note', '-')}, {e.get('duree_min', '?')} min)")
        return 0
    events = merge.replace_lieu(merge.load()["events"], LIEU, fresh)
    merge.save(merge.purge(events))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
