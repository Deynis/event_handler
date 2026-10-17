"""Import de programmes saisis à la main (json/*.json) vers data/events.json.

Usage :
    python scripts/import_json.py                     # traite tous les json/*.json
    python scripts/import_json.py json/mon-fichier.json
    python scripts/import_json.py --dry-run json/mon-fichier.json

Format d'entrée : {"source": "<url>", "events": [...]} avec des événements au format
de data/events.json. Adaptations :
  - les genres hors catégories du widget (théâtre, danse...) deviennent « spectacle »,
    le genre d'origine passe dans la note ;
  - « artiste » (non affiché par le widget) est versé dans la note ;
  - sans url, l'événement reçoit l'url « source » du fichier.

Chaque fichier remplace les événements qu'il avait importés la fois précédente
(repérés par leur champ « import »), donc le rejouer après correction est sans risque.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import merge
from common import CATEGORIES

GENRES = {"theatre": "Théâtre", "danse": "Danse", "humour": "Humour", "conference": "Conférence"}


def convert(event: dict, source: str | None, origin: str) -> dict:
    e = dict(event)
    notes = []
    cat = e.get("categorie")
    if cat not in CATEGORIES:
        if cat not in GENRES:
            raise ValueError(f"{e.get('id', '?')} : catégorie inconnue '{cat}'")
        notes.append(GENRES[cat])
        e["categorie"] = "spectacle"
    if e.get("artiste"):
        notes.append(e.pop("artiste"))
    if e.get("note"):
        notes.append(e["note"])
    if notes:
        e["note"] = " - ".join(notes)
    if source and not e.get("url"):
        e["url"] = source
    e["import"] = origin
    return e


def import_jsons(paths: list[Path], dry_run: bool = False) -> int:
    events = merge.load()["events"]
    status = 0
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            fresh = [convert(e, doc.get("source"), path.name) for e in doc["events"]]
        except Exception as exc:  # noqa: BLE001
            print(f"::error::{path.name} : {exc}")
            status = 1
            continue
        print(f"{path.name} : {len(fresh)} événement(s)")
        if dry_run:
            for e in fresh:
                print(f"  {e['debut'][:16]}  [{e['categorie']}] {e['lieu']} : {e['titre']}  {e.get('note', '')}")
            continue
        events = [e for e in events if e.get("import") != path.name] + fresh
    if not dry_run:
        merge.save(merge.purge(events))
    return status


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    args = [a for a in argv if not a.startswith("--")]
    paths = [Path(a) for a in args] or sorted((merge.ROOT / "json").glob("*.json"))
    if not paths:
        print("Aucun JSON à traiter (dossier json/ vide).")
        return 0
    return import_jsons(paths, dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
