"""Orchestrateur : lance chaque parseur, isole les erreurs, purge et écrit events.json.

- Une source qui échoue (ou ne renvoie rien) conserve ses dernières données valides.
- La purge des événements passés et l'écriture du fichier ont toujours lieu.
- Code de sortie 1 si au moins une source a échoué (le workflow GitHub passe alors
  en échec et GitHub envoie un e-mail), 0 sinon.

Pour ajouter une source : créer scripts/sources/<nom>.py avec les constantes LIEU
et une fonction fetch_events() -> list[dict], puis l'ajouter à SOURCES ci-dessous.
"""
from __future__ import annotations

import sys
import traceback

import merge
from sources import arsenal

SOURCES = [arsenal]


def main() -> int:
    doc = merge.load()
    events = doc["events"]
    failures = []

    for source in SOURCES:
        print(f"[{source.LIEU}] récupération...")
        try:
            fresh = source.fetch_events()
            events = merge.replace_lieu(events, source.LIEU, fresh)
            print(f"[{source.LIEU}] {len(fresh)} événement(s) récupéré(s)")
        except Exception as exc:  # noqa: BLE001 - on isole volontairement toute erreur
            failures.append(source.LIEU)
            traceback.print_exc()
            print(f"::error::[{source.LIEU}] échec : {exc} - données précédentes conservées")

    merge.save(merge.purge(events))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
