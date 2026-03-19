"""
ImportanceScorer — Scoring d'importance des concepts pour le Knowledge Atlas.

Score calculé depuis Neo4j pour chaque entité :
    importance = log(1 + claim_count) + 1.5 * log(1 + doc_count) + 0.5 * graph_degree

Seuils Tier (percentile-based) :
    Tier 1 (top ~5%)  — Portails / concepts structurants (doc_count >= 2 requis)
    Tier 2 (next ~15%) — Concepts principaux
    Tier 3 (reste)     — Concepts spécifiques

Filtrage qualité pour la génération Atlas :
    - Consolidation SAME_CANON_AS (éviter les doublons d'articles)
    - Exclusion des entités trop génériques pour mériter un article
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Set

logger = logging.getLogger("[OSMOSE] importance_scorer")

# Entités trop génériques pour mériter un article Atlas autonome.
# Distincte de la ENTITY_STOPLIST (qui filtre à l'extraction).
# Ici on filtre à la génération : ces termes sont utiles comme entités KG
# (ex: "women" dans "women with preeclampsia") mais pas comme sujets d'article.
ATLAS_UNWANTED_ENTITIES: frozenset[str] = frozenset({
    # Populations / sujets génériques
    "women", "men", "patients", "children", "infants", "neonates",
    "adults", "individuals", "people", "persons", "subjects",
    "participants", "population", "populations", "cohort", "cohorts",
    "mothers", "fathers", "newborns", "pregnant women",
    # Termes méthodologiques
    "studies", "study", "research", "analysis", "review", "reviews",
    "meta-analysis", "trial", "trials", "clinical trial", "clinical trials",
    "evidence", "literature", "publication", "publications",
    "data", "results", "findings", "outcomes", "outcome",
    "methods", "methodology", "approach", "approaches",
    "guidelines", "guideline", "recommendations", "recommendation",
    "criteria", "criterion", "protocol", "protocols",
    # Termes temporels / quantitatifs
    "years", "months", "weeks", "days", "hours",
    "levels", "level", "rate", "rates", "risk", "risks",
    "group", "groups", "sample", "samples",
    "treatment", "treatments", "therapy", "therapies",
    "diagnosis", "management", "assessment", "evaluation",
    "measurement", "measurements", "testing", "test", "tests",
    # Termes anatomiques ultra-génériques
    "blood", "plasma", "serum", "urine", "tissue",
    "cells", "cell",
    # Mots de liaison déguisés en entités
    "use", "effect", "effects", "role", "association",
    "relationship", "impact", "comparison", "combination",
    "prevention", "intervention", "monitoring",
})


@dataclass
class ScoredConcept:
    """Concept avec score d'importance calculé."""

    entity_name: str
    entity_type: str
    entity_id: str
    claim_count: int
    doc_count: int
    graph_degree: int
    importance_score: float
    importance_tier: int  # 1, 2, 3


def compute_importance(claim_count: int, doc_count: int, graph_degree: int) -> float:
    return (
        math.log(1 + claim_count)
        + 1.5 * math.log(1 + doc_count)
        + 0.5 * graph_degree
    )


class ImportanceScorer:
    """Calcule les scores d'importance pour tous les concepts d'un tenant."""

    def __init__(self, neo4j_driver):
        self._driver = neo4j_driver

    def score_all_concepts(self, tenant_id: str = "default") -> List[ScoredConcept]:
        """
        Calcule le score d'importance de tous les concepts (Entity) du tenant.

        Étapes :
        1. Récupérer les métriques depuis Neo4j
        2. Filtrer les entités non-article-worthy (génériques, trop courtes)
        3. Dédupliquer via SAME_CANON_AS (garder le meilleur par groupe canonical)
        4. Scorer et trier

        Retourne la liste triée par importance_score décroissant, avec tier assigné.
        """
        raw = self._fetch_concept_metrics(tenant_id)
        if not raw:
            return []

        # Filtre qualité : exclure les entités non-article-worthy
        filtered = self._filter_article_worthy(raw)

        # Dédupliquer via SAME_CANON_AS
        deduped = self._deduplicate_canonicals(filtered, tenant_id)

        scored = []
        for r in deduped:
            score = compute_importance(r["claim_count"], r["doc_count"], r["graph_degree"])
            scored.append(
                ScoredConcept(
                    entity_name=r["name"],
                    entity_type=r["entity_type"] or "concept",
                    entity_id=r["entity_id"],
                    claim_count=r["claim_count"],
                    doc_count=r["doc_count"],
                    graph_degree=r["graph_degree"],
                    importance_score=round(score, 3),
                    importance_tier=3,  # défaut, recalculé ci-dessous
                )
            )

        scored.sort(key=lambda c: c.importance_score, reverse=True)
        self._assign_tiers(scored)

        logger.info(
            f"[OSMOSE:ImportanceScorer] {len(raw)} entités → "
            f"{len(filtered)} après filtre qualité → "
            f"{len(deduped)} après dedup canonicals → "
            f"Tier 1: {sum(1 for c in scored if c.importance_tier == 1)}, "
            f"Tier 2: {sum(1 for c in scored if c.importance_tier == 2)}, "
            f"Tier 3: {sum(1 for c in scored if c.importance_tier == 3)}"
        )

        return scored

    def _fetch_concept_metrics(self, tenant_id: str) -> List[dict]:
        """Récupère claim_count, doc_count et graph_degree depuis Neo4j."""
        query = """
        MATCH (e:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (c:Claim)-[:ABOUT]->(e)
        WITH e, count(DISTINCT c) AS claim_count,
             count(DISTINCT c.doc_id) AS doc_count
        OPTIONAL MATCH (e)-[rel]-(other)
        WHERE type(rel) <> 'ABOUT'
        WITH e, claim_count, doc_count, count(DISTINCT rel) AS graph_degree
        WHERE claim_count > 0
        RETURN e.entity_id AS entity_id,
               e.name AS name,
               e.entity_type AS entity_type,
               claim_count,
               doc_count,
               graph_degree
        """
        with self._driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [dict(r) for r in result]

    def _filter_article_worthy(self, raw: List[dict]) -> List[dict]:
        """
        Filtre les entités qui ne méritent pas un article Atlas autonome.

        Critères d'exclusion :
        - Nom dans ATLAS_UNWANTED_ENTITIES (populations, méthodologie, etc.)
        - Nom trop court (1-2 chars sauf acronymes majuscules validés)
        - Nom purement numérique
        - Nom qui ressemble à une phrase (> 6 mots)
        - entity_type = 'OTHER' avec peu de claims (< 5)
        """
        kept = []
        rejected = 0
        for r in raw:
            name = r["name"]
            name_lower = name.lower().strip()

            # Stoplist Atlas
            if name_lower in ATLAS_UNWANTED_ENTITIES:
                rejected += 1
                continue

            # Trop court (sauf acronymes 2-3 majuscules)
            if len(name_lower) <= 2 and not re.match(r"^[A-Z]{2,3}$", name):
                rejected += 1
                continue

            # Purement numérique
            if re.match(r"^[\d\s\.\-/]+$", name_lower):
                rejected += 1
                continue

            # Phrase trop longue (> 6 mots → probablement pas un concept)
            if len(name_lower.split()) > 6:
                rejected += 1
                continue

            # entity_type OTHER avec peu de claims → bruit
            if (r["entity_type"] or "").lower() == "other" and r["claim_count"] < 5:
                rejected += 1
                continue

            kept.append(r)

        if rejected:
            logger.info(f"[OSMOSE:QualityFilter] {rejected} entités exclues (non-article-worthy)")
        return kept

    def _deduplicate_canonicals(self, raw: List[dict], tenant_id: str) -> List[dict]:
        """
        Déduplique les entités en 2 passes :

        1. SAME_CANON_AS — regroupe les entités liées à un même CanonicalEntity
        2. Similarité de nom — regroupe les entités qui partagent un nom-racine
           (ex: "sFlt-1", "sFLT1 levels", "sFlt-1/PlGF ratio" → groupe "sflt")

        Pour chaque groupe, garde le meilleur représentant (plus de claims)
        et agrège les métriques des variants.
        """
        entity_ids = [r["entity_id"] for r in raw]
        if not entity_ids:
            return raw

        entity_index = {r["entity_id"]: r for r in raw}
        suppressed: Set[str] = set()

        # ── Passe 1 : SAME_CANON_AS ──────────────────────────────────
        canonical_groups: dict[str, list[str]] = {}
        with self._driver.session() as session:
            result = session.run(
                """
                UNWIND $eids AS eid
                MATCH (e:Entity {entity_id: eid, tenant_id: $tid})
                OPTIONAL MATCH (e)-[:SAME_CANON_AS]->(ce:CanonicalEntity)
                RETURN e.entity_id AS eid, ce.canonical_entity_id AS canon_id
                """,
                eids=entity_ids, tid=tenant_id,
            )
            for r in result:
                canon_id = r["canon_id"]
                if canon_id:
                    canonical_groups.setdefault(canon_id, []).append(r["eid"])

        suppressed.update(self._merge_group(canonical_groups, entity_index))

        # ── Passe 2 : similarité de nom (stem-based) ─────────────────
        # Extraire un "stem" normalisé pour chaque entité restante
        remaining = [r for r in raw if r["entity_id"] not in suppressed]
        stem_groups: dict[str, list[str]] = {}

        for r in remaining:
            stem = self._extract_stem(r["name"])
            if stem and len(stem) >= 3:
                stem_groups.setdefault(stem, []).append(r["entity_id"])

        # Ne merger que les groupes > 1 et où le stem est substantiel
        stem_merges: dict[str, list[str]] = {}
        for stem, eids in stem_groups.items():
            if len(eids) > 1:
                stem_merges[stem] = eids

        suppressed.update(self._merge_group(stem_merges, entity_index))

        canon_count = sum(1 for g in canonical_groups.values() if len(g) > 1)
        stem_count = len(stem_merges)
        total_suppressed = len(suppressed)

        if total_suppressed:
            logger.info(
                f"[OSMOSE:Dedup] {total_suppressed} variants supprimés — "
                f"{canon_count} groupes SAME_CANON_AS, {stem_count} groupes par similarité de nom"
            )

        return [r for r in raw if r["entity_id"] not in suppressed]

    @staticmethod
    def _merge_group(
        groups: dict[str, list[str]],
        entity_index: dict[str, dict],
    ) -> Set[str]:
        """
        Pour chaque groupe avec > 1 membre, garde le meilleur (plus de claims)
        et agrège les métriques des variants. Retourne les entity_ids supprimés.
        """
        suppressed: Set[str] = set()
        for _, member_ids in groups.items():
            if len(member_ids) <= 1:
                continue

            members = [entity_index[eid] for eid in member_ids if eid in entity_index]
            if len(members) <= 1:
                continue

            members.sort(key=lambda m: m["claim_count"], reverse=True)
            best = members[0]

            for other in members[1:]:
                if other["entity_id"] in suppressed:
                    continue  # déjà supprimé par un groupe précédent
                best["claim_count"] += other["claim_count"]
                best["doc_count"] = max(best["doc_count"], other["doc_count"])
                best["graph_degree"] += other["graph_degree"]
                suppressed.add(other["entity_id"])

        return suppressed

    @staticmethod
    def _extract_stem(name: str) -> str:
        """
        Extrait un 'stem' normalisé pour regrouper les variants d'un même concept.

        Exemples :
        - "sFlt-1" → "sflt1"
        - "sFLT1 family of proteins" → "sflt1"
        - "sFlt-1/PlGF ratio" → "sflt1plgf"
        - "Pre-eclampsia" → "preeclampsia"
        - "PAPP-A levels" → "pappa"

        Stratégie : strip diacritiques, normaliser, retirer les mots-suffixes
        génériques, normaliser terminaisons cross-langue.
        """
        # Strip diacritics : pré-éclampsie → pre-eclampsie
        s = "".join(
            c for c in unicodedata.normalize("NFD", name.lower().strip())
            if unicodedata.category(c) != "Mn"
        )

        # Retirer les acronymes entre parenthèses : "Preeclampsia (PE)" → "Preeclampsia"
        s = re.sub(r"\s*\([A-Za-z]{1,6}\)\s*$", "", s)

        # Retirer les suffixes génériques courants
        suffix_noise = [
            "levels", "level", "values", "value", "ratio", "ratios",
            "test", "tests", "assay", "assays", "measurements", "measurement",
            "family of proteins", "family", "proteins", "protein",
            "concentration", "concentrations", "serum", "plasma",
            "cut-off", "cut-offs", "cutoff", "cutoffs",
        ]
        for suffix in suffix_noise:
            if s.endswith(" " + suffix):
                s = s[: -(len(suffix) + 1)].strip()

        # Retirer les préfixes génériques
        prefix_noise = [
            "elevated", "increased", "decreased", "high", "low",
            "total", "mean", "median", "circulating",
        ]
        words = s.split()
        if words and words[0] in prefix_noise:
            s = " ".join(words[1:])

        # Normaliser les séparateurs en espaces pour splitter proprement
        s = re.sub(r"[-‐–—/]", " ", s)

        # Retirer les mots de liaison
        link_words = {"to", "of", "and", "the", "in", "for", "on", "with", "by"}
        s = " ".join(w for w in s.split() if w not in link_words)

        # Retirer ponctuation et espaces → stem compact
        s = re.sub(r"[^a-z0-9]", "", s)

        # Normaliser terminaisons cross-langue : -ie (FR) → -ia (EN)
        if s.endswith("ie") and len(s) > 5:
            s = s[:-2] + "ia"

        return s

    def compute_web_priority(
        self,
        candidates: List[ScoredConcept],
        tenant_id: str = "default",
    ) -> List[ScoredConcept]:
        """
        Stratégie "toile" — re-trie les candidats pour tisser un réseau connecté.

        Boost les concepts qui partagent des claims avec des entités déjà couvertes
        par un WikiArticle publié. Le premier batch sera trié par importance pure.
        Les suivants tissent la toile autour des articles existants.

        Score final = importance_score + connectivity_boost
        connectivity_boost = 2.0 * connected_articles + 0.5 * shared_claims_log
        """
        if not candidates:
            return candidates

        # Récupérer les entity_ids couverts par des articles existants
        connectivity: dict[str, tuple[int, int]] = {}  # entity_id → (connected_articles, shared_claims)
        candidate_ids = [c.entity_id for c in candidates]

        with self._driver.session() as session:
            # Pour chaque candidat, compter combien d'articles existants
            # couvrent des entités qui co-apparaissent dans les mêmes claims
            result = session.run(
                """
                UNWIND $candidate_ids AS cand_id
                MATCH (e_cand:Entity {entity_id: cand_id, tenant_id: $tid})
                OPTIONAL MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e_cand),
                               (c)-[:ABOUT]->(e_other:Entity),
                               (wa:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e_other)
                WHERE e_other <> e_cand
                WITH cand_id, count(DISTINCT wa) AS connected_articles,
                     count(DISTINCT c) AS shared_claims
                RETURN cand_id, connected_articles, shared_claims
                """,
                candidate_ids=candidate_ids,
                tid=tenant_id,
            )
            for r in result:
                connectivity[r["cand_id"]] = (r["connected_articles"], r["shared_claims"])

        # Appliquer le boost
        has_existing_articles = any(v[0] > 0 for v in connectivity.values())

        if not has_existing_articles:
            # Aucun article existant → importance pure (premier batch)
            logger.info("[OSMOSE:WebPriority] Aucun article existant — tri par importance pure")
            return candidates

        boosted = []
        for c in candidates:
            connected, shared = connectivity.get(c.entity_id, (0, 0))
            boost = 2.0 * connected + 0.5 * math.log(1 + shared)
            boosted.append((c, c.importance_score + boost, connected))

        boosted.sort(key=lambda x: x[1], reverse=True)

        top_connected = sum(1 for _, _, conn in boosted[:10] if conn > 0)
        logger.info(
            f"[OSMOSE:WebPriority] {len(boosted)} candidats re-triés — "
            f"top 10 : {top_connected}/10 connectés à des articles existants"
        )

        return [c for c, _, _ in boosted]

    def _assign_tiers(self, scored: List[ScoredConcept]) -> None:
        """Assigne les tiers en percentile-based. Tier 1 requiert doc_count >= 2."""
        n = len(scored)
        if n == 0:
            return

        tier1_cutoff = max(1, int(n * 0.05))  # top 5%
        tier2_cutoff = max(tier1_cutoff + 1, int(n * 0.20))  # next 15% (cumul 20%)

        for i, concept in enumerate(scored):
            if i < tier1_cutoff and concept.doc_count >= 2:
                concept.importance_tier = 1
            elif i < tier2_cutoff:
                concept.importance_tier = 2
            else:
                concept.importance_tier = 3
