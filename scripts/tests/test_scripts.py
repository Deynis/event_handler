"""Tests sans réseau : python -m unittest discover -s scripts/tests -v"""
import sys
import unittest
from datetime import date, datetime
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


class TestInfoLines(unittest.TestCase):
    def test_wrapped_info_line(self):
        import extract_pdf
        film = extract_pdf.Film(["Chien bleu"], ["Dominique Pochat, Jean-Christophe Ribot, Benoît", "Laborde - 0h33 - France - dès 3 ans"])
        (info,) = film.infos()
        self.assertEqual((info["minutes"], info["country"], info["extras"]), (33, "France", ["dès 3 ans"]))

    def test_several_films_in_one_title(self):
        import extract_pdf
        film = extract_pdf.Film(["Puppet Master I, II & III"], [
            "David Schmoeller - 1h30 - USA - VOST", "David Allen - 1h28 - USA - VOST", "David DeCoteau - 1h26 - USA - VOST"])
        self.assertEqual(len(film.infos()), 3)
        minutes, version, _ = extract_pdf.film_summary(film)
        self.assertEqual((minutes, version), (None, "VOST"))


PDF = Path(__file__).resolve().parents[2] / "pdf" / "scala-2026-09-30.pdf"


@unittest.skipUnless(PDF.exists(), "PDF d'exemple absent")
class TestScalaPdf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import extract_pdf
        cls.page = extract_pdf.parse_pdf(PDF)
        cls.by_title = {}
        for e in cls.page.events:
            cls.by_title.setdefault(e["titre"], []).append(e)

    def test_week_and_counts(self):
        self.assertEqual((self.page.week_start, self.page.week_end), (date(2026, 9, 30), date(2026, 10, 6)))
        self.assertEqual(self.page.warnings, [])
        in_week = [e for e in self.page.events if e["debut"][:10] <= "2026-10-06"]
        self.assertEqual(len(in_week), 65)  # nombre d'heures dans la grille du PDF

    def test_memoire_de_fille_columns(self):
        times = sorted(e["debut"][:16] for e in self.by_title["Mémoire de fille"])
        self.assertEqual(len(times), 15)
        self.assertEqual(times[0], "2026-09-30T13:35")
        self.assertEqual(times[-1], "2026-10-06T13:20")
        self.assertIn("2026-10-03T14:25", times)  # samedi

    def test_metadata(self):
        rose = self.by_title["Rose"][0]
        self.assertEqual((rose["duree_min"], rose["version"], rose["note"]), (94, "VOST", "Dernière semaine"))
        self.assertEqual(self.by_title["La Vie en relief - Jacques Henri Lartigue"][0]["note"], "3D")
        self.assertEqual(self.by_title["Mon vieux"][0]["debut"], "2026-10-06T20:00:00+02:00")

    def test_upcoming_events(self):
        insecticide = self.by_title["Insecticide, comment l'agrochimie a tué les insectes"][0]
        self.assertEqual(insecticide["debut"], "2026-10-16T20:00:00+02:00")
        self.assertEqual(insecticide["categorie"], "festival")
        puppet = self.by_title["Puppet Master I, II & III"][0]
        self.assertEqual(puppet["categorie"], "cinema")  # pas rattaché au festival
        self.assertNotIn("duree_min", puppet)
        buffet = self.by_title["Au fil de l'eau, de l'insouciance à la désobéïssance"][0]
        self.assertIn("Association Franco-Africaine de Moselle", buffet["note"])


if __name__ == "__main__":
    unittest.main()
