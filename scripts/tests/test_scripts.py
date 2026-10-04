"""Tests sans réseau : python -m unittest discover -s scripts/tests -v"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import merge  # noqa: E402
from common import TZ  # noqa: E402
from sources import arsenal  # noqa: E402

# Deux mises en page plausibles : lien qui enveloppe toute la carte, ou lien sur le titre seul.
HTML_WRAPPED = """
<ul>
 <li><a href="/fr/programmation/saison-26-27/arsenal/sauvage"><span>Concert</span>
   <h3>Sauvage</h3><p>Mathilde Monnier, Eve Risser</p><p>9 oct. 2026, 20h</p><p>Arsenal</p></a></li>
 <li><a href="/fr/programmation/saison-26-27/exposition/cimarron"><span>Exposition</span>
   <h3>Cimarron</h3><p>Charles Fréger</p><p>13 sept. → 15 nov. 2026</p><p>Arsenal</p></a></li>
 <li><a href="/fr/programmation/saison-26-27/en-famille/ile-aux-bebes-musicale-12"><span>En famille (3 mois à 3 ans)</span>
   <h3>Île aux bébés musicale</h3><p>20 oct. 2026</p><p>Arsenal</p><span>Complet</span></a></li>
 <li><a href="/fr/programmation/saison-26-27/concert/thea"><span>Concert</span>
   <h3>THÉA</h3><p>8 oct. 2026, 20h</p><p>BAM</p></a></li>
</ul>"""

HTML_SPLIT = """
<div class="card"><div class="meta">Concert · Arsenal</div>
  <h3><a href="/fr/programmation/saison-26-27/arsenal/sauvage">Sauvage</a></h3>
  <div>9 oct. 2026, 20h30</div></div>
<div class="card"><div>Ciné-Cité</div>
  <h3><a href="/fr/programmation/saison-26-27/evenement/lamour-est-un-crime-parfait-1">L'Amour est un crime parfait</a></h3>
  <div>7 oct. 2026, 20h</div><div>Arsenal</div></div>"""


class TestDates(unittest.TestCase):
    def test_single_with_time(self):
        s, e, allday = arsenal.parse_date_line("6 oct. 2026, 20h")
        self.assertEqual((s, e, allday), (datetime(2026, 10, 6, 20, 0), None, False))

    def test_single_with_minutes(self):
        s, _, _ = arsenal.parse_date_line("9 oct. 2026, 20h30")
        self.assertEqual(s, datetime(2026, 10, 9, 20, 30))

    def test_single_without_time(self):
        s, e, allday = arsenal.parse_date_line("20 oct. 2026")
        self.assertTrue(allday)
        self.assertEqual((s, e), (datetime(2026, 10, 20), datetime(2026, 10, 20, 23, 59, 59)))

    def test_range(self):
        s, e, allday = arsenal.parse_date_line("13 sept. → 15 nov. 2026")
        self.assertEqual((s.date().isoformat(), e.date().isoformat(), allday), ("2026-09-13", "2026-11-15", True))

    def test_range_across_new_year(self):
        s, e, _ = arsenal.parse_date_line("20 déc. → 5 janv. 2027")
        self.assertEqual((s.year, e.year), (2026, 2027))

    def test_not_a_date(self):
        self.assertIsNone(arsenal.parse_date_line("50 ans de l'Orchestre : Mozart"))
        self.assertIsNone(arsenal.parse_date_line("Rap session #20"))
        self.assertIsNone(arsenal.safe_parse_date_line("31 nov. 2026"))


class TestParsing(unittest.TestCase):
    def test_wrapped_layout(self):
        cards = arsenal.parse_listing(HTML_WRAPPED, arsenal.BASE)
        self.assertEqual(len(cards), 4)
        events = [e for e in map(arsenal.build_event, cards) if e]
        self.assertEqual(len(events), 3)  # le concert de la BAM est écarté
        by_title = {e["titre"]: e for e in events}
        self.assertEqual(by_title["Sauvage"]["categorie"], "concert")
        self.assertEqual(by_title["Sauvage"]["debut"], "2026-10-09T20:00:00+02:00")
        self.assertEqual(by_title["Sauvage"]["note"], "Mathilde Monnier, Eve Risser")
        self.assertEqual(by_title["Cimarron"]["categorie"], "expo")
        self.assertTrue(by_title["Cimarron"]["jour_entier"])
        self.assertEqual(by_title["Cimarron"]["fin"], "2026-11-15T23:59:59+01:00")
        bebes = by_title["Île aux bébés musicale"]
        self.assertEqual(bebes["categorie"], "spectacle")
        self.assertEqual(bebes["note"], "3 mois à 3 ans - Complet")

    def test_split_layout(self):
        cards = arsenal.parse_listing(HTML_SPLIT, arsenal.BASE)
        events = [e for e in map(arsenal.build_event, cards) if e]
        self.assertEqual({e["titre"] for e in events}, {"Sauvage", "L'Amour est un crime parfait"})
        self.assertEqual({e["categorie"] for e in events}, {"concert", "cinema"})
        self.assertTrue(all(e["url"].startswith("https://www.citemusicale-metz.fr/") for e in events))


class TestMerge(unittest.TestCase):
    def ev(self, id_, debut, fin=None, lieu="X"):
        e = {"id": id_, "lieu": lieu, "ville": "V", "categorie": "concert", "titre": id_, "debut": debut}
        if fin:
            e["fin"] = fin
        return e

    def test_purge_removes_yesterday_keeps_today_and_ongoing(self):
        now = datetime(2026, 10, 10, 5, 0, tzinfo=TZ)
        events = [
            self.ev("hier", "2026-10-09T20:00:00+02:00"),
            self.ev("tot-ce-matin", "2026-10-10T09:00:00+02:00"),
            self.ev("demain", "2026-10-11T20:00:00+02:00"),
            self.ev("expo-en-cours", "2026-09-13T00:00:00+02:00", "2026-11-15T23:59:59+01:00"),
            self.ev("expo-finie-hier", "2026-09-01T00:00:00+02:00", "2026-10-09T23:59:59+02:00"),
        ]
        kept = {e["id"] for e in merge.purge(events, now)}
        self.assertEqual(kept, {"tot-ce-matin", "demain", "expo-en-cours"})

    def test_replace_lieu_keeps_other_venues(self):
        events = [self.ev("a", "2026-10-10T20:00:00+02:00", lieu="A"), self.ev("b", "2026-10-10T20:00:00+02:00", lieu="B")]
        out = merge.replace_lieu(events, "A", [self.ev("a2", "2026-10-11T20:00:00+02:00", lieu="A")])
        self.assertEqual({e["id"] for e in out}, {"a2", "b"})

    def test_validate_rejects_bad_documents(self):
        with self.assertRaises(ValueError):
            merge.validate({"events": [{"id": "x"}]})
        with self.assertRaises(ValueError):
            merge.validate({"events": [self.ev("a", "2026-10-10T20:00:00")]})  # pas de fuseau
        with self.assertRaises(ValueError):
            merge.validate({"events": [self.ev("a", "2026-10-10T20:00:00+02:00"), self.ev("a", "2026-10-11T20:00:00+02:00")]})
        merge.validate({"events": [self.ev("a", "2026-10-10T20:00:00+02:00")]})


if __name__ == "__main__":
    unittest.main()
