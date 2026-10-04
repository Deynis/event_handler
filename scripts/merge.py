"""Fusion, validation et purge de data/events.json.

Lancé seul (`python scripts/merge.py`), ce script ne fait que purger les
événements passés et revalider le fichier.

Règle de purge : on supprime tout événement dont la fin (ou le début s'il n'a
pas de fin) est antérieure au début de la journée en cours (heure de Paris).
Les événements de la veille disparaissent donc au premier passage du jour ;
ceux du jour même restent jusqu'au lendemain.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from common import CATEGORIES, now_paris, parse_iso

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "events.json"

REQUIRED = ("id", "lieu", "ville", "categorie", "titre", "debut")


def load(path: Path = DATA_FILE) -> dict:
    if not path.exists():
        return {"updated_at": None, "events": []}
    return json.loads(path.read_text(encoding="utf-8"))


def end_of(event: dict) -> datetime:
    return parse_iso(event.get("fin") or event["debut"])


def purge(events: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or now_paris()
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    kept = [e for e in events if end_of(e) >= cutoff]
    print(f"Purge : {len(events) - len(kept)} événement(s) passé(s) supprimé(s), {len(kept)} conservé(s).")
    return kept


def replace_lieu(events: list[dict], lieu: str, new_events: list[dict]) -> list[dict]:
    """Remplace tous les événements d'un lieu par la liste fraîchement récupérée."""
    return [e for e in events if e.get("lieu") != lieu] + new_events


def dedupe_and_sort(events: list[dict]) -> list[dict]:
    by_id = {}
    for e in events:
        by_id[e["id"]] = e  # le dernier gagne
    return sorted(by_id.values(), key=lambda e: (parse_iso(e["debut"]), e["titre"]))


def validate(doc: dict) -> None:
    """Lève ValueError si le document risquerait de casser le widget."""
    if not isinstance(doc.get("events"), list):
        raise ValueError("'events' doit être une liste")
    seen = set()
    for i, e in enumerate(doc["events"]):
        label = f"événement #{i} ({e.get('id', '?')})"
        for key in REQUIRED:
            if not isinstance(e.get(key), str) or not e[key].strip():
                raise ValueError(f"{label} : champ '{key}' manquant ou vide")
        if e["categorie"] not in CATEGORIES:
            raise ValueError(f"{label} : catégorie inconnue '{e['categorie']}'")
        if e["id"] in seen:
            raise ValueError(f"{label} : id en double")
        seen.add(e["id"])
        try:
            debut = parse_iso(e["debut"])
            fin = parse_iso(e["fin"]) if e.get("fin") else None
        except ValueError as exc:
            raise ValueError(f"{label} : date invalide ({exc})") from exc
        if debut.tzinfo is None or (fin is not None and fin.tzinfo is None):
            raise ValueError(f"{label} : la date doit contenir un fuseau horaire")
        if fin is not None and fin < debut:
            raise ValueError(f"{label} : 'fin' est avant 'debut'")
        if "jour_entier" in e and not isinstance(e["jour_entier"], bool):
            raise ValueError(f"{label} : 'jour_entier' doit être un booléen")


def save(events: list[dict], path: Path = DATA_FILE) -> None:
    doc = {
        "updated_at": now_paris().isoformat(timespec="seconds"),
        "events": dedupe_and_sort(events),
    }
    validate(doc)  # on n'écrit jamais un fichier invalide
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{path.name} écrit : {len(doc['events'])} événement(s).")


def main() -> int:
    doc = load()
    save(purge(doc["events"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
