#!/usr/bin/env python3
"""
Clustering cross-document rétroactif des claims existantes dans Neo4j.

Les ClaimClusters existants sont 100% single-doc car le clustering (Phase 5)
s'exécute dans orchestrator.process() qui ne voit qu'un seul document.
Ce script crée des clusters cross-doc via Jaccard sur entités partagées.

Algorithme :
1. Charger claims avec entités depuis Neo4j
2. Index inversé entité → claims (entités dans 2+ docs uniquement)
3. Comparer pairwise cross-doc (Jaccard ≥ seuil + même modalité + pas négation inversée)
4. Union-Find → clusters
5. Persister ClaimCluster + IN_CLUSTER (sans supprimer les single-doc existants)

Usage (dans le conteneur Docker) :
    python scripts/cluster_cross_doc.py --dry-run --tenant default
    python scripts/cluster_cross_doc.py --execute --tenant default
    python scripts/cluster_cross_doc.py --execute --tenant default --min-jaccard 0.35
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import uuid
from collections import defaultdict
from typing import Dict, List, Set

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ── Constantes ──────────────────────────────────────────────────────────────

STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall",
    "can", "need", "to", "of", "in", "for", "on", "with", "at",
    "by", "from", "as", "into", "through", "during", "before",
    "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "and", "but", "if",
    "or", "because", "until", "while", "this", "that", "these",
    "those", "which", "who", "whom", "what", "whose",
}

STRONG_OBLIGATION = {"must", "shall", "required", "mandatory", "obligatory"}
WEAK_OBLIGATION = {"should", "recommended", "advisable"}
PERMISSION = {"may", "can", "allowed", "permitted", "optional"}

NEGATION_PATTERNS = [
    re.compile(r"\bnot\b"), re.compile(r"\bno\b"),
    re.compile(r"\bnever\b"), re.compile(r"\bnone\b"),
    re.compile(r"\bcannot\b"), re.compile(r"\bcan't\b"),
    re.compile(r"\bwon't\b"), re.compile(r"\bdon't\b"),
    re.compile(r"\bwithout\b"), re.compile(r"\bexcept\b"),
    re.compile(r"\bexclud"),
]

MAX_CLAIMS_PER_ENTITY = 200


def _score_claim_quality(claim: dict) -> float:
    """
    Score qualité pour champion selection (cross-doc).

    Préfère claims vérifiées, structurées, connectées — pas verbeuses.
    """
    import json as _json

    # Parse quality_scores si disponible
    verif = 0.85  # défaut conservateur
    quality_scores_json = claim.get("quality_scores_json")
    if quality_scores_json:
        try:
            qs = _json.loads(quality_scores_json)
            verif = qs.get("verif_score", 0.85)
        except (ValueError, TypeError):
            pass

    has_sf = 1.0 if claim.get("structured_form_json") else 0.0
    has_entities = 1.0 if claim.get("entity_count", 0) > 0 else 0.0
    text_len = len(claim.get("text", ""))

    return 100 * verif + 10 * has_sf + 5 * has_entities - 0.02 * text_len


# ── Fonctions utilitaires ───────────────────────────────────────────────────

def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def extract_key_tokens(text: str) -> Set[str]:
    """Extrait les tokens significatifs d'un texte."""
    tokens = re.findall(r"\b[a-zA-Z]+\b", text.lower())
    return {t for t in tokens if t not in STOP_WORDS and len(t) > 2}


def jaccard_similarity(s1: Set[str], s2: Set[str]) -> float:
    """Calcule la similarité Jaccard entre deux ensembles."""
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def extract_modality(text: str) -> str:
    """Extrait la modalité d'un texte (strong/weak/permission/neutral)."""
    tl = text.lower()
    for w in STRONG_OBLIGATION:
        if re.search(rf"\b{w}\b", tl):
            return "strong"
    for w in WEAK_OBLIGATION:
        if re.search(rf"\b{w}\b", tl):
            return "weak"
    for w in PERMISSION:
        if re.search(rf"\b{w}\b", tl):
            return "permission"
    return "neutral"


def has_inverted_negation(text1: str, text2: str) -> bool:
    """Détecte si deux textes ont une négation inversée."""
    def count_neg(text):
        tl = text.lower()
        return sum(1 for p in NEGATION_PATTERNS if p.search(tl))
    return (count_neg(text1) > 0) != (count_neg(text2) > 0)


# ── Union-Find ──────────────────────────────────────────────────────────────

class UnionFind:
    """Structure Union-Find avec compression de chemin."""

    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str) -> None:
        px, py = self.find(x), self.find(y)
        if px != py:
            self.parent[px] = py

    def groups(self) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = defaultdict(set)
        for x in self.parent:
            result[self.find(x)].add(x)
        return dict(result)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Clustering cross-document rétroactif des claims"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les modifications")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    parser.add_argument("--min-jaccard", type=float, default=0.30,
                        help="Seuil Jaccard minimum (default: 0.30)")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    min_jaccard = args.min_jaccard

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # 1. Charger claims avec entités
            logger.info(f"[OSMOSE] Chargement des claims avec entités (tenant={args.tenant})...")
            result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)
                RETURN c.claim_id AS claim_id, c.doc_id AS doc_id,
                       c.text AS text, c.confidence AS confidence,
                       c.structured_form_json AS structured_form_json,
                       c.quality_scores_json AS quality_scores_json,
                       collect(e.normalized_name) AS entity_names
                """,
                tid=args.tenant,
            )
            claims_data: Dict[str, dict] = {}
            entity_to_claims: Dict[str, Set[str]] = defaultdict(set)
            for r in result:
                cid = r["claim_id"]
                claims_data[cid] = {
                    "claim_id": cid,
                    "doc_id": r["doc_id"],
                    "text": r["text"] or "",
                    "confidence": r["confidence"] or 0.5,
                    "entity_names": r["entity_names"] or [],
                    "structured_form_json": r.get("structured_form_json"),
                    "quality_scores_json": r.get("quality_scores_json"),
                    "entity_count": len(r["entity_names"] or []),
                }
                for ename in r["entity_names"]:
                    entity_to_claims[ename].add(cid)

            # Stats initiales
            doc_ids = sorted({c["doc_id"] for c in claims_data.values()})
            logger.info(f"  → {len(claims_data)} claims avec entités")
            logger.info(f"  → {len(doc_ids)} documents")
            logger.info(f"  → {len(entity_to_claims)} entités uniques")

            if len(doc_ids) < 2:
                logger.info("Moins de 2 documents, pas de clustering cross-doc possible.")
                return

            # 2. Filtrer entités cross-doc, exclure hubs
            cross_doc_groups: Dict[str, Set[str]] = {}
            hubs_excluded = 0
            for ename, cids in entity_to_claims.items():
                edoc_ids = {claims_data[cid]["doc_id"] for cid in cids if cid in claims_data}
                if len(edoc_ids) < 2:
                    continue
                if len(cids) > MAX_CLAIMS_PER_ENTITY:
                    hubs_excluded += 1
                    continue
                cross_doc_groups[ename] = cids

            logger.info(f"  → {len(cross_doc_groups)} entités cross-doc candidates")
            logger.info(f"  → {hubs_excluded} hubs exclus (>{MAX_CLAIMS_PER_ENTITY} claims)")

            if not cross_doc_groups:
                logger.info("Aucune entité cross-doc trouvée.")
                return

            # 3. Pré-calculer tokens et modalité
            tokens_cache = {cid: extract_key_tokens(c["text"]) for cid, c in claims_data.items()}
            modality_cache = {cid: extract_modality(c["text"]) for cid, c in claims_data.items()}

            # 4. Comparer pairwise cross-doc
            logger.info(f"\n[OSMOSE] Comparaison pairwise cross-doc (Jaccard ≥ {min_jaccard})...")
            uf = UnionFind()
            pairs_validated = 0
            pairs_rejected = {
                "same_doc": 0,
                "low_jaccard": 0,
                "modality_mismatch": 0,
                "negation_inversion": 0,
            }

            for ename, cids in cross_doc_groups.items():
                cids_list = sorted(cids)
                for i, cid1 in enumerate(cids_list):
                    c1 = claims_data.get(cid1)
                    if not c1:
                        continue
                    for cid2 in cids_list[i + 1:]:
                        c2 = claims_data.get(cid2)
                        if not c2:
                            continue
                        if c1["doc_id"] == c2["doc_id"]:
                            pairs_rejected["same_doc"] += 1
                            continue
                        j = jaccard_similarity(tokens_cache[cid1], tokens_cache[cid2])
                        if j < min_jaccard:
                            pairs_rejected["low_jaccard"] += 1
                            continue
                        if modality_cache[cid1] != modality_cache[cid2]:
                            pairs_rejected["modality_mismatch"] += 1
                            continue
                        if has_inverted_negation(c1["text"], c2["text"]):
                            pairs_rejected["negation_inversion"] += 1
                            continue
                        uf.union(cid1, cid2)
                        pairs_validated += 1

            logger.info(f"  → {pairs_validated} paires cross-doc validées")
            logger.info(f"  → Rejections: {dict(pairs_rejected)}")

            if pairs_validated == 0:
                logger.info("Aucune paire cross-doc validée.")
                return

            # 5. Former les clusters
            all_groups = uf.groups()
            cross_clusters = []
            for root, cids in all_groups.items():
                cdoc_ids = sorted({claims_data[cid]["doc_id"] for cid in cids if cid in claims_data})
                if len(cdoc_ids) < 2:
                    continue
                cross_clusters.append((sorted(cids), cdoc_ids))

            logger.info(f"  → {len(cross_clusters)} clusters cross-doc formés")

            # Détails des clusters
            for i, (cids, cdocs) in enumerate(cross_clusters[:20]):
                claim_objs = [claims_data[cid] for cid in cids if cid in claims_data]
                best = max(claim_objs, key=lambda c: c["confidence"])
                logger.info(
                    f"  Cluster {i+1}: {len(cids)} claims, {len(cdocs)} docs, "
                    f"label='{best['text'][:80]}'"
                )

            # Clusters existants
            existing_result = session.run(
                """
                MATCH (cc:ClaimCluster {tenant_id: $tid})
                WHERE cc.doc_count > 1
                RETURN count(cc) AS count
                """,
                tid=args.tenant,
            )
            existing_xd = existing_result.single()["count"]
            logger.info(f"\n  Clusters cross-doc existants: {existing_xd}")

            # Résumé
            logger.info(f"\n{'='*60}")
            logger.info("RÉSUMÉ CLUSTERING CROSS-DOC")
            logger.info(f"{'='*60}")
            logger.info(f"Claims avec entités    : {len(claims_data)}")
            logger.info(f"Documents              : {len(doc_ids)}")
            logger.info(f"Entités cross-doc      : {len(cross_doc_groups)}")
            logger.info(f"Paires validées        : {pairs_validated}")
            logger.info(f"Clusters cross-doc     : {len(cross_clusters)}")
            logger.info(f"Clusters existants (xd): {existing_xd}")

            if args.dry_run:
                logger.info("\n[DRY-RUN] Aucune modification effectuée.")
                logger.info("    Utilisez --execute pour appliquer.")
                return

            # 6. Persister
            logger.info(f"\n[OSMOSE] Persistance des {len(cross_clusters)} clusters cross-doc...")
            clusters_created = 0
            for cids, cdocs in cross_clusters:
                cluster_id = f"cluster_xd_{uuid.uuid4().hex[:12]}"
                claim_objs = [claims_data[cid] for cid in cids if cid in claims_data]
                if not claim_objs:
                    continue
                best = max(claim_objs, key=lambda c: c["confidence"])
                avg_conf = sum(c["confidence"] for c in claim_objs) / len(claim_objs)

                session.run(
                    """
                    MERGE (cc:ClaimCluster {cluster_id: $cid, tenant_id: $tid})
                    SET cc.canonical_label = $label,
                        cc.claim_count = $claim_count,
                        cc.doc_count = $doc_count,
                        cc.doc_ids = $doc_ids,
                        cc.avg_confidence = $avg_conf,
                        cc.cross_doc = true,
                        cc.method = 'jaccard_cross_doc'
                    """,
                    cid=cluster_id,
                    tid=args.tenant,
                    label=best["text"][:100],
                    claim_count=len(cids),
                    doc_count=len(cdocs),
                    doc_ids=cdocs,
                    avg_conf=avg_conf,
                )

                for claim_id in cids:
                    session.run(
                        """
                        MATCH (c:Claim {claim_id: $claim_id, tenant_id: $tid})
                        MATCH (cc:ClaimCluster {cluster_id: $cluster_id, tenant_id: $tid})
                        MERGE (c)-[:IN_CLUSTER]->(cc)
                        """,
                        claim_id=claim_id,
                        tid=args.tenant,
                        cluster_id=cluster_id,
                    )

                clusters_created += 1

            logger.info(f"  → {clusters_created} clusters cross-doc créés")

            # 7. Champion selection — marquer le champion et les redundants
            logger.info("\n[OSMOSE] Champion selection (quality-based scoring)...")
            champions_marked = 0
            redundants_marked = 0
            for cids, cdocs in cross_clusters:
                claim_objs = [claims_data[cid] for cid in cids if cid in claims_data]
                if not claim_objs:
                    continue

                # Scorer chaque claim par qualité
                scored = [(c, _score_claim_quality(c)) for c in claim_objs]
                scored.sort(key=lambda x: x[1], reverse=True)
                champion = scored[0][0]

                # Marquer le champion
                session.run(
                    """
                    MATCH (c:Claim {claim_id: $cid, tenant_id: $tid})
                    SET c.is_champion = true
                    """,
                    cid=champion["claim_id"],
                    tid=args.tenant,
                )
                champions_marked += 1

                # Marquer les redundants
                for c, _ in scored[1:]:
                    session.run(
                        """
                        MATCH (c:Claim {claim_id: $cid, tenant_id: $tid})
                        SET c.redundant = true, c.champion_claim_id = $champion_id
                        """,
                        cid=c["claim_id"],
                        tid=args.tenant,
                        champion_id=champion["claim_id"],
                    )
                    redundants_marked += 1

            logger.info(
                f"  → {champions_marked} champions marked, "
                f"{redundants_marked} redundants marked"
            )

            # Vérification finale
            final_result = session.run(
                """
                MATCH (cc:ClaimCluster {tenant_id: $tid})
                WHERE cc.doc_count > 1
                RETURN count(cc) AS count
                """,
                tid=args.tenant,
            )
            final_xd = final_result.single()["count"]
            logger.info(f"  → Total clusters cross-doc après persistance: {final_xd}")

            logger.info("\n[OSMOSE] Clustering cross-doc terminé.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
