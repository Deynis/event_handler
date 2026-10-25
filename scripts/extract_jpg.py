"""Lecture de la grille hebdomadaire de La Scala publiée en image (JPG).

Utilisé par extract_pdf.py pour les fichiers jpg/*.jpg ; même résultat qu'un PDF.

Principe : l'image reprend la mise en page du PDF, mais sans texte exploitable. On
retrouve la géométrie à partir des pixels rouges, puis on lit chaque case avec
Tesseract (OCR, langue fra) :
  - lignes presque entièrement rouges = filets (fins) ou bandeaux (épais) ;
  - entre deux frontières, les traits verticaux rouges donnent le type de ligne :
    7 séparateurs = ligne de la grille, 1 = événement à venir, 0 = titre de groupe ;
  - texte noir lu sur le canal rouge (les filets disparaissent), texte blanc des
    bandeaux lu sur le canal vert inversé ;
  - titre de film ou ligne d'infos : le titre est en gras, reconnu à l'épaisseur
    des traits.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image

import extract_pdf as ep
from common import norm

SCALE = 3             # agrandissement avant OCR (image en 96 dpi) ; 2 suffit pour les horaires
BOLD_STROKE = 4.0     # épaisseur moyenne des traits (px) au-delà de laquelle le texte est gras
PX_PER_PT = 1166 / 420  # pour réutiliser les seuils du PDF (exprimés en points)
TIME_OCR = "-c tessedit_char_whitelist=0123456789h"
ROMAN_END_RE = re.compile(r"(?<=\s)[Il|1]{1,3}$")  # « Puppet Master IIl » -> III (I gras mal lu)


def red_mask(a: np.ndarray) -> np.ndarray:
    r, g, b = (a[..., i].astype(int) for i in range(3))
    return (r > 180) & (r - g > 60) & (r - b > 60)


def runs(flags, gap: int = 0) -> list[tuple[int, int]]:
    """Plages [début, fin[ d'indices à True consécutifs (trous de `gap` au plus ignorés)."""
    out: list[list[int]] = []
    for i in np.flatnonzero(flags):
        if out and i - out[-1][1] <= gap:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1])
    return [tuple(r) for r in out]


def stroke_width(dark: np.ndarray) -> float:
    """Épaisseur moyenne des traits : longueur moyenne des segments horizontaux d'encre."""
    n = (dark[:, 1:] & ~dark[:, :-1]).sum() + dark[:, 0].sum()
    return dark.sum() / n if n else 0.0


class Scan:
    def __init__(self, path: Path):
        a = np.asarray(Image.open(path).convert("RGB"))
        self.red = red_mask(a)
        self.ink = a[..., 0].copy()                 # noir sur blanc, le rouge devient blanc
        self.band_ink = 255 - a[..., 1]             # blanc sur rouge -> sombre sur clair

    def lines(self, y0, y1, x0, x1, config="", band=False, scale=SCALE) -> list[list[dict]]:
        """OCR d'une case -> lignes de mots (coordonnées en pixels de l'image)."""
        crop = (self.band_ink if band else self.ink)[y0:y1, x0:x1]
        if crop.size == 0 or crop.min() > 128:
            return []
        img = Image.fromarray(crop)
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
        data = pytesseract.image_to_data(img, lang="fra", config=f"--psm 6 {config}",
                                         output_type=pytesseract.Output.DICT)
        lines: dict[tuple, list[dict]] = {}
        for i, text in enumerate(data["text"]):
            if not text.strip():
                continue
            left, top = x0 + data["left"][i] / scale, y0 + data["top"][i] / scale
            word = {"text": text, "x0": left, "x1": left + data["width"][i] / scale,
                    "top": top, "bottom": top + data["height"][i] / scale}
            lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(word)
        return sorted(lines.values(), key=lambda l: l[0]["top"])

    def is_bold(self, line) -> bool:
        y0, y1 = int(min(w["top"] for w in line)), int(max(w["bottom"] for w in line)) + 1
        x0, x1 = int(line[0]["x0"]), int(line[-1]["x1"]) + 1
        return stroke_width(self.ink[y0:y1, x0:x1] < 128) >= BOLD_STROKE


def text_of(lines) -> str:
    return ep.clean(" ".join(ep.line_text(l) for l in lines))


def build_films(img: Image_, lines) -> list[ep.Film]:
    """Comme ep.build_films, le gras étant mesuré sur l'image."""
    films: list[ep.Film] = []
    for line in lines:
        text = ep.line_text(line)
        if img.is_bold(line):
            if not films or films[-1].info_lines:
                films.append(ep.Film())
            films[-1].title_lines.append(ROMAN_END_RE.sub(lambda m: "I" * len(m.group()), text))
        elif films:
            films[-1].info_lines.append(text)
    return films


def separators(img: Scan, interval, left_edge: int, right_edge: int) -> list[int]:
    """Abscisses des traits verticaux rouges qui traversent toute la ligne."""
    a, b = interval
    vertical = img.red[a + 3:b - 2, left_edge:right_edge].mean(0) > 0.9
    return [left_edge + (s + e) // 2 for s, e in runs(vertical, gap=1)]


def grid_times(img: Scan, grid, seps, right_edge: int) -> dict[tuple, list[tuple[int, dict]]]:
    """Horaires de la grille : une seule lecture par colonne de jour (bien plus rapide
    que case par case), chaque mot étant ensuite rangé dans sa ligne -> (colonne, mot)."""
    out: dict[tuple, list[tuple[int, dict]]] = {}
    if not grid:
        return out
    cols = seps[grid[0]]
    top, bottom = grid[0][0], grid[-1][1]
    for col, (c0, c1) in enumerate(zip(cols, cols[1:] + [right_edge])):
        for line in img.lines(top, bottom, c0 + 3, c1 - 2, config=TIME_OCR, scale=2):
            for w in line:
                y = (w["top"] + w["bottom"]) / 2
                row = next((iv for iv in grid if iv[0] <= y < iv[1]), None)
                if row:
                    out.setdefault(row, []).append((col, w))
    return out


def parse_image(path: Path) -> ep.Page:
    img = Scan(path)
    width = img.red.shape[1]
    wide = runs(img.red.mean(1) > 0.6, gap=2)
    if not wide:
        raise ValueError("aucun bandeau rouge trouvé : l'image n'a pas le format attendu")
    xs = np.flatnonzero(img.red[(wide[0][0] + wide[0][1]) // 2])
    left_edge, right_edge = int(xs.min()), int(xs.max()) + 1

    # Frontières horizontales : filets (≤ 6 px) et bandeaux, mesurés sur la largeur du tableau
    full = img.red[:, left_edge:right_edge].mean(1) > 0.6
    bands, bounds = [], []
    for a, b in runs(full, gap=2):
        if b - a > 6:
            bands.append((a, b))
            bounds += [a, b]
        else:
            bounds.append((a + b) // 2)
    bounds = sorted(set(bounds))

    intervals = [(a, b) for a, b in zip(bounds, bounds[1:]) if b - a > 6]
    seps = {iv: separators(img, iv, left_edge, right_edge) for iv in intervals if iv not in bands}
    times = grid_times(img, [iv for iv, s in seps.items() if len(s) == 7], seps, right_edge)

    warnings: list[str] = []
    week_start, week_end = ep.parse_header(text_of(img.lines(0, bands[0][0], 0, width)))

    events: list[dict] = []
    zone = "grid"
    band_note: str | None = None
    group_note: str | None = None

    for a, b in intervals:
        if (a, b) in bands:
            label = text_of(img.lines(a, b, left_edge, right_edge, band=True))
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

        y0, y1 = a + 3, b - 2  # sans les bords anti-aliasés des filets
        row_seps = seps[(a, b)]
        if not row_seps:  # titre de groupe centré (ex. « Festival Alimenterre »)
            label = text_of(img.lines(y0, y1, left_edge, right_edge))
            if label:
                group_note = label
            continue

        films = build_films(img, img.lines(y0, y1, left_edge, row_seps[0] - 2))

        if zone == "grid":
            if len(row_seps) != 7:
                raise ValueError(f"{len(row_seps)} séparateurs de colonnes trouvés au lieu de 7 : mise en page inattendue")
            if len(films) != 1:
                warnings.append(f"ligne de grille ignorée (films détectés : {len(films)}) : {[f.title for f in films]}")
                continue
            film = films[0]
            for col, w in times.get((a, b), []):
                m = ep.TIME_RE.match(w["text"])
                if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
                    warnings.append(f"« {film.title} » : texte inattendu dans la grille : {w['text']!r}")
                    continue
                film.times.append((col, int(m.group(1)), int(m.group(2))))
            events += ep.grid_events(film, week_start, band_note)
        else:
            right = img.lines(y0, y1, row_seps[0] + 3, right_edge)
            entries = ep.parse_date_entries(right, right_edge, wrap_gap=25 * PX_PER_PT)
            heading, group_note = group_note, None  # le titre de groupe ne couvre que cette ligne
            events += ep.upcoming_events(films, entries, heading, week_start, week_end, warnings)

    if not events:
        raise ValueError(f"{path.name} : aucun événement extrait")
    return ep.Page(week_start, week_end, events, warnings)
