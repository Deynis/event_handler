"""Import du PDF hebdomadaire de La Scala (Thionville) vers data/events.json.

Usage :
    python scripts/extract_pdf.py                    # traite tous les pdf/*.pdf
    python scripts/extract_pdf.py pdf/mon-fichier.pdf
    python scripts/extract_pdf.py --dry-run pdf/mon-fichier.pdf   # affiche sans écrire

Principe : la grille du PDF est dessinée avec des rectangles (filets rouges entre
les films, bandeaux de titre, séparateurs de colonnes). On s'appuie sur cette
géométrie plutôt que sur le texte brut :
  - chaque film = une ligne de la grille (entre deux filets) ;
  - colonne = jour de la semaine (Mer. -> Mar.), la date vient de l'en-tête
    « Horaires du mercredi 30 septembre au mardi 6 octobre 2026 » ;
  - les bandeaux (« Dernière semaine », « Jeune public »...) deviennent la note
    des films qui les suivent ;
  - sous « Événements à venir », chaque film est associé à sa date écrite en toutes
    lettres (« Vendredi 16 octobre à 20h00 »).

L'import d'un PDF remplace tous les événements de La Scala de sa semaine, puis les
événements à venir sont ajoutés. Un PDF d'une autre semaine n'est pas touché.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

import pdfplumber

import merge
from common import make_id, month_num, norm, paris_iso, parse_iso

LIEU = "La Scala"
VILLE = "Thionville"
URL = "https://www.thionville.fr/scala/programmation-cinema"

TIME_RE = re.compile(r"^(\d{1,2})h(\d{2})$")
DURATION_RE = re.compile(r"^(\d+)h(\d{2})$")
VERSIONS = {"VOST", "VF", "VO", "VOSTFR"}
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
DATE_LINE_RE = re.compile(
    r"^(?:%s)\s+(\d{1,2})(?:er)?\s+([^\W\d_]+)\s+(?:à\s+)?(\d{1,2})h(\d{2})?" % "|".join(WEEKDAYS), re.I)
HEADER_RE = re.compile(
    r"Horaires du \w+\s+(\d{1,2})(?:er)?\s+([^\W\d_]+)(?:\s+(\d{4}))?\s+au\s+\w+\s+(\d{1,2})(?:er)?\s+([^\W\d_]+)\s+(\d{4})",
    re.I)


# ---------- Petites aides ----------

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'").replace(" ", " ")).strip()


def is_white(color) -> bool:
    if color is None:
        return True
    if isinstance(color, (int, float)):
        return color >= 0.99
    return all(v >= 0.99 for v in color)


def cy(word) -> float:
    return (word["top"] + word["bottom"]) / 2


def group_lines(words, tol: float = 2.5):
    """Regroupe des mots en lignes (même hauteur), triées de haut en bas puis de gauche à droite."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def line_text(line) -> str:
    return clean(" ".join(w["text"] for w in line))


def cluster(values, tol: float = 1.5):
    out: list[float] = []
    for v in sorted(values):
        if out and v - out[-1] <= tol:
            continue
        out.append(v)
    return out


def is_bold(word) -> bool:
    return "bold" in word.get("fontname", "").lower()


# ---------- Films ----------

@dataclass
class Film:
    title_lines: list[str] = field(default_factory=list)
    info_lines: list[str] = field(default_factory=list)
    times: list[tuple[int, int, int]] = field(default_factory=list)  # (colonne, heure, minute)

    @property
    def title(self) -> str:
        return clean(" ".join(self.title_lines))

    def infos(self) -> list[dict]:
        """Un ou plusieurs enregistrements « Réalisateur - 1h57 - France - VOST »."""
        records, buf = [], ""
        for line in self.info_lines:
            buf = (buf + " " + line).strip()
            if any(DURATION_RE.match(t.strip()) for t in re.split(r"\s+-\s+", buf)):
                records.append(parse_info(buf))
                buf = ""
        if buf:
            records.append(parse_info(buf))
        return records


def parse_info(text: str) -> dict:
    tokens = [t.strip() for t in re.split(r"\s+-\s+", clean(text)) if t.strip()]
    info = {"minutes": None, "version": None, "extras": [], "country": None}
    idx = next((i for i, t in enumerate(tokens) if DURATION_RE.match(t)), None)
    if idx is not None:
        h, m = DURATION_RE.match(tokens[idx]).groups()
        info["minutes"] = int(h) * 60 + int(m)
    for t in tokens[(idx + 1) if idx is not None else 0:]:
        if t.upper() in VERSIONS:
            info["version"] = t.upper()
        elif t == "3D" or norm(t).startswith("des "):
            info["extras"].append(t)
        elif info["country"] is None:
            info["country"] = t
        else:
            info["extras"].append(t)
    return info


def build_films(left_lines) -> list[Film]:
    """Lignes de la colonne de gauche -> films (titre en gras, puis lignes d'infos)."""
    films: list[Film] = []
    for line in left_lines:
        first = line[0]
        is_title = is_bold(first) and first["size"] >= 8.8
        text = line_text(line)
        if is_title:
            if not films or films[-1].info_lines:
                films.append(Film())
            films[-1].title_lines.append(text)
        elif films:
            films[-1].info_lines.append(text)
    return films


def film_summary(film: Film):
    infos = film.infos()
    minutes = infos[0]["minutes"] if len(infos) == 1 else None
    versions = {i["version"] for i in infos if i["version"]}
    version = versions.pop() if len(versions) == 1 and all(i["version"] for i in infos) else None
    extras: list[str] = []
    for i in infos:
        for e in i["extras"]:
            if e not in extras:
                extras.append(e)
    return minutes, version, extras


# ---------- Lecture d'une page ----------

@dataclass
class Page:
    week_start: date
    week_end: date
    events: list[dict]
    warnings: list[str]


def parse_header(text: str):
    m = HEADER_RE.search(text)
    if not m:
        raise ValueError("en-tête « Horaires du ... au ... » introuvable : le PDF n'a pas le format attendu")
    d1, mo1, y1, d2, mo2, y2 = m.groups()
    month1, month2 = month_num(mo1), month_num(mo2)
    if not month1 or not month2:
        raise ValueError(f"mois illisible dans l'en-tête : {m.group(0)!r}")
    end_year = int(y2)
    start_year = int(y1) if y1 else (end_year - 1 if month1 > month2 else end_year)
    start, end = date(start_year, month1, int(d1)), date(end_year, month2, int(d2))
    if start.weekday() != 2:  # mercredi
        raise ValueError(f"la semaine devrait commencer un mercredi, pas le {start:%d/%m/%Y}")
    return start, end


def resolve_year(month: int, day: int, week_end: date, week_start: date) -> date:
    d = date(week_end.year, month, day)
    return d.replace(year=d.year + 1) if d < week_start - timedelta(days=180) else d


def parse_page(page) -> Page:
    text = page.extract_text() or ""
    week_start, week_end = parse_header(text)
    words = page.extract_words(extra_attrs=["fontname", "size"])
    warnings: list[str] = []

    rects = [r for r in page.rects if not is_white(r.get("non_stroking_color"))]
    wide = page.width * 0.8
    bands = sorted((r for r in rects if r["height"] > 8 and r["width"] > wide), key=lambda r: r["top"])
    rules = [r for r in rects if r["height"] <= 2.5 and r["width"] > wide]
    seps = cluster(r["x0"] for r in rects if r["width"] <= 2.5 and r["height"] > 15)
    right_edge = max(r["x1"] for r in bands)
    if len(seps) != 7:
        raise ValueError(f"{len(seps)} séparateurs de colonnes trouvés au lieu de 7 : mise en page inattendue")
    col_bounds = list(zip(seps, seps[1:] + [right_edge]))

    def column_of(word) -> int | None:
        x = (word["x0"] + word["x1"]) / 2
        for i, (a, b) in enumerate(col_bounds):
            if a <= x < b:
                return i
        return None

    # Bandes horizontales : entre deux frontières consécutives (filets et bords de bandeaux)
    bounds = cluster([(r["top"] + r["bottom"]) / 2 for r in rules] + [b["top"] for b in bands] + [b["bottom"] for b in bands])
    intervals = [(a, b) for a, b in zip(bounds, bounds[1:]) if b - a > 3]

    def band_at(a, b):
        return any(band["top"] - 2 <= a and b <= band["bottom"] + 2 for band in bands)

    events: list[dict] = []
    zone = "grid"
    band_note: str | None = None
    group_note: str | None = None

    for a, b in intervals:
        ws = [w for w in words if a <= cy(w) < b]
        if not ws:
            continue
        lines = group_lines(ws)

        if band_at(a, b):
            label = clean(" ".join(line_text(l) for l in lines))
            n = norm(label)
            if "mer." in n and "jeu." in n:
                continue
            if n.startswith("evenements"):
                zone, band_note, group_note = "events", None, None
            elif "ouvert tous les jours" in n or "thionville.fr" in n:
                break
            else:
                band_note = label
            continue

        left = [w for w in ws if w["x0"] < seps[0]]
        right = [w for w in ws if w["x0"] >= seps[0]]

        # Ligne-titre centrée en gras (ex. « Festival Alimenterre ») dans la zone des événements
        if ws and all(is_bold(w) for w in ws) and min(w["x0"] for w in ws) > 100:
            group_note = clean(" ".join(line_text(l) for l in lines))
            continue

        films = build_films(group_lines(left))

        if zone == "grid":
            if len(films) != 1:
                warnings.append(f"ligne de grille ignorée (films détectés : {len(films)}) : {[f.title for f in films]}")
                continue
            film = films[0]
            for w in right:
                m = TIME_RE.match(w["text"])
                col = column_of(w)
                if not m or col is None:
                    warnings.append(f"« {film.title} » : texte inattendu dans la grille : {w['text']!r}")
                    continue
                film.times.append((col, int(m.group(1)), int(m.group(2))))
            minutes, version, extras = film_summary(film)
            category = "festival" if band_note and "festival" in norm(band_note) else "cinema"
            note = ", ".join(x for x in [band_note, *extras] if x) or None
            for col, hh, mm in sorted(film.times):
                start = datetime.combine(week_start + timedelta(days=col), dtime(hh, mm))
                events.append(_event(film.title, start, minutes, version, note, category))
        else:
            entries = parse_date_entries(group_lines(right), right_edge)
            if len(entries) != len(films):
                warnings.append(
                    f"événements à venir ignorés : {len(films)} film(s) mais {len(entries)} date(s) "
                    f"({[f.title for f in films]})")
                continue
            heading, group_note = group_note, None  # le titre de groupe ne couvre que cette ligne
            for film, entry in zip(films, entries):
                minutes, version, extras = film_summary(film)
                try:
                    day = resolve_year(entry["month"], entry["day"], week_end, week_start)
                    start = datetime.combine(day, dtime(entry["hour"], entry["minute"]))
                except ValueError:
                    warnings.append(f"date invalide pour « {film.title} »")
                    continue
                category = "festival" if heading and "festival" in norm(heading) else "cinema"
                note = " - ".join(x for x in [heading, entry["note"], *extras] if x) or None
                events.append(_event(film.title, start, minutes, version, note, category))

    return Page(week_start, week_end, events, warnings)


def parse_date_entries(right_lines, right_edge: float) -> list[dict]:
    """Colonne de droite de « Événements à venir » : une date en gras, puis ses notes."""
    entries: list[dict] = []
    prev_line = None
    for line in right_lines:
        text = line_text(line)
        m = DATE_LINE_RE.match(text)
        if m:
            month = month_num(m.group(2))
            if not month:
                continue
            entries.append({"day": int(m.group(1)), "month": month, "hour": int(m.group(3)),
                            "minute": int(m.group(4) or 0), "note_lines": []})
            prev_line = None
        elif entries:
            notes = entries[-1]["note_lines"]
            # Ligne qui continue la précédente (retour à la ligne automatique) : on la colle
            if notes and prev_line is not None and right_edge - prev_line[-1]["x1"] < 25:
                notes[-1] += " " + text
            else:
                notes.append(text)
            prev_line = line
    for e in entries:
        e["note"] = " - ".join(e.pop("note_lines")) or None
    return entries


def _event(title, start, minutes, version, note, category) -> dict:
    e = {"id": make_id(LIEU, start, title), "lieu": LIEU, "ville": VILLE, "categorie": category,
         "titre": title, "debut": paris_iso(start)}
    if minutes:
        e["duree_min"] = minutes
    if version:
        e["version"] = version
    if note:
        e["note"] = note
    e["url"] = URL
    return e


# ---------- Fichier PDF -> événements ----------

def parse_pdf(path: Path) -> Page:
    with pdfplumber.open(path) as pdf:
        pages = [parse_page(p) for p in pdf.pages if "Horaires du" in (p.extract_text() or "")]
    if not pages:
        raise ValueError(f"{path.name} : aucune page « Horaires du ... » trouvée")
    first = pages[0]
    result = Page(first.week_start, pages[-1].week_end, [], [])
    for p in pages:
        result.events += p.events
        result.warnings += p.warnings
    if not result.events:
        raise ValueError(f"{path.name} : aucun événement extrait")
    return result


def import_pdfs(paths: list[Path], dry_run: bool = False) -> int:
    doc = merge.load()
    events = doc["events"]
    status = 0
    for path in paths:
        try:
            page = parse_pdf(path)
        except Exception as exc:  # noqa: BLE001
            print(f"::error::{path.name} : {exc}")
            status = 1
            continue
        for w in page.warnings:
            print(f"::warning::{path.name} : {w}")
        in_week = [e for e in page.events if page.week_start <= parse_iso(e["debut"]).date() <= page.week_end]
        print(f"{path.name} : semaine du {page.week_start:%d/%m/%Y} au {page.week_end:%d/%m/%Y}, "
              f"{len(in_week)} séance(s) + {len(page.events) - len(in_week)} événement(s) à venir")
        if dry_run:
            for e in page.events:
                print(f"  {e['debut'][:16]}  {e['titre']}  [{e.get('version', '')}] {e.get('note', '')}")
            continue
        events = [e for e in events
                  if not (e["lieu"] == LIEU and page.week_start <= parse_iso(e["debut"]).date() <= page.week_end)]
        events += page.events
    if not dry_run:
        merge.save(merge.purge(events))
    return status


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    args = [a for a in argv if not a.startswith("--")]
    paths = [Path(a) for a in args] or sorted((merge.ROOT / "pdf").glob("*.pdf"))
    if not paths:
        print("Aucun PDF à traiter (dossier pdf/ vide).")
        return 0
    return import_pdfs(paths, dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
