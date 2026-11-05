"""Tests sans réseau : python -m unittest discover -s scripts/tests -v"""
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import merge  # noqa: E402
import scrape_kinepolis  # noqa: E402
from common import TZ  # noqa: E402
from sources import arsenal, nest, philharmonie  # noqa: E402

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

    def test_any_dash_separates_infos(self):
        import extract_pdf
        for dash in "-–—":
            film = extract_pdf.Film(["La vérité du sol"], [f"François Legrand - 0h52 {dash} France"])
            (info,) = film.infos()
            self.assertEqual((info["minutes"], info["country"], info["extras"]), (52, "France", []))


def words(text: str, x1: float = 100) -> list[dict]:
    return [{"text": text, "x1": x1}]


class TestUpcomingSlots(unittest.TestCase):
    """Une date sans heure, suivie d'une ligne par séance (« 14h30 : Partie 1 »)."""
    WEEK = (date(2026, 11, 11), date(2026, 11, 17))

    def setUp(self):
        import extract_pdf
        self.ep = extract_pdf
        self.films = [
            extract_pdf.Film(["La Bataille de Gaulle - Partie 1 :", "L'Âge de Fer"], ["Antonin Baudry - 2h40 - France"]),
            extract_pdf.Film(["La Bataille de Gaulle - Partie 2 :", "J'écris ton nom"], ["Antonin Baudry - 2h40 - France"]),
        ]

    def parse(self, lines, films=None):
        entries = self.ep.parse_date_entries([words(t) for t in lines], right_edge=500)
        warnings = []
        return self.ep.upcoming_events(films or self.films, entries, None, *self.WEEK, warnings), warnings

    def test_each_film_gets_its_time(self):
        events, warnings = self.parse([
            "Dimanche 22 novembre", "Ciné-débat", "14h30 : Partie 1 : L'Âge de Fer", "17h30 : Table Ronde",
            "18h30 : Buffet dînatoire offert", "19h30 : Partie 2 : J'écris ton nom"])
        self.assertEqual(warnings, [])
        self.assertEqual([e["debut"] for e in events], ["2026-11-22T14:30:00+01:00", "2026-11-22T19:30:00+01:00"])
        self.assertEqual(events[0]["duree_min"], 160)
        self.assertEqual(events[0]["note"], "Ciné-débat - 17h30 : Table Ronde - 18h30 : Buffet dînatoire offert")

    def test_film_without_time_is_reported(self):
        events, warnings = self.parse(["Dimanche 22 novembre", "14h30 : Partie 1 : L'Âge de Fer"])
        self.assertEqual(events, [])
        self.assertEqual(len(warnings), 1)

    def test_several_dates_one_without_time_is_reported(self):
        events, warnings = self.parse(["Dimanche 22 novembre", "Lundi 23 novembre à 20h"])
        self.assertEqual(events, [])
        self.assertEqual(len(warnings), 1)

    def test_date_with_time_unchanged(self):
        film = self.ep.Film(["Torso"], ["Sergio Martino - 1h30 - Italie - VOST"])
        events, warnings = self.parse(["Vendredi 27 novembre à 20h30", "Le Retour du Bis"], [film])
        self.assertEqual(warnings, [])
        self.assertEqual((events[0]["debut"], events[0]["note"]), ("2026-11-27T20:30:00+01:00", "Le Retour du Bis"))

    def test_date_inside_a_note_stays_a_note(self):
        entries = self.ep.parse_date_entries(
            [words("Vendredi 27 novembre à 20h30"), words("Samedi 28 novembre : rencontre")], right_edge=500)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["note"], "Samedi 28 novembre : rencontre")


PDF =Path(__file__).resolve().parents[2] / "pdf" / "scala-2026-09-30.pdf"


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


JPG = Path(__file__).resolve().parents[2] / "jpg" / "grille_horaire_scala_S46_A5_1.jpg"


def has_tesseract_fra() -> bool:
    try:
        import pytesseract
        return "fra" in pytesseract.get_languages()
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(JPG.exists() and has_tesseract_fra(), "image d'exemple ou Tesseract (fra) absent")
class TestScalaJpg(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import extract_jpg
        cls.page = extract_jpg.parse_image(JPG)
        cls.by_title = {}
        for e in cls.page.events:
            cls.by_title.setdefault(e["titre"], []).append(e)

    def test_week_and_counts(self):
        self.assertEqual((self.page.week_start, self.page.week_end), (date(2026, 11, 11), date(2026, 11, 17)))
        self.assertEqual(self.page.warnings, [])
        in_week = [e for e in self.page.events if e["debut"][:10] <= "2026-11-17"]
        self.assertEqual(len(in_week), 58)  # nombre d'heures dans la grille

    def test_grid(self):
        lucy = sorted(e["debut"][:16] for e in self.by_title["Le Mystère Lucy Lost"])
        self.assertEqual(len(lucy), 4)
        self.assertEqual((lucy[0], lucy[-1]), ("2026-11-11T13:50", "2026-11-16T18:25"))
        wild = self.by_title["Wild Horse Nine"][0]
        self.assertEqual((wild["duree_min"], wild["version"]), (118, "VOST"))
        self.assertEqual(self.by_title["Entre le ciel et l'enfer"][0]["note"], "Cycle Japanese Noire")
        self.assertEqual(self.by_title["Petite Casbah"][0]["note"], "Jeune public, dès 6 ans")

    def test_band_note_and_any_dash(self):
        sol = self.by_title["La vérité du sol"][0]
        self.assertEqual((sol["duree_min"], sol["note"], sol["categorie"]), (52, "Festival Permaculture 2026", "festival"))

    def test_upcoming_events(self):
        # une date, puis une heure par film sur les lignes suivantes
        self.assertEqual(self.by_title["La Bataille de Gaulle - Partie 1 : L'Âge de Fer"][0]["debut"], "2026-11-22T14:30:00+01:00")
        self.assertEqual(self.by_title["La Bataille de Gaulle - Partie 2 : J'écris ton nom"][0]["debut"], "2026-11-22T19:30:00+01:00")
        # double programme : une seule date pour deux films
        self.assertEqual(self.by_title["Torso"][0]["debut"], "2026-11-27T20:30:00+01:00")
        self.assertEqual(self.by_title["La Tarentule au ventre noir"][0]["debut"], "2026-11-27T20:30:00+01:00")


PHIL_SITEMAP = """<urlset>
<url><loc>https://www.philharmonie.lu/fr/programme/2026-27/mozart-requiem-000000e9001d169c</loc><lastmod>2026-10-01T00:00:00+02:00</lastmod></url>
<url><loc>https://www.philharmonie.lu/fr/programme/2026-27/abonnements/pick-mix-0000013e0000057a</loc><lastmod>2026-10-01T00:00:00+02:00</lastmod></url>
<url><loc>https://www.philharmonie.lu/fr/programme/2025-26/vieux-concert-000000e9001a0001</loc><lastmod>2025-10-01T00:00:00+02:00</lastmod></url>
<url><loc>https://www.philharmonie.lu/fr/programme</loc></url>
</urlset>"""

PHIL_PAGE = """<html><head>
<meta property="og:title" content="{og}" /></head><body>
<h1 class="hero__title" data-is-kids="{kids}">M<span>oz</span>art Requiem</h1>
<ul class="event-details__specs">
 <li class="event-details__spec"><span class="event-details__spec-label">Date</span><span class="event-details__spec-value">samedi 06.03.27</span></li>
 <li class="event-details__spec"><span class="event-details__spec-label">Salle</span><span class="event-details__spec-value">Grand Auditorium</span></li>
</ul></body></html>"""


class TestPhilharmonie(unittest.TestCase):
    URL = "https://www.philharmonie.lu/fr/programme/2026-27/mozart-requiem-000000e9001d169c"

    def test_sitemap_keeps_current_season_event_pages_only(self):
        entries = philharmonie.parse_sitemap(PHIL_SITEMAP, date(2026, 10, 18))
        self.assertEqual(list(entries), [self.URL])

    def test_season_end(self):
        self.assertTrue(philharmonie.season_is_current(2026, 27, date(2027, 7, 31)))
        self.assertFalse(philharmonie.season_is_current(2025, 26, date(2026, 10, 18)))
        self.assertTrue(philharmonie.season_is_current(2099, 0, date(2099, 10, 1)))

    def test_event_page(self):
        html = PHIL_PAGE.format(og="Mozart Requiem | 06.03.2027 19:30", kids="False")
        e = philharmonie.parse_event_page(html, self.URL)
        self.assertEqual(e["titre"], "Mozart Requiem")
        self.assertEqual(e["debut"], "2027-03-06T19:30:00+01:00")
        self.assertEqual((e["lieu"], e["ville"], e["categorie"]), ("Philharmonie Luxembourg", "Luxembourg", "concert"))
        self.assertEqual(e["note"], "Grand Auditorium")
        self.assertNotIn("fin", e)

    def test_title_with_pipe_and_no_time(self):
        html = PHIL_PAGE.format(og="Jazz | Late Night | 25.10.2026", kids="False")
        e = philharmonie.parse_event_page(html, self.URL)
        self.assertEqual(e["titre"], "Jazz | Late Night")
        self.assertTrue(e["jour_entier"])
        self.assertEqual(e["fin"], "2026-10-25T23:59:59+01:00")

    def test_kids_event_is_skipped(self):
        html = PHIL_PAGE.format(og="Hopeless at Horror | 25.10.2026 11:00", kids="True")
        self.assertIsNone(philharmonie.parse_event_page(html, self.URL))

    def test_unexpected_page_raises(self):
        with self.assertRaises(ValueError):
            philharmonie.parse_event_page("<html><h1>Rien</h1></html>", self.URL)


class TestKinepolis(unittest.TestCase):
    CARDS = [
        {"titre": "Les Misérables", "href": "/movies/detail/36821/HO00014610/0/les-miserables",
         "salles": [{"version": "Version Française", "salle": "Salle 3", "heures": ["10:30"]},
                    {"version": "Version Originale Sous-Titrée", "salle": "Salle 10", "heures": ["13:40", "19:50"]}]},
        {"titre": "", "href": None, "salles": []},
    ]

    def test_build_events(self):
        events = scrape_kinepolis.build_events(date(2026, 10, 18), self.CARDS, {"36821": 179})
        self.assertEqual([e["debut"] for e in events],
                         ["2026-10-18T10:30:00+02:00", "2026-10-18T13:40:00+02:00", "2026-10-18T19:50:00+02:00"])
        first = events[0]
        self.assertEqual((first["lieu"], first["categorie"], first["version"], first["note"], first["duree_min"]),
                         ("Kinepolis Thionville", "cinema", "VF", "Salle 3", 179))
        self.assertEqual(events[1]["version"], "VOST")
        self.assertEqual(first["url"], "https://kinepolis.fr/movies/detail/36821/HO00014610/0/les-miserables")

    def test_versions(self):
        cases = {"Version Française": "VF", "Version Originale Sous-Titrée": "VOST", "Version Originale": "VO",
                 "Version Allemande (Sous-tîtres : Français)": "VOST", "(Sous-titres - Anglais)": "VO ST anglais",
                 "": None}
        for label, expected in cases.items():
            self.assertEqual(scrape_kinepolis.map_version(label), expected, label)

    def test_corporate_id(self):
        self.assertEqual(scrape_kinepolis.corporate_id("/movies/detail/36821/HO00014610/0/x"), 36821)
        self.assertIsNone(scrape_kinepolis.corporate_id(None))


NEST_SAISON = """<div class="bloc-prog">
<article class="item"><a href="https://www.nest-theatre.fr/saison/26-27/tadam-960"><h1>Tadam</h1>
 <p class="tag"><span><span>Théâtre</span><span>En famille</span></span></p></a></article>
<a href="https://www.nest-theatre.fr/saison/26-27">Saison</a>
</div>"""

NEST_FICHE = """<header class="header_fiche"><h1>Huit Rois  - Sarkhollande</h1></header>
<div class="pratique"><div class="pratique_sub_section"><p class="lieu">Théâtre de Thionville - grande salle</p></div>
<div class="pratique_sub_section"><h4>Séances</h4><ul>
 <li><a><strong>Théâtre de Thionville - grande salle</strong><br/><span>mardi  4 mai &agrave; 20<abbr title='heure'>h</abbr>30</span></a></li>
 <li><a><strong>Escher Theater – Théâtre d'Esch, Esch-sur-Alzette</strong><br/><span>jeudi 14 janvier &agrave; 20<abbr>h</abbr></span></a></li>
 <li><a><strong>En attente</strong><br/><span>vendredi 2 juillet &agrave; 00<abbr>h</abbr></span></a></li>
 <li><a><span>lundi 18 janvier &agrave; 00<abbr>h</abbr></span></a></li>
</ul></div></div>
<div class="footer"><p class="tag"><span><span>Autre spectacle</span></span></p></div>"""


class TestNest(unittest.TestCase):
    URL = "https://www.nest-theatre.fr/saison/26-27/huit-rois-sarkhollande-964"

    def test_season_page(self):
        self.assertEqual(nest.season_years(NEST_SAISON), [("https://www.nest-theatre.fr/saison/26-27", 2026)])
        self.assertEqual(nest.show_links(NEST_SAISON),
                         {"https://www.nest-theatre.fr/saison/26-27/tadam-960": ["Théâtre", "En famille"]})

    def test_seance_year_from_season(self):
        self.assertEqual(nest.parse_seance("mardi 3 novembre à 20h", 2026), (datetime(2026, 11, 3, 20, 0), True))
        self.assertEqual(nest.parse_seance("mardi 4 mai à 20 h 30", 2026), (datetime(2027, 5, 4, 20, 30), True))
        self.assertEqual(nest.parse_seance("lundi 18 janvier à 00h", 2026), (datetime(2027, 1, 18), False))
        self.assertIsNone(nest.parse_seance("bientôt", 2026))

    def test_show_page(self):
        events = nest.parse_show(NEST_FICHE, self.URL, 2026, ["Théâtre"])
        self.assertEqual([e["debut"] for e in events],
                         ["2027-05-04T20:30:00+02:00", "2027-01-14T20:00:00+01:00", "2027-07-02T00:00:00+02:00"])
        first, esch, unknown = events
        self.assertEqual((first["titre"], first["lieu"], first["ville"]), ("Huit Rois - Sarkhollande", "NEST", "Thionville"))
        self.assertEqual(first["note"], "Théâtre de Thionville - grande salle - Théâtre")
        self.assertEqual(esch["ville"], "Esch-sur-Alzette")
        self.assertTrue(unknown["jour_entier"])
        self.assertEqual((unknown["ville"], unknown["note"]), ("Environs de Thionville", "Lieu à confirmer - Théâtre"))

    def test_ville(self):
        self.assertEqual(nest.ville_of("salle des fêtes de Fontoy"), "Environs de Thionville")
        self.assertEqual(nest.ville_of("Centre-ville de Thionville"), "Thionville")


if __name__ == "__main__":
    unittest.main()
