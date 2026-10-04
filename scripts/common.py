"""Utilitaires partagés par les scripts (fuseau, slug, catégories)."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")
CATEGORIES = {"cinema", "concert", "spectacle", "expo", "festival"}


def norm(text: str) -> str:
    """Minuscules, sans accents, espaces normalisés (pour comparer des libellés)."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(text)).strip("-")


def paris_iso(naive: datetime) -> str:
    """Date naïve (heure de Paris) -> ISO 8601 avec le bon décalage (+02:00 / +01:00)."""
    return naive.replace(tzinfo=TZ).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def now_paris() -> datetime:
    return datetime.now(TZ)


def make_id(lieu: str, start: datetime, titre: str) -> str:
    return f"{slug(lieu)}-{start:%Y-%m-%d-%H%M}-{slug(titre)}"


MONTHS = [
    ("janv", 1), ("fevr", 2), ("mars", 3), ("avr", 4), ("mai", 5), ("juin", 6),
    ("juil", 7), ("aout", 8), ("sept", 9), ("oct", 10), ("nov", 11), ("dec", 12),
]


def month_num(word: str) -> int | None:
    """« oct. », « octobre », « Août »... -> numéro du mois (ou None)."""
    w = norm(word).rstrip(".")
    for prefix, number in MONTHS:
        if w.startswith(prefix):
            return number
    return None
