"""
CH-40.2 — Métriques structurées par type pour OSMOSIS V4 Sprint S0.

GARDE-FOU CRITIQUE contre l'overfit Claude-juge / Claude-reviewer.
Ces métriques sont déterministes (pas LLM) et calculées sur 100% des samples
quand le gold-set v4 fournit les annotations criterion-level.

4 fonctions :
- item_level_recall(answer, expected_items)         — pour list questions
- exact_match_identifiers(answer, expected_ids)      — pour identifiants critiques
- citation_presence_rate(answer, expected_doc_ids)   — pour provenance
- coverage_state_accuracy(predicted, expected)       — pour V4 coverage_state

Toutes les fonctions sont regex-free sur le contenu (uniquement substring match
case-insensitive + whitespace normalization). Domain-agnostic.
"""
from __future__ import annotations

import re
from typing import Any


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace. Pas de regex sur contenu sémantique."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _split_sentences(text: str) -> list[str]:
    """Split en phrases sur ponctuation fin-de-phrase. Filtre phrases trop courtes."""
    # Simple sentence split — pas de NLP, pas de domaine-spécifique
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if len(p.strip()) >= 10]


# ──────────────────────────────────────────────────────────────────────────
# 1. item_level_recall — pour list questions
# ──────────────────────────────────────────────────────────────────────────

def item_level_recall(answer: str, expected_items: list[str]) -> dict[str, Any]:
    """Mesure recall + precision sur l'énumération d'items attendus.

    Pour chaque item attendu, on vérifie si l'item (ou ses tokens significatifs
    > 3 chars) est mentionné dans la réponse. Pas de regex métier.

    Args:
        answer: réponse synthétisée
        expected_items: liste d'items attendus (ex. ["Reg 952/2013", "Reg 2016/679", ...])

    Returns:
        {recall, precision, f1, n_matched, n_expected, missing_items}
    """
    if not expected_items:
        return {
            "recall": None,
            "precision": None,
            "f1": None,
            "n_matched": 0,
            "n_expected": 0,
            "missing_items": [],
            "applicable": False,
        }
    answer_norm = _normalize(answer)
    matched = []
    missing = []
    for item in expected_items:
        item_norm = _normalize(item)
        # Match : item complet OU au moins 1 token significatif (> 3 chars)
        if item_norm in answer_norm:
            matched.append(item)
            continue
        # Token-level fallback : tokens > 3 chars
        tokens = [t for t in item_norm.split() if len(t) > 3]
        if tokens and all(t in answer_norm for t in tokens):
            matched.append(item)
        else:
            missing.append(item)
    n_matched = len(matched)
    n_expected = len(expected_items)
    recall = n_matched / n_expected if n_expected else 0.0
    # Precision : on ne peut pas vraiment la calculer sans ground truth des "items présents".
    # Approximation : ratio matched / max(matched, items "détectés" dans answer).
    # Pour simplifier, on retourne precision = recall (les questions list cherchent surtout recall).
    precision = recall
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "recall": round(recall, 3),
        "precision": round(precision, 3),
        "f1": round(f1, 3),
        "n_matched": n_matched,
        "n_expected": n_expected,
        "missing_items": missing[:5],  # top-5 pour debug
        "applicable": True,
    }


# ──────────────────────────────────────────────────────────────────────────
# 2. exact_match_identifiers — pour identifiants critiques
# ──────────────────────────────────────────────────────────────────────────

def exact_match_identifiers(answer: str, expected_ids: list[str]) -> dict[str, Any]:
    """Vérifie que les identifiants critiques apparaissent verbatim dans la réponse.

    Identifiants = numéros de règlement, dates, codes, valeurs numériques avec unité.
    Match case-insensitive + whitespace-collapsed (mais pas regex sémantique).

    Args:
        answer: réponse synthétisée
        expected_ids: liste d'identifiants critiques (ex. ["2021/821", "21 J", "20 May 2021"])

    Returns:
        {score, n_matched, n_expected, missing_ids, applicable}
    """
    if not expected_ids:
        return {
            "score": None,
            "n_matched": 0,
            "n_expected": 0,
            "missing_ids": [],
            "applicable": False,
        }
    answer_norm = _normalize(answer)
    matched = []
    missing = []
    for ident in expected_ids:
        # Match exact substring après normalisation
        ident_norm = _normalize(ident)
        if ident_norm in answer_norm:
            matched.append(ident)
        else:
            missing.append(ident)
    n_matched = len(matched)
    n_expected = len(expected_ids)
    score = n_matched / n_expected
    return {
        "score": round(score, 3),
        "n_matched": n_matched,
        "n_expected": n_expected,
        "missing_ids": missing,
        "applicable": True,
    }


# ──────────────────────────────────────────────────────────────────────────
# 3. citation_presence_rate — pour provenance
# ──────────────────────────────────────────────────────────────────────────

# Patterns de citation supportés (regex sur structure, pas sur contenu sémantique) :
# - [doc=foo_bar_123]                — runtime V3 format
# - [Source 1] / [source 2]          — historique
# - [foo_bar_123]                    — bracket simple avec doc_id
# - [[SOURCE:Doc|p.X]]                — frontend SourcePill
_CITATION_PATTERN = re.compile(r"\[(?:doc=|Source\s*\d+|source\s*\d+|\[?SOURCE:[^\]]+|[a-z0-9_]{8,})", re.IGNORECASE)


def citation_presence_rate(answer: str, expected_doc_ids: list[str]) -> dict[str, Any]:
    """Mesure le ratio de phrases citées + validité des doc_ids cités.

    Args:
        answer: réponse synthétisée
        expected_doc_ids: doc_ids attendus du gold-set

    Returns:
        {
          sentences_with_citation,
          sentences_total,
          citation_rate,
          valid_doc_rate (cited doc_ids ∈ expected),
          unsupported_sentences (phrases sans citation),
          applicable
        }
    """
    sentences = _split_sentences(answer)
    if not sentences:
        return {
            "sentences_with_citation": 0,
            "sentences_total": 0,
            "citation_rate": None,
            "valid_doc_rate": None,
            "unsupported_sentences": 0,
            "applicable": False,
        }

    n_with_citation = 0
    cited_doc_ids: set[str] = set()
    for s in sentences:
        if _CITATION_PATTERN.search(s):
            n_with_citation += 1
            # Extract doc_ids from the sentence (best effort)
            for m in re.finditer(r"\[(?:doc=)?([a-z0-9_]{8,})\]", s, re.IGNORECASE):
                cited_doc_ids.add(m.group(1))

    citation_rate = n_with_citation / len(sentences)

    # Validity : combien des doc_ids cités sont dans la liste attendue ?
    if expected_doc_ids and cited_doc_ids:
        valid = sum(1 for c in cited_doc_ids if any(e in c or c in e for e in expected_doc_ids))
        valid_doc_rate = valid / len(cited_doc_ids)
    elif not expected_doc_ids:
        valid_doc_rate = None
    else:
        valid_doc_rate = 0.0

    return {
        "sentences_with_citation": n_with_citation,
        "sentences_total": len(sentences),
        "citation_rate": round(citation_rate, 3),
        "valid_doc_rate": round(valid_doc_rate, 3) if valid_doc_rate is not None else None,
        "unsupported_sentences": len(sentences) - n_with_citation,
        "applicable": True,
    }


# ──────────────────────────────────────────────────────────────────────────
# 4. coverage_state_accuracy — pour V4 coverage_state
# ──────────────────────────────────────────────────────────────────────────

def coverage_state_accuracy(predicted: str | None, expected: str | None) -> dict[str, Any]:
    """Vérifie que le système prédit correctement complete/partial/unknown.

    V4 will émettre `coverage_state` dans la réponse JSON. Pour l'instant V3 ne
    l'émet pas → predicted=None → applicable=False.

    Args:
        predicted: 'complete' | 'partial' | 'unknown' | None
        expected: 'complete' | 'partial' | 'unknown' | None

    Returns:
        {match, predicted, expected, applicable}
    """
    if predicted is None or expected is None:
        return {
            "match": None,
            "predicted": predicted,
            "expected": expected,
            "applicable": False,
        }
    return {
        "match": predicted == expected,
        "predicted": predicted,
        "expected": expected,
        "applicable": True,
    }


# ──────────────────────────────────────────────────────────────────────────
# Convenience : compute all metrics for a sample
# ──────────────────────────────────────────────────────────────────────────

def compute_all(
    answer: str,
    gold_truth: dict | None,
    primary_type: str | None = None,
    predicted_coverage_state: str | None = None,
) -> dict[str, Any]:
    """Calcule les 4 métriques structurées sur un échantillon.

    Args:
        answer: réponse synthétisée par OSMOSIS
        gold_truth: l'objet `ground_truth` du gold-set v4 (peut être None si pas dans gold-set)
        primary_type: type de question (factual|list|temporal|...)
        predicted_coverage_state: état coverage prédit par V4 (None pour V3)

    Returns:
        {
          item_recall: {...},
          exact_match: {...},
          citation: {...},
          coverage: {...},
          structured_avg: float,  # moyenne des scores applicables (pour disagreement detection)
        }
    """
    if not gold_truth:
        return {
            "item_recall": None,
            "exact_match": None,
            "citation": None,
            "coverage": None,
            "structured_avg": None,
            "applicable": False,
        }

    expected_items = gold_truth.get("list_items_expected") or []
    expected_ids = gold_truth.get("exact_identifiers") or []
    expected_doc_ids = gold_truth.get("supporting_doc_ids") or []
    # Le gold-set v4 ne stocke pas de "expected coverage_state" pour l'instant.
    # Il sera dérivé de la sémantique : list answerable = "complete", abstain = "unknown", etc.
    # Pour CH-40.2, on laisse à None côté expected — c'est V4 qui devra émettre predicted.
    expected_coverage = None

    item_recall = item_level_recall(answer, expected_items)
    exact_match = exact_match_identifiers(answer, expected_ids)
    citation = citation_presence_rate(answer, expected_doc_ids)
    coverage = coverage_state_accuracy(predicted_coverage_state, expected_coverage)

    # structured_avg : moyenne des scores applicables (pour disagreement vs LLM-judge)
    components = []
    if item_recall.get("applicable"):
        components.append(item_recall["recall"])
    if exact_match.get("applicable"):
        components.append(exact_match["score"])
    if citation.get("applicable") and citation.get("citation_rate") is not None:
        components.append(citation["citation_rate"])
    structured_avg = sum(components) / len(components) if components else None

    return {
        "item_recall": item_recall,
        "exact_match": exact_match,
        "citation": citation,
        "coverage": coverage,
        "structured_avg": round(structured_avg, 3) if structured_avg is not None else None,
        "applicable": bool(components),
    }


# ──────────────────────────────────────────────────────────────────────────
# Aggregation helpers
# ──────────────────────────────────────────────────────────────────────────

def aggregate_by_type(per_sample_metrics: list[dict]) -> dict[str, Any]:
    """Aggrège les métriques structurées par primary_type.

    Args:
        per_sample_metrics: liste de {primary_type, structured: compute_all output}

    Returns:
        {
          per_type: {factual: {...}, list: {...}, ...},
          global: {item_recall_avg, exact_match_avg, citation_avg, structured_avg}
        }
    """
    by_type: dict[str, dict[str, list[float]]] = {}
    global_acc: dict[str, list[float]] = {"item_recall": [], "exact_match": [], "citation": [], "structured_avg": []}

    for sm in per_sample_metrics:
        pt = sm.get("primary_type", "unknown")
        st = sm.get("structured", {})
        if not st or not st.get("applicable"):
            continue
        type_acc = by_type.setdefault(pt, {"item_recall": [], "exact_match": [], "citation": [], "structured_avg": []})

        if st.get("item_recall", {}).get("applicable"):
            v = st["item_recall"]["recall"]
            type_acc["item_recall"].append(v)
            global_acc["item_recall"].append(v)
        if st.get("exact_match", {}).get("applicable"):
            v = st["exact_match"]["score"]
            type_acc["exact_match"].append(v)
            global_acc["exact_match"].append(v)
        if st.get("citation", {}).get("applicable") and st["citation"].get("citation_rate") is not None:
            v = st["citation"]["citation_rate"]
            type_acc["citation"].append(v)
            global_acc["citation"].append(v)
        if st.get("structured_avg") is not None:
            v = st["structured_avg"]
            type_acc["structured_avg"].append(v)
            global_acc["structured_avg"].append(v)

    def _avg(arr: list[float]) -> float | None:
        return round(sum(arr) / len(arr), 3) if arr else None

    per_type_summary = {}
    for pt, accs in by_type.items():
        per_type_summary[pt] = {
            "n": max(len(accs["structured_avg"]), 1),
            "item_recall_avg": _avg(accs["item_recall"]),
            "exact_match_avg": _avg(accs["exact_match"]),
            "citation_avg": _avg(accs["citation"]),
            "structured_avg": _avg(accs["structured_avg"]),
        }

    return {
        "per_type": per_type_summary,
        "global": {
            "item_recall_avg": _avg(global_acc["item_recall"]),
            "exact_match_avg": _avg(global_acc["exact_match"]),
            "citation_avg": _avg(global_acc["citation"]),
            "structured_avg": _avg(global_acc["structured_avg"]),
            "n_samples_with_metrics": len(global_acc["structured_avg"]),
        },
    }
