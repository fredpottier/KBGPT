#!/usr/bin/env python3
"""
Pass C1.4 — Canonicalisation cross-langue (FR <-> EN).

Strategie :
1. Charger les entites non canonicalisees
2. Detecter la langue de chaque nom (heuristique accents + langdetect fallback)
3. Construire 2 pools : FR et EN
4. Embeddings e5-large multilingue (GPU)
5. Paires cross-langue avec cosine > threshold (defaut 0.85)
6. Validation LLM (Qwen72B) avec prompt specialise synonymie cross-langue
7. Persister merges approuves (CanonicalEntity + SAME_CANON_AS method='cross_lingual')

Usage :
    python scripts/canonicalize_cross_lingual.py --dry-run --tenant default
    python scripts/canonicalize_cross_lingual.py --execute --tenant default
    python scripts/canonicalize_cross_lingual.py --execute --threshold 0.82
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Seuil cosine — paires cross-langue sont typiquement 0.82-0.92 sur e5-large
DEFAULT_THRESHOLD = 0.85


# ── Detection de langue (heuristique + langdetect fallback) ────────────

_FRENCH_ACCENTS = re.compile(r"[àâäéèêëïîôöùûüÿçæœÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇÆŒ]")
_FRENCH_WORDS = {
    "le", "la", "les", "des", "du", "de", "un", "une", "aux", "au",
    "est", "sont", "pour", "avec", "dans", "sur", "par", "sans",
    "données", "donnée", "traitement", "responsable", "personne",
    "règlement", "règles", "règle", "protection", "droits", "droit",
}
_ENGLISH_WORDS = {
    "the", "of", "and", "or", "in", "for", "with", "to", "by",
    "data", "processing", "controller", "subject", "person",
    "regulation", "rules", "rule", "protection", "rights", "right",
}


def detect_lang(name: str) -> str:
    """Detecte la langue d'un nom d'entite. Retourne 'fr', 'en' ou 'other'."""
    if not name:
        return "other"
    norm = name.strip().lower()

    # Fast path : accents francais caracteristiques
    if _FRENCH_ACCENTS.search(name):
        return "fr"

    # Match mots communs
    tokens = re.findall(r"[a-zàâäéèêëïîôöùûüÿçæœ]+", norm)
    if not tokens:
        return "other"
    fr_hits = sum(1 for t in tokens if t in _FRENCH_WORDS)
    en_hits = sum(1 for t in tokens if t in _ENGLISH_WORDS)
    if fr_hits > en_hits and fr_hits > 0:
        return "fr"
    if en_hits > fr_hits and en_hits > 0:
        return "en"

    # Fallback : langdetect sur >= 3 tokens (peu fiable sur 1-2 mots)
    if len(tokens) >= 3:
        try:
            from langdetect import detect_langs, LangDetectException
            detected = detect_langs(norm)
            if detected:
                top = detected[0]
                if top.prob >= 0.8 and top.lang in ("fr", "en"):
                    return top.lang
        except (Exception,):
            pass

    # Par defaut : on considere anglais (langue dominante du corpus)
    return "en"


# ── Charger les entites ────────────────────────────────────────────────


@dataclass
class EntityRow:
    entity_id: str
    name: str
    normalized_name: str
    entity_type: str
    claim_count: int
    lang: str = "other"


def load_uncanonicalized_entities(driver, tenant_id: str) -> List[EntityRow]:
    """Charge les entites non rattachees a un CanonicalEntity."""
    query = """
    MATCH (e:Entity {tenant_id: $tid})
    WHERE NOT (e)-[:SAME_CANON_AS]->(:CanonicalEntity)
    OPTIONAL MATCH (e)<-[:ABOUT]-(c:Claim)
    WITH e, count(c) AS claim_count
    WHERE claim_count >= 1
    RETURN e.entity_id AS entity_id,
           e.name AS name,
           coalesce(e.normalized_name, toLower(e.name)) AS normalized_name,
           coalesce(e.entity_type, 'other') AS entity_type,
           claim_count
    ORDER BY claim_count DESC
    """
    rows: List[EntityRow] = []
    with driver.session() as session:
        result = session.run(query, tid=tenant_id)
        for r in result:
            name = r["name"]
            rows.append(
                EntityRow(
                    entity_id=r["entity_id"],
                    name=name,
                    normalized_name=r["normalized_name"],
                    entity_type=r["entity_type"] or "other",
                    claim_count=r["claim_count"] or 0,
                    lang=detect_lang(name),
                )
            )
    return rows


# ── Embeddings + paires cross-langue ────────────────────────────────────


_MODEL_CACHE: Dict[str, Any] = {}


def compute_embeddings(names: List[str], batch_size: int = 32, use_cpu: bool = True) -> np.ndarray:
    """e5-large multilingue.

    Par defaut use_cpu=True pour eviter conflit CUDA avec le worker RQ qui
    a deja e5-large charge sur le GPU (sinon crash du worker container).
    """
    from sentence_transformers import SentenceTransformer
    import torch

    if use_cpu:
        device = "cpu"
    else:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    # Cache du modele entre appels (evite 2 chargements pour FR + EN)
    cache_key = f"{device}"
    if cache_key not in _MODEL_CACHE:
        logger.info(f"[C1.4] Loading e5-large on {device} (once)...")
        _MODEL_CACHE[cache_key] = SentenceTransformer(
            "intfloat/multilingual-e5-large", device=device
        )
    model = _MODEL_CACHE[cache_key]

    logger.info(f"[C1.4] Computing embeddings for {len(names)} entities on {device}...")
    prefixed = [f"query: {n}" for n in names]
    embeddings = model.encode(
        prefixed, batch_size=batch_size, show_progress_bar=False, convert_to_numpy=True
    )
    # Normalise pour cosine via dot product
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return embeddings / norms


def find_cross_lingual_pairs(
    fr: List[EntityRow],
    en: List[EntityRow],
    fr_emb: np.ndarray,
    en_emb: np.ndarray,
    threshold: float,
) -> List[Tuple[EntityRow, EntityRow, float]]:
    """Retourne les paires (fr_entity, en_entity, cosine) au-dessus du seuil."""
    if not fr or not en:
        return []

    # Matrice similarite FR x EN — feasible jusqu'a ~10K x 10K en RAM
    # (5000 x 5000 x 4 bytes = 100MB OK)
    sim = fr_emb @ en_emb.T  # shape (|fr|, |en|)
    pairs: List[Tuple[EntityRow, EntityRow, float]] = []
    # Pour chaque FR, prendre top-k EN au-dessus du threshold
    # Pas de top-k global — on veut toutes les paires pour la deduplication LLM
    indices = np.argwhere(sim >= threshold)
    for fi, ei in indices:
        pairs.append((fr[fi], en[ei], float(sim[fi, ei])))
    # Sort by score DESC pour batch LLM sur les plus probables d'abord
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs


# ── LLM validation (reuse merge_validator) ──────────────────────────────


def llm_validate_pairs(
    pairs: List[Tuple[EntityRow, EntityRow, float]],
    batch_size: int = 10,
) -> List[Dict[str, Any]]:
    """
    Valide les paires cross-langue via Qwen72B.

    Returns list of {entity_ids: [...], canonical: str, decision: str, reason: str}.
    """
    from knowbase.claimfirst.canonicalization.merge_validator import (
        LLMMergeValidator,
        MergeCandidate,
        MergeMember,
    )

    candidates: List[MergeCandidate] = []
    pair_by_gid: Dict[int, Tuple[EntityRow, EntityRow, float]] = {}
    for idx, (fr_e, en_e, score) in enumerate(pairs):
        members = [
            MergeMember(
                entity_id=fr_e.entity_id,
                name=fr_e.name,
                claim_count=fr_e.claim_count,
                entity_type=fr_e.entity_type,
            ),
            MergeMember(
                entity_id=en_e.entity_id,
                name=en_e.name,
                claim_count=en_e.claim_count,
                entity_type=en_e.entity_type,
            ),
        ]
        candidates.append(
            MergeCandidate(
                group_id=idx,
                members=members,
                source_method="cross_lingual",
                max_confidence=score,
            )
        )
        pair_by_gid[idx] = (fr_e, en_e, score)

    validator = LLMMergeValidator(batch_size=batch_size)
    decisions = validator.validate_groups(candidates)

    approved: List[Dict[str, Any]] = []
    stats = {"merge": 0, "keep_separate": 0, "partial": 0, "other": 0}
    for d in decisions:
        stats[d.decision] = stats.get(d.decision, 0) + 1
        if d.decision == "merge" and len(d.approved_entity_ids) == 2:
            fr_e, en_e, score = pair_by_gid[d.group_id]
            # Canonical = nom LLM ou entite la plus utilisee
            canonical = d.canonical
            if not canonical:
                canonical = fr_e.name if fr_e.claim_count >= en_e.claim_count else en_e.name
            approved.append(
                {
                    "entity_ids": d.approved_entity_ids,
                    "canonical": canonical,
                    "entity_type": fr_e.entity_type if fr_e.claim_count >= en_e.claim_count else en_e.entity_type,
                    "score": score,
                    "fr_name": fr_e.name,
                    "en_name": en_e.name,
                    "reason": d.reason,
                }
            )

    logger.info(
        f"[C1.4] LLM decisions: {stats['merge']} merge, "
        f"{stats.get('keep_separate', 0)} keep_separate, "
        f"{stats.get('partial', 0) + stats.get('partial_merge', 0)} partial"
    )
    return approved


# ── Persistance Neo4j ───────────────────────────────────────────────────


def persist_merges(
    driver,
    tenant_id: str,
    approved: List[Dict[str, Any]],
) -> Tuple[int, int]:
    """Persiste CanonicalEntity + SAME_CANON_AS. Retourne (canonicals_created, rels_created)."""
    from knowbase.claimfirst.models.canonical_entity import CanonicalEntity
    from knowbase.claimfirst.models.entity import EntityType

    canonicals = 0
    rels = 0
    with driver.session() as session:
        for m in approved:
            try:
                etype = EntityType(m["entity_type"])
            except ValueError:
                etype = EntityType.OTHER

            ce_id = CanonicalEntity.make_id(tenant_id, m["canonical"])
            session.run(
                """
                MERGE (ce:CanonicalEntity {canonical_entity_id: $ce_id})
                ON CREATE SET ce.canonical_name = $name,
                              ce.tenant_id = $tid,
                              ce.entity_type = $etype,
                              ce.method = 'cross_lingual',
                              ce.source = 'c1.4_cross_lingual',
                              ce.created_at = datetime()
                ON MATCH SET ce.method = coalesce(ce.method, 'cross_lingual')
                """,
                ce_id=ce_id,
                name=m["canonical"],
                tid=tenant_id,
                etype=etype.value,
            )
            canonicals += 1

            for eid in m["entity_ids"]:
                session.run(
                    """
                    MATCH (e:Entity {entity_id: $eid, tenant_id: $tid})
                    MATCH (ce:CanonicalEntity {canonical_entity_id: $ce_id})
                    MERGE (e)-[r:SAME_CANON_AS]->(ce)
                    ON CREATE SET r.method = 'cross_lingual',
                                  r.confidence = $score,
                                  r.created_at = datetime()
                    """,
                    eid=eid,
                    ce_id=ce_id,
                    tid=tenant_id,
                    score=m["score"],
                )
                rels += 1

    return canonicals, rels


# ── Main ────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="C1.4 — Cross-lingual entity canonicalization (FR<->EN)"
    )
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--llm-batch-size", type=int, default=10)
    parser.add_argument("--max-candidates", type=int, default=500,
                        help="Limite paires soumises au LLM (safety).")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_pass = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))

    try:
        # Phase 1 — Charger entites
        logger.info(f"[C1.4] Phase 1 — Chargement entites (tenant={args.tenant})...")
        entities = load_uncanonicalized_entities(driver, args.tenant)
        logger.info(f"[C1.4]   → {len(entities)} entities uncanonicalized loaded")

        if not entities:
            logger.info("[C1.4] No entities to process.")
            return

        # Phase 2 — Detecter langues
        logger.info("[C1.4] Phase 2 — Detection langues...")
        fr = [e for e in entities if e.lang == "fr"]
        en = [e for e in entities if e.lang == "en"]
        other = [e for e in entities if e.lang == "other"]
        logger.info(f"[C1.4]   FR: {len(fr)}, EN: {len(en)}, other: {len(other)}")
        if not fr or not en:
            logger.info("[C1.4] Pas assez d'entities dans les deux langues — abort.")
            return

        # Phase 3 — Embeddings
        logger.info("[C1.4] Phase 3 — Embeddings (multilingual-e5-large)...")
        fr_emb = compute_embeddings([e.name for e in fr])
        en_emb = compute_embeddings([e.name for e in en])

        # Phase 4 — Paires cross-langue
        logger.info(f"[C1.4] Phase 4 — Recherche paires cross-langue (seuil {args.threshold})...")
        pairs = find_cross_lingual_pairs(fr, en, fr_emb, en_emb, args.threshold)
        logger.info(f"[C1.4]   → {len(pairs)} paires au-dessus du seuil")

        if not pairs:
            logger.info("[C1.4] Aucune paire cross-langue detectee — terminé.")
            return

        if len(pairs) > args.max_candidates:
            logger.info(
                f"[C1.4] Limite max-candidates ({args.max_candidates}) — garde les "
                f"plus probables (sorted by cosine desc)."
            )
            pairs = pairs[: args.max_candidates]

        # Preview des top paires
        logger.info("[C1.4] Top 15 paires candidates :")
        for fr_e, en_e, score in pairs[:15]:
            logger.info(
                f"  {score:.3f} | FR: {fr_e.name[:40]!r:42s} ↔ EN: {en_e.name[:40]!r}"
            )
        if len(pairs) > 15:
            logger.info(f"  ... +{len(pairs) - 15} more pairs")

        # Phase 5 — Validation LLM
        logger.info(f"[C1.4] Phase 5 — Validation LLM ({len(pairs)} paires)...")
        approved = llm_validate_pairs(pairs, batch_size=args.llm_batch_size)
        logger.info(f"[C1.4]   → {len(approved)} paires approuvees LLM")

        # Preview approuvees
        logger.info("[C1.4] Paires APPROUVEES (echantillon) :")
        for m in approved[:20]:
            logger.info(
                f"  {m['score']:.3f} | FR: {m['fr_name'][:40]!r:42s} ↔ EN: {m['en_name'][:40]!r} → {m['canonical']!r}"
            )

        # Phase 6 — Persist / dry-run
        if args.dry_run:
            logger.info(f"\n[C1.4] DRY-RUN — {len(approved)} merges seraient appliqués.")
            logger.info("       Relancer avec --execute pour persister.")
        else:
            logger.info(f"\n[C1.4] Phase 6 — Persistance Neo4j...")
            canonicals, rels = persist_merges(driver, args.tenant, approved)
            logger.info(
                f"[C1.4]   → {canonicals} CanonicalEntity créés, {rels} SAME_CANON_AS"
            )

    finally:
        driver.close()


if __name__ == "__main__":
    main()
