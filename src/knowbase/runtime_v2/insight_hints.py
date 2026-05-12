"""
Insight Hints V2 — Cards proactives sous la réponse chat (CH-06).

Trois types de cards :
- **attention** (⚠️ Point d'attention) : vraie contradiction non résolue par le lifecycle
  (= ConflictReport avec `is_resolved_by_lifecycle=False`).
- **evolution** (📅 Évolution détectée) : conflict résolu par lifecycle, ou présence de
  LIFECYCLE_RELATION sortante (SUPERSEDES/EVOLVES_FROM/REAFFIRMS) sur les docs cités,
  ou anchor RANGE avec evolution_points.
- **cross_doc** (🔗 Contexte cross-doc) : ≥2 authoritative_doc_ids — la réponse
  croise plusieurs sources, intéressant à signaler.

Le module n'altère pas le pipeline V2 — il enrichit la réponse en post-processing.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from neo4j import Driver

from knowbase.runtime_v2.models import PipelineResponse

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────

def _short_doc(doc_id: str) -> str:
    """Raccourci d'affichage pour un doc_id (retire le hash final s'il y en a un)."""
    if not doc_id:
        return "?"
    parts = doc_id.split("_")
    # Retire un hash hex final (8+ chars hex)
    if parts and len(parts[-1]) >= 6 and all(c in "0123456789abcdef" for c in parts[-1]):
        parts = parts[:-1]
    label = "_".join(parts) if parts else doc_id
    return label[:60]


def _truncate(text: Optional[str], n: int = 160) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# ── Lifecycle lookup pour les docs cités ───────────────────────────────

def _fetch_lifecycle_for_docs(
    driver: Driver,
    tenant_id: str,
    doc_ids: list[str],
) -> list[dict[str, Any]]:
    """Pour chaque doc cité, retourne ses LIFECYCLE_RELATION sortantes
    (ex: SUPERSEDES → ce doc remplace un autre, EVOLVES_FROM → modifie un autre).

    Limite à 5 relations max pour éviter les cards trop bruyantes.
    """
    if not doc_ids:
        return []
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (src:DocumentContext)-[r:LIFECYCLE_RELATION]->(tgt:DocumentContext)
                WHERE src.doc_id IN $doc_ids
                  AND src.tenant_id = $tid
                  AND tgt.tenant_id = $tid
                RETURN src.doc_id AS src_id,
                       tgt.doc_id AS tgt_id,
                       coalesce(tgt.primary_subject, '') AS tgt_subject,
                       r.type AS rel_type,
                       coalesce(r.confidence, 0.0) AS confidence,
                       coalesce(r.evidence_quote, '') AS evidence_quote
                ORDER BY r.confidence DESC
                LIMIT 5
                """,
                doc_ids=list(doc_ids),
                tid=tenant_id,
            ).data()
        return rows
    except Exception as exc:
        logger.warning("[INSIGHT_HINTS] LIFECYCLE lookup failed: %s", exc)
        return []


# ── Builders ────────────────────────────────────────────────────────────

def _build_attention_cards(response: PipelineResponse) -> list[dict[str, Any]]:
    """⚠️ Point d'attention — vrais conflicts non résolus par le lifecycle."""
    cards: list[dict[str, Any]] = []
    for c in response.conflicts or []:
        if c.is_resolved_by_lifecycle:
            continue  # ce sera une evolution card

        # Récupérer les textes depuis les claims (si présents dans la réponse)
        text_a = _truncate(_claim_text(response, c.claim_a_id), 140)
        text_b = _truncate(_claim_text(response, c.claim_b_id), 140)
        msg_parts = []
        if text_a and text_b:
            msg_parts.append(f"« {text_a} » vs « {text_b} »")
        msg_parts.append(
            f"Sources : {_short_doc(c.doc_a_id)} / {_short_doc(c.doc_b_id)}"
        )
        message = " — ".join(msg_parts)

        cards.append({
            "type": "attention",
            "icon": "alert",
            "title": "Point d'attention",
            "message": message,
            "priority": 1,
            "metadata": {
                "claim_a_id": c.claim_a_id,
                "claim_b_id": c.claim_b_id,
                "doc_a_id": c.doc_a_id,
                "doc_b_id": c.doc_b_id,
                "confidence": c.confidence,
                "reasoning": c.reasoning,
            },
        })
    return cards


def _build_evolution_cards(
    response: PipelineResponse,
    lifecycle_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """📅 Évolution détectée — lifecycle resolution + LIFECYCLE_RELATION sortantes + evolution_points."""
    cards: list[dict[str, Any]] = []

    # Conflicts résolus par lifecycle
    for c in response.conflicts or []:
        if not c.is_resolved_by_lifecycle:
            continue
        kind = c.lifecycle_resolution_type or "lifecycle"
        text_a = _truncate(_claim_text(response, c.claim_a_id), 120)
        text_b = _truncate(_claim_text(response, c.claim_b_id), 120)

        action_label = None
        if kind == "SUPERSEDES":
            base = f"Le contenu cité a été remplacé : {_short_doc(c.doc_a_id)} → {_short_doc(c.doc_b_id)}"
            action_label = "Voir l'évolution"
        elif kind in ("EVOLVES_FROM", "REAFFIRMS"):
            verb = "fait évoluer" if kind == "EVOLVES_FROM" else "réaffirme"
            base = f"Ce point {verb} : {_short_doc(c.doc_a_id)} → {_short_doc(c.doc_b_id)}"
        else:
            base = f"Évolution réglementaire : {_short_doc(c.doc_a_id)} ↔ {_short_doc(c.doc_b_id)}"

        if text_a and text_b:
            base += f" — « {text_a} » → « {text_b} »"

        cards.append({
            "type": "evolution",
            "icon": "calendar",
            "title": "Évolution détectée",
            "message": base,
            "priority": 2,
            "action_label": action_label,
            "metadata": {
                "lifecycle_kind": kind,
                "doc_a_id": c.doc_a_id,
                "doc_b_id": c.doc_b_id,
            },
        })

    # LIFECYCLE_RELATION sortantes des docs cités (cas: doc Y abroge X, surfaçable même sans conflict)
    seen_pairs: set[tuple[str, str]] = set()
    for row in lifecycle_rows or []:
        pair = (row.get("src_id") or "", row.get("tgt_id") or "")
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        kind = row.get("rel_type") or "lifecycle"
        if kind == "SUPERSEDES":
            msg = f"{_short_doc(row['src_id'])} abroge {_short_doc(row['tgt_id'])}"
        elif kind == "EVOLVES_FROM":
            msg = f"{_short_doc(row['src_id'])} fait évoluer {_short_doc(row['tgt_id'])}"
        elif kind == "REAFFIRMS":
            msg = f"{_short_doc(row['src_id'])} réaffirme {_short_doc(row['tgt_id'])}"
        else:
            msg = f"{_short_doc(row['src_id'])} → {_short_doc(row['tgt_id'])} ({kind})"

        ev = (row.get("evidence_quote") or "").strip()
        if ev:
            msg += f" — « {_truncate(ev, 110)} »"

        cards.append({
            "type": "evolution",
            "icon": "calendar",
            "title": "Lien de version",
            "message": msg,
            "priority": 3,
            "metadata": {
                "lifecycle_kind": kind,
                "src_doc_id": row["src_id"],
                "tgt_doc_id": row["tgt_id"],
                "confidence": row.get("confidence", 0.0),
            },
        })

    # Anchor RANGE → evolution_points (timeline implicite)
    if response.evolution_points:
        n = len(response.evolution_points)
        years = sorted({
            (ep.publication_date or "")[:4]
            for ep in response.evolution_points
            if ep.publication_date
        })
        years = [y for y in years if y]
        if n >= 2:
            yspan = f" ({years[0]} → {years[-1]})" if years else ""
            cards.append({
                "type": "evolution",
                "icon": "calendar",
                "title": "Timeline détectée",
                "message": f"La réponse couvre {n} versions successives{yspan}",
                "priority": 2,
                "metadata": {"n_evolution_points": n, "years": years},
            })

    return cards


def _build_answer_gap_card(response: PipelineResponse) -> Optional[dict[str, Any]]:
    """🔍 Couverture incertaine — gap question/contexte élevé (CH-13)."""
    cls = response.answer_gap_classification
    if cls not in ("UNCERTAIN", "UNANSWERABLE"):
        return None
    gap = response.answer_gap_score or 0.0
    missing = response.answer_gap_missing_terms or []
    missing_preview = ", ".join(missing[:5])
    if len(missing) > 5:
        missing_preview += f" (+{len(missing) - 5})"
    is_unanswerable = cls == "UNANSWERABLE"
    if is_unanswerable:
        title = "Information potentiellement absente"
        prose = (
            "La question contient des termes spécifiques qui n'apparaissent pas dans les "
            "sources retrouvées — la réponse risque d'être imprécise ou hallucinée."
        )
    else:
        title = "Couverture incertaine"
        prose = (
            "Certains termes spécifiques de la question ne sont pas dans les sources "
            "retrouvées. Vérifier que la réponse correspond bien à la question."
        )
    if missing_preview:
        prose += f" Termes non couverts : {missing_preview}."
    return {
        "type": "attention",
        "icon": "alert",
        "title": title,
        "message": prose,
        "priority": 1,
        "metadata": {
            "gap_score": gap,
            "classification": cls,
            "n_missing": len(missing),
            "signal": "answer_gap_tfidf",
        },
    }


def _build_low_confidence_card(response: PipelineResponse) -> Optional[dict[str, Any]]:
    """🔍 Confiance faible — entropy élevée (CH-14, signal hallucination potentielle)."""
    if not response.synthesis_low_confidence:
        return None
    entropy = response.synthesis_entropy
    return {
        "type": "attention",
        "icon": "alert",
        "title": "Confiance faible",
        "message": (
            f"Le modèle a hésité sur cette réponse (entropie {entropy:.2f}). "
            "Les sources ne couvrent peut-être pas pleinement la question — "
            "vérifie l'extrait original avant de t'appuyer dessus."
        ),
        "priority": 1,
        "metadata": {
            "synthesis_entropy": entropy,
            "signal": "halt_epr_logprob",
        },
    }


def _build_cross_doc_card(response: PipelineResponse) -> Optional[dict[str, Any]]:
    """🔗 Contexte cross-doc — la réponse croise ≥2 docs."""
    docs = response.authoritative_doc_ids or []
    if len(docs) < 2:
        return None
    short = [_short_doc(d) for d in docs[:4]]
    suffix = "" if len(docs) <= 4 else f" (+{len(docs) - 4})"
    return {
        "type": "cross_doc",
        "icon": "link",
        "title": "Contexte cross-document",
        "message": f"La réponse synthétise {len(docs)} sources : {', '.join(short)}{suffix}",
        "priority": 3,
        "metadata": {"doc_ids": list(docs)},
    }


def _claim_text(response: PipelineResponse, claim_id: str) -> str:
    for c in response.claims or []:
        if c.claim_id == claim_id:
            return c.text or ""
    return ""


# ── Public API ──────────────────────────────────────────────────────────

def build_insight_hints(
    response: PipelineResponse,
    driver: Driver,
    tenant_id: str = "default",
) -> list[dict[str, Any]]:
    """Construit les insight cards à partir de la PipelineResponse.

    Idempotent et défensif : toute exception interne ne propage pas (juste log).
    Retourne toujours une liste (vide si rien à dire).
    """
    cards: list[dict[str, Any]] = []
    try:
        # CH-13 — answer_gap (en tête si UNANSWERABLE/UNCERTAIN)
        ag = _build_answer_gap_card(response)
        if ag:
            cards.append(ag)
        # CH-14 — low_confidence en premier si applicable
        lc = _build_low_confidence_card(response)
        if lc:
            cards.append(lc)
        cards.extend(_build_attention_cards(response))
        lifecycle_rows = _fetch_lifecycle_for_docs(driver, tenant_id, response.authoritative_doc_ids or [])
        cards.extend(_build_evolution_cards(response, lifecycle_rows))
        cd = _build_cross_doc_card(response)
        if cd:
            cards.append(cd)
        # Tri par priorité (1 = top)
        cards.sort(key=lambda c: c.get("priority", 99))
    except Exception as exc:
        logger.warning("[INSIGHT_HINTS] build failed (non-blocking): %s", exc)
    return cards
