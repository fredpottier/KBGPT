"""
value_equivalence.py — Équivalence numérique inter-unités entre deux textes de claims.

Cas déclencheur (05/06/2026, retour Fred sur le chat) : le runtime présentait en
« ⚠ Divergence entre autorités » une paire FAA/EASA qui dit LA MÊME CHOSE dans
des unités différentes — FAA « 1,500 lbs (6.67 kN) » vs EASA « 680 kg (1500 lb) ».
Un faux conflit affiché détruit la confiance (pire que de ne rien afficher).

Principe (domain-agnostic — conversions physiques universelles, aucune règle
corpus) : extraire les quantités (nombre + unité) de chaque texte, les normaliser
par DIMENSION (charge → newtons, longueur → mm, masse volumique etc.), puis :
  - pour chaque dimension présente DES DEUX côtés, comparer les ensembles de
    valeurs avec tolérance relative (défaut 3 % — couvre les arrondis de
    conversion type 680 kg ↔ 1500 lb) ;
  - équivalent ⟺ au moins une dimension partagée ET aucune valeur partagée
    en désaccord (chaque valeur d'un côté a un correspondant proche de l'autre).

Limites assumées : ne traite que les unités tabulées ; « g » (accélération) est
ignoré (ambigu avec grammes) ; deux textes sans dimension commune → non-équivalents
(on n'affirme l'équivalence que si on peut la PROUVER numériquement).
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# (pattern d'unité, dimension, facteur vers l'unité canonique de la dimension)
# Charge/force : canonique = newton. lb/lbf ≈ 4.448 N ; kg(-force) ≈ 9.807 N.
# NB : en contexte réglementaire « 1500 lb » et « 680 kg » désignent la même
# charge limite — on traite lb et kg comme des forces équivalentes (lbf/kgf).
_UNITS: List[Tuple[str, str, float]] = [
    (r"kn", "load", 1000.0),
    (r"kilonewtons?", "load", 1000.0),
    (r"newtons?|n", "load", 1.0),
    (r"lbs?\.?|pounds?|livres?", "load", 4.4482),
    (r"kgs?|kilograms?|kilogrammes?", "load", 9.8067),
    (r"daN", "load", 10.0),
    # Longueur : canonique = mm
    (r"inch(?:es)?|in\.|\"|''", "length", 25.4),
    (r"ft|feet|foot", "length", 304.8),
    (r"mm|millim[eè]tres?|millimeters?", "length", 1.0),
    (r"cm|centim[eè]tres?|centimeters?", "length", 10.0),
    (r"m|m[eè]tres?|meters?", "length", 1000.0),
    # Durée : canonique = ms
    (r"ms|millisecond(?:e?s)?", "time", 1.0),
    (r"s|sec|seconds?|secondes?", "time", 1000.0),
    # Vitesse : canonique = m/s
    (r"ft/s|fps", "speed", 0.3048),
    (r"m/s", "speed", 1.0),
    (r"km/h", "speed", 0.27778),
    (r"kts?|knots?|n[oœ]uds?", "speed", 0.51444),
]

# Nombre : « 1,500 » (séparateur milliers) / « 6.67 » / « 680 » / « 1 500 »
_NUM = r"(\d{1,3}(?:[, ]\d{3})+|\d+(?:[.,]\d+)?)"
_QTY_RES = [
    (re.compile(_NUM + r"\s*(" + pat + r")\b", re.IGNORECASE), dim, factor)
    for pat, dim, factor in _UNITS
]


def _parse_number(raw: str) -> float:
    s = raw.strip()
    # « 1,500 » ou « 1 500 » = milliers ; « 6.67 » / « 6,67 » = décimal
    if re.fullmatch(r"\d{1,3}(?:[, ]\d{3})+", s):
        return float(re.sub(r"[, ]", "", s))
    return float(s.replace(",", "."))


def extract_quantities(text: str) -> Dict[str, List[float]]:
    """Extrait {dimension: [valeurs canoniques]} d'un texte."""
    out: Dict[str, List[float]] = {}
    if not text:
        return out
    consumed: List[Tuple[int, int]] = []
    for rx, dim, factor in _QTY_RES:
        for m in rx.finditer(text):
            span = (m.start(), m.end())
            # éviter qu'une unité courte (« n », « m », « s ») re-matche dans une
            # plage déjà capturée par une unité plus spécifique (kN, mm, ms…)
            if any(s < span[1] and span[0] < e for s, e in consumed):
                continue
            consumed.append(span)
            try:
                val = _parse_number(m.group(1)) * factor
            except ValueError:
                continue
            out.setdefault(dim, []).append(val)
    return out


def _value_sets_compatible(a: List[float], b: List[float], tol: float) -> bool:
    """Chaque valeur de a a un correspondant proche dans b, et réciproquement."""
    def _matched(xs: List[float], ys: List[float]) -> bool:
        return all(
            any(abs(x - y) <= tol * max(abs(x), abs(y), 1e-9) for y in ys)
            for x in xs
        )
    return _matched(a, b) and _matched(b, a)


def quantities_equivalent(text_a: str, text_b: str, tol: float = 0.03) -> bool:
    """Vrai si les deux textes énoncent les MÊMES valeurs (modulo conversion
    d'unités et arrondis ≤ tol) sur au moins une dimension partagée, sans
    désaccord sur aucune dimension partagée.

    Conçu pour requalifier une « divergence inter-autorités » en CONCORDANCE
    quand les deux côtés disent la même chose dans des unités différentes.
    """
    qa, qb = extract_quantities(text_a), extract_quantities(text_b)
    shared = set(qa) & set(qb)
    if not shared:
        return False
    return all(_value_sets_compatible(qa[d], qb[d], tol) for d in shared)
