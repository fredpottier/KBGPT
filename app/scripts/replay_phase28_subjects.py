#!/usr/bin/env python3
"""
Replay Phase 2.8 — Redériver les SubjectAnchors depuis les entités canonicalisées.

Reconstruit le claim_entity_map depuis les relations (Claim)-[:ABOUT]->(Entity)
en Neo4j, puis applique la logique Phase 2.8 (seuils adaptatifs + LLM subjectness
+ SubjectResolver avec bypass validation).

Utile quand le code Phase 2.8 a été corrigé APRÈS un import batch.

Usage (dans le conteneur Docker) :
    # Dry-run — affiche les candidats et verdicts LLM sans persister
    python scripts/replay_phase28_subjects.py --dry-run --tenant default

    # Exécuter — persiste SubjectAnchors + met à jour ABOUT_SUBJECT
    python scripts/replay_phase28_subjects.py --execute --tenant default

    # Un seul document
    python scripts/replay_phase28_subjects.py --execute --doc-id 028_SAP_S4HANA...
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# --- Phase 2.8 constants (mêmes que orchestrator.py) ---
MIN_ENTITY_CLAIMS = 8
MIN_ENTITY_COVERAGE_FLOOR = 0.005  # 0.5% plancher pour gros docs
MAX_CANDIDATES_FOR_LLM = 12
MAX_FINAL_SUBJECTS = 5


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def get_imported_doc_ids(session, tenant_id: str) -> List[str]:
    """Liste tous les doc_ids qui ont des claims avec des liens ABOUT vers des entities."""
    result = session.run(
        """
        MATCH (c:Claim)-[:ABOUT]->(e:Entity)
        WHERE c.tenant_id = $tenant_id
        RETURN DISTINCT c.doc_id AS doc_id
        ORDER BY doc_id
        """,
        tenant_id=tenant_id,
    )
    return [r["doc_id"] for r in result]


def load_doc_context(session, doc_id: str, tenant_id: str) -> Optional[dict]:
    """Charge le DocumentContext pour un document."""
    result = session.run(
        """
        MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
        RETURN dc.primary_subject AS primary_subject,
               dc.subject_ids AS subject_ids,
               dc.doc_id AS doc_id,
               dc.tenant_id AS tenant_id
        """,
        doc_id=doc_id,
        tenant_id=tenant_id,
    )
    record = result.single()
    if record:
        return {
            "doc_id": record["doc_id"],
            "tenant_id": record["tenant_id"],
            "primary_subject": record["primary_subject"],
            "subject_ids": record["subject_ids"] or [],
        }
    return None


def load_doc_title(session, doc_id: str) -> Optional[str]:
    """Récupère le titre du document depuis le noeud Document."""
    result = session.run(
        """
        MATCH (d:Document {doc_id: $doc_id})
        RETURN d.title AS title
        """,
        doc_id=doc_id,
    )
    record = result.single()
    return record["title"] if record else None


def build_claim_entity_map(session, doc_id: str, tenant_id: str) -> Tuple[Dict[str, List[str]], Dict[str, dict], Dict[str, dict]]:
    """
    Reconstruit le claim_entity_map depuis Neo4j.

    Returns:
        (claim_entity_map, entities_by_id, claims_by_id)
        - claim_entity_map: {claim_id: [entity_id, ...]}
        - entities_by_id: {entity_id: {entity_id, name, entity_type}}
        - claims_by_id: {claim_id: {claim_id, text}}
    """
    # Charger les relations Claim-[:ABOUT]->Entity
    result = session.run(
        """
        MATCH (c:Claim {doc_id: $doc_id, tenant_id: $tenant_id})-[:ABOUT]->(e:Entity)
        RETURN c.claim_id AS claim_id, c.text AS claim_text,
               e.entity_id AS entity_id, e.name AS entity_name,
               e.entity_type AS entity_type
        """,
        doc_id=doc_id,
        tenant_id=tenant_id,
    )

    claim_entity_map: Dict[str, List[str]] = defaultdict(list)
    entities_by_id: Dict[str, dict] = {}
    claims_by_id: Dict[str, dict] = {}

    for record in result:
        cid = record["claim_id"]
        eid = record["entity_id"]
        claim_entity_map[cid].append(eid)

        if eid not in entities_by_id:
            entities_by_id[eid] = {
                "entity_id": eid,
                "name": record["entity_name"],
                "entity_type": record["entity_type"] or "OTHER",
            }

        if cid not in claims_by_id:
            claims_by_id[cid] = {
                "claim_id": cid,
                "text": record["claim_text"],
            }

    return dict(claim_entity_map), entities_by_id, claims_by_id


def compute_candidates(
    claim_entity_map: Dict[str, List[str]],
    entities_by_id: Dict[str, dict],
    total_claims: int,
) -> List[dict]:
    """
    Étape A : candidats coverage-based avec seuil adaptatif.

    Returns:
        Liste triée par claim_count DESC, max MAX_CANDIDATES_FOR_LLM
    """
    entity_claim_counts: Counter = Counter()
    for claim_id, entity_ids in claim_entity_map.items():
        for eid in entity_ids:
            entity_claim_counts[eid] += 1

    # Seuil adaptatif
    if total_claims > 0:
        min_coverage = max(
            MIN_ENTITY_CLAIMS / total_claims,
            MIN_ENTITY_COVERAGE_FLOOR,
        )
    else:
        min_coverage = 0.03

    logger.info(
        f"    Seuil adaptatif: {min_coverage:.3f} ({min_coverage * 100:.1f}%) "
        f"pour {total_claims} claims"
    )

    candidates = []
    for entity_id, claim_count in entity_claim_counts.items():
        entity = entities_by_id.get(entity_id)
        if not entity:
            continue
        coverage = claim_count / total_claims if total_claims > 0 else 0
        if claim_count >= MIN_ENTITY_CLAIMS and coverage >= min_coverage:
            candidates.append({
                "entity_id": entity_id,
                "entity_name": entity["name"],
                "entity_type": entity["entity_type"],
                "claim_count": claim_count,
                "coverage": coverage,
            })

    candidates.sort(key=lambda x: x["claim_count"], reverse=True)

    # Log top candidates
    for c in candidates[:8]:
        logger.info(
            f"      '{c['entity_name']}' ({c['claim_count']} claims, "
            f"{c['coverage']:.1%})"
        )

    return candidates[:MAX_CANDIDATES_FOR_LLM]


def build_evidence_pack(
    candidates: List[dict],
    claim_entity_map: Dict[str, List[str]],
    claims_by_id: Dict[str, dict],
) -> List[dict]:
    """
    Étape B : evidence pack diversifié (3 snippets par candidat).

    Returns:
        candidates_json prêt pour le prompt LLM
    """
    # Inverser : entity_id → [claim_ids]
    entity_to_claims: Dict[str, List[str]] = defaultdict(list)
    for claim_id, entity_ids in claim_entity_map.items():
        for eid in entity_ids:
            entity_to_claims[eid].append(claim_id)

    def _pick_diverse_snippets(claim_ids: List[str], n: int = 3) -> List[str]:
        valid = [cid for cid in claim_ids if cid in claims_by_id]
        if len(valid) <= n:
            return [claims_by_id[cid]["text"] for cid in valid]
        step = max(1, len(valid) // n)
        picked = [valid[i * step] for i in range(n)]
        return [claims_by_id[cid]["text"] for cid in picked]

    candidates_json = []
    for c in candidates:
        snippets = _pick_diverse_snippets(entity_to_claims[c["entity_id"]])
        candidates_json.append({
            "index": len(candidates_json) + 1,
            "entity_name": c["entity_name"],
            "entity_type": c["entity_type"],
            "claim_count": c["claim_count"],
            "coverage_pct": round(c["coverage"] * 100, 1),
            "evidence_snippets": snippets,
        })

    return candidates_json


def llm_classify_subjects(
    candidates_json: List[dict],
    doc_title: str,
) -> List[str]:
    """
    Étape C : LLM arbiter "documentary subjectness".

    Returns:
        Liste des entity_name classifiés SUBJECT (max MAX_FINAL_SUBJECTS)
    """
    from knowbase.common.llm_router import get_llm_router, TaskType

    candidates_text = json.dumps(candidates_json, indent=2, ensure_ascii=False)

    prompt = f"""You are classifying entity candidates as document subjects.
A "subject" is a meaningful topic that this document is ABOUT — a useful pivot for navigation and retrieval.

Document: "{doc_title}"

For each candidate below, evidence snippets from the document are provided.
Judge ONLY based on the evidence — is this entity a central topic of the document, or just a mentioned term?

Classify each as:
- SUBJECT: a central topic of this document, useful for navigation
- TOO_GENERIC: too broad to serve as a navigation pivot. Includes: common nouns ("system", "data", "process", "role", "user"), the corpus owner or publisher name if it appears in every document, and umbrella terms so broad they match most documents in a collection
- NOISE: not a meaningful topic

Candidates:
{candidates_text}

Return JSON:
{{"decisions": [{{"index": 1, "verdict": "SUBJECT", "reason": "..."}}]}}"""

    router = get_llm_router()
    response = router.complete(
        task_type=TaskType.METADATA_EXTRACTION,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=1500,
        response_format={"type": "json_object"},
    ).strip()

    data = json.loads(response)
    decisions = data.get("decisions", [])

    valid_names = []
    for d in decisions:
        idx = d.get("index")
        verdict = d.get("verdict", "")
        reason = d.get("reason", "")
        if isinstance(idx, int) and 1 <= idx <= len(candidates_json):
            name = candidates_json[idx - 1]["entity_name"]
            logger.info(f"      [{idx}] {name}: {verdict} — {reason}")
            if verdict == "SUBJECT":
                valid_names.append(name)
        else:
            logger.warning(f"      Invalid index {idx}, skipping")

    return valid_names[:MAX_FINAL_SUBJECTS]


def resolve_subjects(
    valid_names: List[str],
    existing_anchors: List,
    doc_id: str,
    tenant_id: str,
) -> List:
    """
    Étape D : résolution via SubjectResolver.resolve_batch().

    Returns:
        Liste de SubjectAnchor (nouveaux ou existants)
    """
    from knowbase.claimfirst.resolution.subject_resolver import SubjectResolver

    resolver = SubjectResolver(embeddings_client=None, tenant_id=tenant_id)
    results = resolver.resolve_batch(
        raw_subjects=valid_names,
        existing_anchors=existing_anchors,
        doc_id=doc_id,
        skip_name_validation=True,
    )

    anchors = []
    for r in results:
        if r.anchor:
            anchors.append(r.anchor)
            if doc_id not in r.anchor.source_doc_ids:
                r.anchor.source_doc_ids.append(doc_id)
            logger.info(
                f"      → {r.anchor.canonical_name} "
                f"(match={r.match_type}, id={r.anchor.subject_id})"
            )

    return anchors


def load_existing_subject_anchors(session, tenant_id: str) -> List:
    """Charge les SubjectAnchors existants depuis Neo4j en objets Pydantic."""
    from knowbase.claimfirst.models.subject_anchor import SubjectAnchor

    result = session.run(
        """
        MATCH (sa:SubjectAnchor)
        WHERE sa.tenant_id = $tenant_id OR sa.tenant_id IS NULL
        RETURN sa
        """,
        tenant_id=tenant_id,
    )

    anchors = []
    for record in result:
        node = record["sa"]
        try:
            anchor = SubjectAnchor(
                subject_id=node["subject_id"],
                tenant_id=node.get("tenant_id", tenant_id),
                canonical_name=node["canonical_name"],
                aliases_explicit=node.get("aliases_explicit", []),
                aliases_inferred=node.get("aliases_inferred", []),
                aliases_learned=node.get("aliases_learned", []),
                domain=node.get("domain"),
                source_doc_ids=node.get("source_doc_ids", []),
                possible_equivalents=node.get("possible_equivalents", []),
            )
            anchors.append(anchor)
        except Exception as e:
            logger.warning(f"  Skipped anchor {node.get('subject_id')}: {e}")

    return anchors


def persist_results(
    session,
    doc_id: str,
    tenant_id: str,
    new_anchors: List,
    old_subject_ids: List[str],
) -> dict:
    """
    Persiste les SubjectAnchors et met à jour les liens ABOUT_SUBJECT.

    Returns:
        Stats {anchors_created, anchors_existing, links_created, old_links_removed}
    """
    stats = {
        "anchors_created": 0,
        "anchors_existing": 0,
        "links_created": 0,
        "old_links_removed": 0,
    }

    # 1. Supprimer les anciens liens ABOUT_SUBJECT pour ce doc
    if old_subject_ids:
        result = session.run(
            """
            MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
                  -[r:ABOUT_SUBJECT]->(sa:SubjectAnchor)
            DELETE r
            RETURN count(r) AS deleted
            """,
            doc_id=doc_id,
            tenant_id=tenant_id,
        )
        record = result.single()
        stats["old_links_removed"] = record["deleted"] if record else 0

    # 2. Nettoyer subject_ids dans DocumentContext
    session.run(
        """
        MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
        SET dc.subject_ids = []
        """,
        doc_id=doc_id,
        tenant_id=tenant_id,
    )

    # 3. Persister chaque SubjectAnchor (MERGE = idempotent)
    for anchor in new_anchors:
        props = {
            "subject_id": anchor.subject_id,
            "canonical_name": anchor.canonical_name,
            "aliases_explicit": anchor.aliases_explicit,
            "aliases_inferred": anchor.aliases_inferred,
            "aliases_learned": anchor.aliases_learned,
            "domain": anchor.domain,
            "source_doc_ids": anchor.source_doc_ids,
            "possible_equivalents": anchor.possible_equivalents,
            "created_at": anchor.created_at.isoformat(),
            "updated_at": anchor.updated_at.isoformat(),
        }

        result = session.run(
            """
            MERGE (sa:SubjectAnchor {subject_id: $subject_id})
            ON CREATE SET sa += $props
            ON MATCH SET sa.source_doc_ids =
                CASE WHEN $doc_id IN sa.source_doc_ids
                     THEN sa.source_doc_ids
                     ELSE sa.source_doc_ids + $doc_id
                END,
                sa.updated_at = $updated_at
            RETURN CASE WHEN sa.created_at = $created_at THEN 'created' ELSE 'existing' END AS status
            """,
            subject_id=anchor.subject_id,
            props=props,
            doc_id=anchor.source_doc_ids[-1] if anchor.source_doc_ids else "",
            updated_at=anchor.updated_at.isoformat(),
            created_at=anchor.created_at.isoformat(),
        )
        record = result.single()
        if record and record["status"] == "created":
            stats["anchors_created"] += 1
        else:
            stats["anchors_existing"] += 1

    # 4. Créer les liens ABOUT_SUBJECT et mettre à jour subject_ids
    new_subject_ids = [a.subject_id for a in new_anchors]
    for subject_id in new_subject_ids:
        session.run(
            """
            MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
            MATCH (sa:SubjectAnchor {subject_id: $subject_id})
            MERGE (dc)-[:ABOUT_SUBJECT]->(sa)
            """,
            doc_id=doc_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        stats["links_created"] += 1

    # 5. Mettre à jour subject_ids dans DocumentContext
    session.run(
        """
        MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
        SET dc.subject_ids = $subject_ids
        """,
        doc_id=doc_id,
        tenant_id=tenant_id,
        subject_ids=new_subject_ids,
    )

    return stats


def process_document(
    session,
    doc_id: str,
    tenant_id: str,
    existing_anchors: List,
    dry_run: bool = True,
) -> Tuple[List, dict]:
    """
    Traite un document : reconstruit claim_entity_map, applique Phase 2.8.

    Returns:
        (new_anchors, stats)
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"  Document: {doc_id}")

    # Charger le contexte
    doc_ctx = load_doc_context(session, doc_id, tenant_id)
    if not doc_ctx:
        logger.warning(f"    Pas de DocumentContext, skip")
        return [], {"skipped": True}

    doc_title = load_doc_title(session, doc_id) or doc_id
    logger.info(f"    Titre: {doc_title}")
    logger.info(f"    Sujets actuels: {doc_ctx['subject_ids']}")

    # Reconstruire claim_entity_map
    claim_entity_map, entities_by_id, claims_by_id = build_claim_entity_map(
        session, doc_id, tenant_id
    )
    total_claims = len(claims_by_id)
    total_entities = len(entities_by_id)
    total_links = sum(len(eids) for eids in claim_entity_map.values())

    logger.info(
        f"    Claims: {total_claims}, Entities: {total_entities}, "
        f"Links ABOUT: {total_links}"
    )

    if not claim_entity_map:
        logger.warning(f"    Pas de liens Claim→Entity, skip")
        return [], {"skipped": True, "reason": "no_about_links"}

    # Étape A : candidats coverage-based
    candidates = compute_candidates(claim_entity_map, entities_by_id, total_claims)

    if not candidates:
        logger.info(f"    Pas de candidats au-dessus des seuils")
        return [], {"candidates": 0}

    logger.info(f"    {len(candidates)} candidats pour LLM")

    # Étape B : evidence pack
    candidates_json = build_evidence_pack(candidates, claim_entity_map, claims_by_id)

    if dry_run:
        logger.info(f"    [DRY-RUN] Candidats LLM:")
        for c in candidates_json:
            logger.info(
                f"      [{c['index']}] {c['entity_name']} "
                f"({c['claim_count']} claims, {c['coverage_pct']}%)"
            )

    # Étape C : LLM classification
    try:
        valid_names = llm_classify_subjects(candidates_json, doc_title)
    except Exception as e:
        logger.warning(f"    LLM failed: {e}")
        return [], {"llm_error": str(e)}

    if not valid_names:
        logger.info(f"    LLM: aucun SUBJECT")
        return [], {"candidates": len(candidates), "subjects": 0}

    logger.info(f"    LLM sujets: {valid_names}")

    # Étape D : résolution via SubjectResolver
    new_anchors = resolve_subjects(valid_names, existing_anchors, doc_id, tenant_id)

    if not new_anchors:
        logger.info(f"    Résolution: aucun anchor créé/trouvé")
        return [], {"candidates": len(candidates), "subjects": len(valid_names), "anchors": 0}

    if dry_run:
        logger.info(f"    [DRY-RUN] {len(new_anchors)} anchors seraient persistés:")
        for a in new_anchors:
            logger.info(f"      → {a.canonical_name} (id={a.subject_id})")
        return new_anchors, {
            "candidates": len(candidates),
            "subjects": len(valid_names),
            "anchors": len(new_anchors),
            "dry_run": True,
        }

    # Persist
    persist_stats = persist_results(
        session, doc_id, tenant_id, new_anchors, doc_ctx["subject_ids"]
    )
    logger.info(
        f"    Persisté: {persist_stats['anchors_created']} créés, "
        f"{persist_stats['anchors_existing']} existants, "
        f"{persist_stats['links_created']} liens ABOUT_SUBJECT, "
        f"{persist_stats['old_links_removed']} anciens liens supprimés"
    )

    return new_anchors, {
        "candidates": len(candidates),
        "subjects": len(valid_names),
        **persist_stats,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Replay Phase 2.8 — Redériver SubjectAnchors depuis entités canonicalisées"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher le rapport sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les modifications")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    parser.add_argument("--doc-id", default=None,
                        help="Traiter un seul document (sinon tous)")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    mode_label = "DRY-RUN" if args.dry_run else "EXECUTE"
    logger.info(f"[OSMOSE] Replay Phase 2.8 — SubjectAnchors ({mode_label})")
    logger.info(f"  Tenant: {args.tenant}")

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # Charger les doc_ids
            if args.doc_id:
                doc_ids = [args.doc_id]
            else:
                doc_ids = get_imported_doc_ids(session, args.tenant)

            logger.info(f"  Documents à traiter: {len(doc_ids)}")

            if not doc_ids:
                logger.info("  Aucun document avec des liens Claim→Entity trouvé.")
                return

            # Charger les SubjectAnchors existants
            existing_anchors = load_existing_subject_anchors(session, args.tenant)
            logger.info(f"  SubjectAnchors existants: {len(existing_anchors)}")

            # Traiter chaque document
            all_stats = []
            all_new_anchors = []

            for doc_id in doc_ids:
                new_anchors, stats = process_document(
                    session, doc_id, args.tenant, existing_anchors, args.dry_run
                )

                all_stats.append({"doc_id": doc_id, **stats})

                # Ajouter les nouveaux anchors à la liste des existants
                for a in new_anchors:
                    if a not in existing_anchors:
                        existing_anchors.append(a)
                    if a not in all_new_anchors:
                        all_new_anchors.append(a)

            # Rapport final
            logger.info(f"\n{'='*60}")
            logger.info("RAPPORT FINAL")
            logger.info(f"{'='*60}")
            logger.info(f"Documents traités: {len(doc_ids)}")

            total_candidates = sum(s.get("candidates", 0) for s in all_stats)
            total_subjects = sum(s.get("subjects", 0) for s in all_stats)
            total_anchors = sum(s.get("anchors", 0) + s.get("anchors_created", 0) + s.get("anchors_existing", 0) for s in all_stats)
            skipped = sum(1 for s in all_stats if s.get("skipped"))

            logger.info(f"Documents skippés: {skipped}")
            logger.info(f"Total candidats coverage: {total_candidates}")
            logger.info(f"Total sujets LLM: {total_subjects}")
            logger.info(f"SubjectAnchors uniques: {len(all_new_anchors)}")

            if all_new_anchors:
                logger.info(f"\nSubjectAnchors:")
                for a in all_new_anchors:
                    logger.info(f"  → {a.canonical_name} (id={a.subject_id})")

            if args.dry_run:
                logger.info(f"\n[DRY-RUN] Aucune modification. Relancer avec --execute.")
            else:
                total_created = sum(s.get("anchors_created", 0) for s in all_stats)
                total_links = sum(s.get("links_created", 0) for s in all_stats)
                total_removed = sum(s.get("old_links_removed", 0) for s in all_stats)
                logger.info(f"\nAnchors créés: {total_created}")
                logger.info(f"Liens ABOUT_SUBJECT créés: {total_links}")
                logger.info(f"Anciens liens supprimés: {total_removed}")

            logger.info(f"\n[OSMOSE] Replay Phase 2.8 terminé.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
