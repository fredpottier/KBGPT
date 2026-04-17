#!/usr/bin/env python3
"""
Consolidation des racines de Facets (Pass F1.1).

Problème observé : plusieurs racines semantiquement identiques coexistent —
`privacy.*` + `data_protection.*` + `gdpr.*` pointent vers le meme concept.
Cette fragmentation empeche l'aggregation naturelle et baisse artificiellement
le linkage Claim->Facet.

Strategie (miroir de la canonicalisation d'entites) :
1. Charger toutes les Facet, grouper par racine (split domain sur '.')
2. Pour chaque racine, construire une "signature" = root_name + top-5 facet_names
3. Embeddings multilingual-e5-large (CPU pour eviter conflit GPU worker)
4. Paires de racines avec cosine > threshold
5. Validation LLM Qwen72B (decision : merge | keep_separate | partial_merge)
6. Persister : renommer `domain` des facets du perdant vers la racine gagnante

Usage :
    python scripts/consolidate_facet_roots.py --dry-run --tenant default
    python scripts/consolidate_facet_roots.py --execute --tenant default
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.75  # Plus bas que entity canon : les noms de racines sont courts


# ── Model singleton ────────────────────────────────────────────────────


_MODEL = None


def get_model():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        logger.info("[F1.1] Loading e5-large on CPU (avoids GPU conflict)...")
        _MODEL = SentenceTransformer("intfloat/multilingual-e5-large", device="cpu")
    return _MODEL


# ── Dataclasses ────────────────────────────────────────────────────────


@dataclass
class RootSignature:
    """Signature semantique d'une racine = nom + facets."""
    root: str
    facet_count: int
    total_claims: int
    facet_names: List[str] = field(default_factory=list)
    facet_ids: List[str] = field(default_factory=list)

    @property
    def signature_text(self) -> str:
        """Texte pour embedding : root + top facets."""
        parts = [self.root.replace("_", " ")]
        parts.extend(self.facet_names[:5])
        return " | ".join(parts)


# ── Load facets ────────────────────────────────────────────────────────


def load_facets_by_root(driver, tenant_id: str) -> Dict[str, RootSignature]:
    query = """
    MATCH (f:Facet {tenant_id: $tid})
    OPTIONAL MATCH (c:Claim)-[:BELONGS_TO_FACET]->(f)
    WITH f, count(c) AS claim_count
    RETURN f.facet_id AS facet_id,
           f.domain AS domain,
           f.facet_name AS name,
           claim_count
    ORDER BY claim_count DESC
    """
    by_root: Dict[str, RootSignature] = {}
    with driver.session() as session:
        result = session.run(query, tid=tenant_id)
        for r in result:
            domain = r["domain"] or ""
            root = domain.split(".")[0] if "." in domain else domain
            if not root:
                continue
            if root not in by_root:
                by_root[root] = RootSignature(root=root, facet_count=0, total_claims=0)
            sig = by_root[root]
            sig.facet_count += 1
            sig.total_claims += r["claim_count"] or 0
            sig.facet_ids.append(r["facet_id"])
            if len(sig.facet_names) < 10:
                sig.facet_names.append(r["name"])
    return by_root


# ── Embeddings + paires ────────────────────────────────────────────────


def compute_root_embeddings(roots: List[RootSignature]) -> np.ndarray:
    texts = [f"query: {r.signature_text}" for r in roots]
    model = get_model()
    logger.info(f"[F1.1] Computing {len(texts)} root embeddings...")
    emb = model.encode(texts, batch_size=16, show_progress_bar=False, convert_to_numpy=True)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return emb / norms


def find_candidate_pairs(
    roots: List[RootSignature],
    emb: np.ndarray,
    threshold: float,
) -> List[Tuple[int, int, float]]:
    n = len(roots)
    pairs = []
    sim = emb @ emb.T
    for i in range(n):
        for j in range(i + 1, n):
            score = float(sim[i, j])
            if score >= threshold:
                pairs.append((i, j, score))
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs


# ── LLM validation ─────────────────────────────────────────────────────


def llm_validate_pairs(
    pairs: List[Tuple[int, int, float]],
    roots: List[RootSignature],
    batch_size: int = 8,
) -> List[Dict[str, Any]]:
    from knowbase.claimfirst.canonicalization.merge_validator import (
        LLMMergeValidator,
        MergeCandidate,
        MergeMember,
    )

    candidates = []
    pair_map: Dict[int, Tuple[RootSignature, RootSignature, float]] = {}
    for idx, (i, j, score) in enumerate(pairs):
        r_i, r_j = roots[i], roots[j]
        # Contexte riche pour le LLM : root + facets + total claims
        members = [
            MergeMember(
                entity_id=r_i.root,
                name=f"{r_i.root} [{r_i.facet_count} facets, {r_i.total_claims} claims]: {', '.join(r_i.facet_names[:3])}",
                claim_count=r_i.total_claims,
                entity_type="facet_root",
            ),
            MergeMember(
                entity_id=r_j.root,
                name=f"{r_j.root} [{r_j.facet_count} facets, {r_j.total_claims} claims]: {', '.join(r_j.facet_names[:3])}",
                claim_count=r_j.total_claims,
                entity_type="facet_root",
            ),
        ]
        candidates.append(
            MergeCandidate(
                group_id=idx,
                members=members,
                source_method="facet_root_consolidation",
                max_confidence=score,
            )
        )
        pair_map[idx] = (r_i, r_j, score)

    validator = LLMMergeValidator(batch_size=batch_size)
    decisions = validator.validate_groups(candidates)

    approved = []
    stats = {"merge": 0, "keep_separate": 0, "partial": 0}
    for d in decisions:
        stats[d.decision] = stats.get(d.decision, 0) + 1
        if d.decision == "merge":
            r_i, r_j, score = pair_map[d.group_id]
            # Canonical = root avec le plus de claims (sinon LLM suggest)
            if d.canonical and d.canonical in (r_i.root, r_j.root):
                winner = d.canonical
            else:
                winner = r_i.root if r_i.total_claims >= r_j.total_claims else r_j.root
            loser = r_j.root if winner == r_i.root else r_i.root
            approved.append({
                "winner": winner,
                "loser": loser,
                "score": score,
                "winner_claims": max(r_i.total_claims, r_j.total_claims),
                "loser_claims": min(r_i.total_claims, r_j.total_claims),
                "reason": d.reason,
            })
    logger.info(
        f"[F1.1] LLM decisions: {stats.get('merge', 0)} merge, "
        f"{stats.get('keep_separate', 0)} keep_separate"
    )
    return approved


# ── Transitive closure (graph des merges) ──────────────────────────────


def resolve_transitive_winners(approved: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Si A→B et B→C, alors A→C. Resolve par union-find.

    Returns: dict {loser_root -> canonical_root}
    """
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        if x not in parent:
            parent[x] = x
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Pour chaque merge, unir loser → winner (direction vers canonical)
    for m in approved:
        union(m["loser"], m["winner"])

    # Extraire les mappings finaux
    mapping: Dict[str, str] = {}
    all_nodes = set()
    for m in approved:
        all_nodes.add(m["loser"])
        all_nodes.add(m["winner"])
    for node in all_nodes:
        canonical = find(node)
        if canonical != node:
            mapping[node] = canonical
    return mapping


# ── Persist ────────────────────────────────────────────────────────────


def dedup_facets_by_name(driver, tenant_id: str) -> Dict[str, int]:
    """
    Phase 6 : dedup exact-match sur facet_name.

    Apres la consolidation des racines, il reste des facets avec le meme
    facet_name mais des domains differents (ex: "Data Subject Rights" sous
    privacy.enforcement, privacy.data_subject_rights, privacy.rights...).

    Strategie deterministe (sans LLM) :
    1. Grouper les facets par facet_name exact
    2. Winner = facet avec le plus de claims lies
    3. Rediriger les BELONGS_TO_FACET des losers vers le winner
    4. Marquer les losers lifecycle='deprecated'
    """
    stats = {"groups_found": 0, "facets_deprecated": 0, "rels_redirected": 0}

    with driver.session() as session:
        # 1. Identifier les groupes de doublons exacts (facets validees/candidates uniquement)
        groups = session.run(
            """
            MATCH (f:Facet {tenant_id: $tid})
            WHERE f.lifecycle IS NULL OR f.lifecycle <> 'deprecated'
            OPTIONAL MATCH (c:Claim)-[:BELONGS_TO_FACET]->(f)
            WITH f, count(c) AS claim_count
            WITH f.facet_name AS name,
                 collect({fid: f.facet_id, claims: claim_count, domain: f.domain}) AS members
            WHERE size(members) > 1
            RETURN name, members
            """,
            tid=tenant_id,
        ).values()

        for name, members in groups:
            if not name:
                continue
            stats["groups_found"] += 1
            # Winner = celui avec le plus de claims, tiebreak sur domain le plus court
            sorted_members = sorted(
                members,
                key=lambda m: (-m["claims"], len(m["domain"] or "")),
            )
            winner = sorted_members[0]
            losers = sorted_members[1:]

            for loser in losers:
                # Rediriger les BELONGS_TO_FACET
                redirect = session.run(
                    """
                    MATCH (source:Facet {facet_id: $sid})
                    MATCH (target:Facet {facet_id: $tid_facet})
                    MATCH (c:Claim)-[rel:BELONGS_TO_FACET]->(source)
                    MERGE (c)-[:BELONGS_TO_FACET]->(target)
                    DELETE rel
                    RETURN count(rel) AS redirected
                    """,
                    sid=loser["fid"],
                    tid_facet=winner["fid"],
                ).single()
                stats["rels_redirected"] += redirect["redirected"] or 0

                # Deprecated
                session.run(
                    """
                    MATCH (f:Facet {facet_id: $fid})
                    SET f.lifecycle = 'deprecated',
                        f.deprecated_at = datetime(),
                        f.deprecated_for = $target_fid,
                        f.deprecation_reason = 'duplicate_facet_name'
                    """,
                    fid=loser["fid"],
                    target_fid=winner["fid"],
                )
                stats["facets_deprecated"] += 1

    return stats


def persist_canonical_roots(
    driver,
    tenant_id: str,
    mapping: Dict[str, str],
) -> int:
    """Persiste les mappings en nodes CanonicalFacetRoot pour anti-drift futur.

    Chaque racine canonique recoit un node avec la liste de ses aliases.
    FacetRegistry.register_candidates() consultera ces nodes pour eviter
    de recreer les racines absorbees lors de futurs imports.
    """
    # Grouper par winner canonical
    canonicals_to_aliases: Dict[str, List[str]] = {}
    for loser, winner in mapping.items():
        canonicals_to_aliases.setdefault(winner, []).append(loser)

    count = 0
    with driver.session() as session:
        for canonical, aliases in canonicals_to_aliases.items():
            # Recuperer aliases existants et fusionner (sans APOC)
            existing = session.run(
                """
                MATCH (cr:CanonicalFacetRoot {canonical_root: $canonical, tenant_id: $tid})
                RETURN cr.aliases AS aliases
                """,
                canonical=canonical,
                tid=tenant_id,
            ).single()
            merged = list(set((existing["aliases"] if existing else []) + aliases))
            session.run(
                """
                MERGE (cr:CanonicalFacetRoot {canonical_root: $canonical, tenant_id: $tid})
                ON CREATE SET cr.created_at = datetime()
                SET cr.aliases = $aliases,
                    cr.updated_at = datetime()
                """,
                canonical=canonical,
                aliases=merged,
                tid=tenant_id,
            )
            count += 1
    return count


def persist_merges(
    driver,
    tenant_id: str,
    mapping: Dict[str, str],
) -> Tuple[int, int]:
    """Renomme le domain des facets du loser root vers winner root.

    Exemple : si 'data_protection' → 'privacy', alors
    'data_protection.rights' devient 'privacy.rights'.
    Le parent_domain est aussi recalcule.
    """
    updated_facets = 0
    skipped = 0
    with driver.session() as session:
        for loser, winner in mapping.items():
            # Trouver toutes les facets sous le loser root
            result = session.run(
                """
                MATCH (f:Facet {tenant_id: $tid})
                WHERE split(f.domain, '.')[0] = $loser
                RETURN f.facet_id AS fid, f.domain AS domain
                """,
                tid=tenant_id,
                loser=loser,
            )
            for r in result:
                old_domain = r["domain"]
                # Replacer la premiere partie
                parts = old_domain.split(".")
                parts[0] = winner
                new_domain = ".".join(parts)

                # Verifier collision : existe-t-il deja une facet avec ce new_domain ?
                collision = session.run(
                    """
                    MATCH (f:Facet {tenant_id: $tid, domain: $new_domain})
                    RETURN f.facet_id AS fid LIMIT 1
                    """,
                    tid=tenant_id,
                    new_domain=new_domain,
                ).single()

                if collision:
                    # Collision : rediriger les claims de la source vers la cible
                    # puis marquer la source comme deprecated
                    session.run(
                        """
                        MATCH (source:Facet {facet_id: $sid})
                        MATCH (target:Facet {facet_id: $tid_facet})
                        MATCH (c:Claim)-[rel:BELONGS_TO_FACET]->(source)
                        MERGE (c)-[:BELONGS_TO_FACET]->(target)
                        DELETE rel
                        """,
                        sid=r["fid"],
                        tid_facet=collision["fid"],
                    )
                    session.run(
                        """
                        MATCH (f:Facet {facet_id: $fid})
                        SET f.lifecycle = 'deprecated',
                            f.deprecated_at = datetime(),
                            f.deprecated_for = $target
                        """,
                        fid=r["fid"],
                        target=collision["fid"],
                    )
                    skipped += 1
                else:
                    # Renommer
                    session.run(
                        """
                        MATCH (f:Facet {facet_id: $fid})
                        SET f.domain = $new_domain,
                            f.parent_domain = $new_parent
                        """,
                        fid=r["fid"],
                        new_domain=new_domain,
                        new_parent=winner,
                    )
                    updated_facets += 1

    return updated_facets, skipped


# ── Main ────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="F1.1 — Facet root consolidation")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--llm-batch-size", type=int, default=8)
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")),
    )

    try:
        # Phase 1 : charger les racines + signatures
        logger.info(f"[F1.1] Phase 1 — Loading facets (tenant={args.tenant})...")
        by_root = load_facets_by_root(driver, args.tenant)
        logger.info(f"[F1.1]   → {len(by_root)} distinct roots")

        if len(by_root) < 2:
            logger.info("[F1.1] Pas assez de racines pour consolidation.")
            return

        roots_list = sorted(by_root.values(), key=lambda r: r.total_claims, reverse=True)
        logger.info("[F1.1] Top 15 roots par claim count :")
        for r in roots_list[:15]:
            logger.info(
                f"  {r.total_claims:5d} claims | {r.facet_count:3d} facets | "
                f"{r.root:30s} → {', '.join(r.facet_names[:3])}"
            )

        # Phase 2 : embeddings
        logger.info("[F1.1] Phase 2 — Embeddings...")
        emb = compute_root_embeddings(roots_list)

        # Phase 3 : paires candidates
        logger.info(f"[F1.1] Phase 3 — Finding candidate pairs (threshold {args.threshold})...")
        pairs = find_candidate_pairs(roots_list, emb, args.threshold)
        logger.info(f"[F1.1]   → {len(pairs)} candidate pairs")

        if not pairs:
            logger.info("[F1.1] Aucune paire candidate — rien à faire.")
            return

        logger.info("[F1.1] Top 15 candidate pairs :")
        for i, j, score in pairs[:15]:
            logger.info(
                f"  {score:.3f} | {roots_list[i].root!r:25s} ↔ {roots_list[j].root!r:25s} "
                f"({roots_list[i].total_claims}+{roots_list[j].total_claims} claims)"
            )

        # Phase 4 : LLM validation
        logger.info(f"[F1.1] Phase 4 — LLM validation ({len(pairs)} pairs)...")
        approved = llm_validate_pairs(pairs, roots_list, args.llm_batch_size)

        if not approved:
            logger.info("[F1.1] Aucune paire approuvee par LLM — terminé.")
            return

        # Transitive closure : si A→B, B→C, alors A→C
        mapping = resolve_transitive_winners(approved)
        logger.info(f"[F1.1]   → {len(approved)} direct merges, {len(mapping)} final mappings (after transitive)")

        logger.info("[F1.1] Mappings finaux :")
        for loser, winner in sorted(mapping.items()):
            source_sig = by_root.get(loser)
            winner_sig = by_root.get(winner)
            if source_sig and winner_sig:
                logger.info(
                    f"  {source_sig.root!r:25s} ({source_sig.facet_count} facets, {source_sig.total_claims} claims) "
                    f"→ {winner_sig.root!r:25s} (gagnant)"
                )

        if args.dry_run:
            # Calcul du re-linkage attendu
            total_losers = sum(by_root[l].facet_count for l in mapping if l in by_root)
            logger.info(f"\n[F1.1] DRY-RUN — {total_losers} facets seraient renommees/fusionnees.")
            logger.info("       Relancer avec --execute pour persister.")
        else:
            logger.info("\n[F1.1] Phase 5 — Persistance Neo4j...")
            updated, skipped = persist_merges(driver, args.tenant, mapping)
            logger.info(
                f"[F1.1]   → {updated} facets renommees, {skipped} fusions (collision)"
            )
            # Anti-drift : persister les CanonicalFacetRoot pour futurs imports
            cr_count = persist_canonical_roots(driver, args.tenant, mapping)
            logger.info(
                f"[F1.1]   → {cr_count} CanonicalFacetRoot nodes crees/mis a jour "
                f"(anti-drift pour futurs imports)"
            )

            # Phase 6 : dedup facet_name exact (post-rename, il reste des doublons
            # avec meme facet_name sous differents domains)
            logger.info("\n[F1.1] Phase 6 — Dedup exact facet_name...")
            dedup_stats = dedup_facets_by_name(driver, args.tenant)
            logger.info(
                f"[F1.1]   → {dedup_stats['groups_found']} groupes de doublons detectes, "
                f"{dedup_stats['facets_deprecated']} facets deprecated, "
                f"{dedup_stats['rels_redirected']} relations BELONGS_TO_FACET redirigees"
            )

    finally:
        driver.close()


if __name__ == "__main__":
    main()
