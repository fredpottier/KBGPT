#!/usr/bin/env python3
"""
poc_evidence_pack.py — Génère les evidence packs pour les 2 concepts POC.

Concept Assembly Engine (Couche 4 OSMOSE) — Phase 1 : Evidence Pack.
Valide que le couple KG + Qdrant suffit pour produire un evidence pack sain
sur EDPB et controller. Pas de LLM — uniquement assemblage déterministe.

Usage :
    docker compose exec app python scripts/poc_evidence_pack.py
    docker compose exec app python scripts/poc_evidence_pack.py --concept "EDPB"
    docker compose exec app python scripts/poc_evidence_pack.py --concept "controller"
    docker compose exec app python scripts/poc_evidence_pack.py --output-dir data/poc_wiki/
"""

import argparse
import json
import logging
import os
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("[OSMOSE] poc_evidence_pack")

POC_CONCEPTS = ["EDPB", "controller"]


def get_neo4j_driver():
    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def get_qdrant():
    from knowbase.common.clients.qdrant_client import get_qdrant_client

    return get_qdrant_client()


def get_embeddings():
    from knowbase.common.clients.embeddings import get_embedding_manager

    return get_embedding_manager()


def slugify(name: str) -> str:
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def generate_diagnostic(concept_name: str, pack) -> str:
    """Génère un rapport de diagnostic texte lisible (Amendement A6)."""
    c = pack.concept
    q = pack.quality_signals

    lines = [
        f"=== DIAGNOSTIC: {concept_name} ===",
        f"Résolution: method={c.resolution_method}, confidence={c.resolution_confidence}, "
        f"entities={len(c.entity_ids)}, aliases={len(c.aliases)}",
    ]

    if c.ambiguity_notes:
        lines.append(f"Ambiguïtés: {'; '.join(c.ambiguity_notes)}")

    lines.append(f"Claims bruts: {q.claim_units} ({q.doc_count} docs)")

    # Répartition par doc
    lines.append("Répartition par doc:")
    for src in pack.source_index:
        pct = src.contribution_pct * 100
        cap_note = " → CAP appliqué" if pct > 40 else ""
        lines.append(f"  {src.doc_id}: {pct:.0f}% ({src.unit_count} units){cap_note}")

    # Répartition par rhetorical_role
    from collections import Counter

    role_counts = Counter(u.rhetorical_role for u in pack.units)
    lines.append("Répartition par rhetorical_role:")
    for role, count in role_counts.most_common():
        lines.append(f"  {role}: {count}")

    # Chunks
    chunk_units = [u for u in pack.units if u.source_type == "chunk"]
    def_chunks = [u for u in chunk_units if u.rhetorical_role == "definition"]
    lines.append(
        f"Chunks récupérés: {len(chunk_units)}, "
        f"définitoires: {len(def_chunks)}"
    )
    if def_chunks:
        top_chunk = def_chunks[0]
        lines.append(
            f"  Top chunk définitoire: \"{top_chunk.text[:80]}...\""
        )

    # Temporal
    if pack.temporal_evolution:
        t = pack.temporal_evolution
        lines.append(
            f"Temporal: {len(t.timeline)} steps sur axe '{t.axis_name}'"
        )
        for step in t.timeline:
            lines.append(
                f"  {step.axis_value}: {step.change_type} ({len(step.unit_ids)} units)"
            )
    else:
        lines.append("Temporal: aucune évolution détectée")

    # Contradictions
    lines.append(
        f"Conflicts: {q.confirmed_conflict_count} confirmed, "
        f"{q.candidate_tension_count} candidate_tension"
    )

    # Quality
    lines.append(f"coherence_risk: {q.coherence_risk_score}")
    if q.coherence_risk_factors:
        lines.append(f"  facteurs: {', '.join(q.coherence_risk_factors)}")
    lines.append(f"coverage: {q.coverage_score}")
    lines.append(f"scope_diversity: {q.scope_diversity_score}")

    # Diagnostic flags
    flagged = [u for u in pack.units if u.diagnostic_flags]
    if flagged:
        lines.append(f"Units avec flags: {len(flagged)}")
        flag_counts = Counter(
            f for u in flagged for f in u.diagnostic_flags
        )
        for flag, count in flag_counts.most_common():
            lines.append(f"  {flag}: {count}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="POC Evidence Pack — Concept Assembly Engine (Couche 4 OSMOSE)"
    )
    parser.add_argument(
        "--concept",
        type=str,
        default=None,
        help="Concept cible (défaut : EDPB + controller)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/poc_wiki/",
        help="Répertoire de sortie",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default="default",
        help="Tenant ID",
    )
    args = parser.parse_args()

    concepts = [args.concept] if args.concept else POC_CONCEPTS
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    logger.info("=" * 60)
    logger.info("POC EVIDENCE PACK — Concept Assembly Engine")
    logger.info(f"Concepts: {concepts}")
    logger.info(f"Output: {output_dir}")
    logger.info("=" * 60)

    # Initialisation des clients
    driver = get_neo4j_driver()
    qdrant = get_qdrant()
    embeddings = get_embeddings()

    from knowbase.wiki.concept_resolver import ConceptResolver
    from knowbase.wiki.evidence_pack_builder import EvidencePackBuilder

    resolver = ConceptResolver(driver)
    builder = EvidencePackBuilder(driver, qdrant, embeddings)

    start_total = time.time()
    stats_global = {"concepts": 0, "errors": 0, "total_units": 0}

    for concept_name in concepts:
        logger.info(f"\n{'─' * 40}")
        logger.info(f"Concept: {concept_name}")
        logger.info(f"{'─' * 40}")

        start = time.time()
        try:
            # Étape 1 : Résolution
            resolved = resolver.resolve(concept_name, args.tenant_id)
            logger.info(
                f"Résolu: {resolved.canonical_name} "
                f"({resolved.resolution_method}, conf={resolved.resolution_confidence})"
            )
            logger.info(
                f"  {resolved.claim_count} claims, "
                f"{len(resolved.doc_ids)} docs, "
                f"{len(resolved.facet_domains)} facettes"
            )

            # Étape 2 : Construction du pack
            pack = builder.build(resolved, args.tenant_id)

            # Sérialiser JSON
            slug = slugify(concept_name)
            json_path = os.path.join(output_dir, f"evidence_pack_{slug}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(pack.model_dump(), f, indent=2, ensure_ascii=False)
            logger.info(f"JSON: {json_path}")

            # Générer diagnostic
            diag = generate_diagnostic(concept_name, pack)
            diag_path = os.path.join(output_dir, f"diagnostic_{slug}.txt")
            with open(diag_path, "w", encoding="utf-8") as f:
                f.write(diag)
            logger.info(f"Diagnostic: {diag_path}")

            # Résumé
            q = pack.quality_signals
            elapsed = time.time() - start
            logger.info(f"\n  RÉSUMÉ {concept_name}:")
            logger.info(f"    Units: {q.total_units} (claims={q.claim_units}, chunks={q.chunk_units})")
            logger.info(f"    Docs: {q.doc_count}")
            logger.info(f"    Coverage: {q.coverage_score}")
            logger.info(f"    Coherence risk: {q.coherence_risk_score}")
            logger.info(f"    Conflicts: {q.confirmed_conflict_count}, Tensions: {q.candidate_tension_count}")
            logger.info(f"    Temporal: {'oui' if q.has_temporal_data else 'non'}")
            logger.info(f"    Définition: {'oui' if q.has_definition else 'non'}")
            logger.info(f"    Durée: {elapsed:.1f}s")

            stats_global["concepts"] += 1
            stats_global["total_units"] += q.total_units

        except ValueError as e:
            logger.error(f"ERREUR résolution: {e}")
            stats_global["errors"] += 1
        except Exception as e:
            logger.error(f"ERREUR inattendue pour '{concept_name}': {e}", exc_info=True)
            stats_global["errors"] += 1

    driver.close()

    total_elapsed = time.time() - start_total
    logger.info(f"\n{'=' * 60}")
    logger.info("POC EVIDENCE PACK — TERMINÉ")
    logger.info(f"{'=' * 60}")
    logger.info(f"  Concepts traités: {stats_global['concepts']}")
    logger.info(f"  Erreurs: {stats_global['errors']}")
    logger.info(f"  Total units: {stats_global['total_units']}")
    logger.info(f"  Durée totale: {total_elapsed:.1f}s")
    logger.info(f"  Output: {output_dir}")


if __name__ == "__main__":
    main()
