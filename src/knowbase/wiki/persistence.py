"""
WikiArticlePersister — Persistence Neo4j pour les articles wiki du Knowledge Atlas.

Responsabilités :
- MERGE WikiArticle sur {slug, tenant_id}
- Création/liaison automatique des WikiCategory
- Relation ABOUT vers l'Entity résolue de référence
- Requêtes de navigation (list, home, categories, claims)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("[OSMOSE] wiki_persistence")

CATEGORY_MAP = {
    "product": "Produits",
    "service": "Services",
    "feature": "Fonctionnalités",
    "actor": "Acteurs",
    "concept": "Concepts",
    "legal_term": "Termes juridiques",
    "standard": "Standards",
    "other": "Autres",
}


def _category_for_entity_type(entity_type: str) -> tuple[str, str]:
    """Retourne (category_key, label) pour un entity_type."""
    label = CATEGORY_MAP.get(entity_type, CATEGORY_MAP["other"])
    key = entity_type if entity_type in CATEGORY_MAP else "other"
    return key, label


class WikiArticlePersister:
    """Persistence des articles wiki dans Neo4j."""

    def __init__(self, neo4j_driver):
        self._driver = neo4j_driver

    # ── Save ──────────────────────────────────────────────────────────────

    def save_article(
        self,
        slug: str,
        title: str,
        tenant_id: str,
        entity_type: str,
        language: str,
        markdown: str,
        sections_count: int,
        total_citations: int,
        generation_confidence: float,
        all_gaps: List[str],
        source_count: int,
        unit_count: int,
        source_details: List[dict],
        resolution_method: str,
        resolution_confidence: float,
        importance_score: float,
        importance_tier: int,
        entity_ids: List[str],
        related_concepts: Optional[List[dict]] = None,
    ) -> str:
        """
        MERGE un WikiArticle dans Neo4j. Crée/lie la WikiCategory et la relation ABOUT.

        Returns:
            Le slug de l'article persisté.
        """
        category_key, category_label = _category_for_entity_type(entity_type)
        now = datetime.now(timezone.utc).isoformat()

        query = """
        MERGE (wa:WikiArticle {slug: $slug, tenant_id: $tenant_id})
        ON CREATE SET wa.created_at = $now
        SET wa.title = $title,
            wa.language = $language,
            wa.entity_type = $entity_type,
            wa.category_key = $category_key,
            wa.markdown = $markdown,
            wa.sections_count = $sections_count,
            wa.total_citations = $total_citations,
            wa.generation_confidence = $generation_confidence,
            wa.all_gaps = $all_gaps_json,
            wa.source_count = $source_count,
            wa.unit_count = $unit_count,
            wa.source_details = $source_details_json,
            wa.related_concepts = $related_concepts_json,
            wa.resolution_method = $resolution_method,
            wa.resolution_confidence = $resolution_confidence,
            wa.importance_score = $importance_score,
            wa.importance_tier = $importance_tier,
            wa.status = 'published',
            wa.updated_at = $now
        WITH wa
        MERGE (wc:WikiCategory {category_key: $category_key, tenant_id: $tenant_id})
        ON CREATE SET wc.label = $category_label
        MERGE (wa)-[:IN_CATEGORY]->(wc)
        RETURN wa.slug AS slug
        """

        with self._driver.session() as session:
            session.run(
                query,
                slug=slug,
                tenant_id=tenant_id,
                title=title,
                language=language,
                entity_type=entity_type,
                category_key=category_key,
                category_label=category_label,
                markdown=markdown,
                sections_count=sections_count,
                total_citations=total_citations,
                generation_confidence=generation_confidence,
                all_gaps_json=json.dumps(all_gaps),
                source_count=source_count,
                unit_count=unit_count,
                source_details_json=json.dumps(source_details, ensure_ascii=False),
                related_concepts_json=json.dumps(related_concepts or [], ensure_ascii=False),
                resolution_method=resolution_method,
                resolution_confidence=resolution_confidence,
                importance_score=importance_score,
                importance_tier=importance_tier,
                now=now,
            )

        # Relation ABOUT vers les entités résolues
        if entity_ids:
            self._link_about(slug, tenant_id, entity_ids)

        logger.info(
            f"[OSMOSE:WikiPersister] Article '{slug}' persisté "
            f"(tier={importance_tier}, score={importance_score:.2f})"
        )
        return slug

    def _link_about(self, slug: str, tenant_id: str, entity_ids: List[str]) -> None:
        """Crée les relations ABOUT entre WikiArticle et les Entity résolues."""
        query = """
        MATCH (wa:WikiArticle {slug: $slug, tenant_id: $tenant_id})
        OPTIONAL MATCH (wa)-[old:ABOUT]->()
        DELETE old
        WITH wa
        UNWIND $entity_ids AS eid
        MATCH (e:Entity {entity_id: eid, tenant_id: $tenant_id})
        MERGE (wa)-[:ABOUT]->(e)
        """
        with self._driver.session() as session:
            session.run(query, slug=slug, tenant_id=tenant_id, entity_ids=entity_ids)

    # ── Linking ─────────────────────────────────────────────────────────────

    def update_linked_markdown(
        self,
        slug: str,
        tenant_id: str,
        linked_markdown: str,
        outgoing_links: List[str],
        linking_metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Met à jour uniquement le linked_markdown d'un article existant."""
        now = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(linking_metadata or {}, ensure_ascii=False)
        outgoing_json = json.dumps(outgoing_links, ensure_ascii=False)

        query = """
        MATCH (wa:WikiArticle {slug: $slug, tenant_id: $tenant_id})
        SET wa.linked_markdown = $linked_markdown,
            wa.outgoing_links = $outgoing_json,
            wa.linking_metadata = $metadata_json,
            wa.linked_at = $now
        RETURN wa.slug AS slug
        """

        with self._driver.session() as session:
            result = session.run(
                query,
                slug=slug,
                tenant_id=tenant_id,
                linked_markdown=linked_markdown,
                outgoing_json=outgoing_json,
                metadata_json=metadata_json,
                now=now,
            )
            record = result.single()
            if record:
                logger.info(
                    f"[OSMOSE:WikiPersister] linked_markdown mis à jour pour '{slug}' "
                    f"({len(outgoing_links)} liens sortants)"
                )
                return True
            return False

    # ── Read ──────────────────────────────────────────────────────────────

    def get_by_slug(self, slug: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Récupère un article complet par slug."""
        query = """
        MATCH (wa:WikiArticle {slug: $slug, tenant_id: $tenant_id})
        RETURN wa
        """
        with self._driver.session() as session:
            result = session.run(query, slug=slug, tenant_id=tenant_id)
            record = result.single()
            if not record:
                return None
            return self._article_to_dict(record["wa"])

    def list_articles(
        self,
        tenant_id: str,
        category: Optional[str] = None,
        search: Optional[str] = None,
        tier: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Liste les articles sans markdown (pour la page liste)."""
        conditions = ["wa.tenant_id = $tenant_id", "wa.status = 'published'"]
        params: Dict[str, Any] = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

        if category:
            conditions.append("wa.category_key = $category")
            params["category"] = category
        if tier:
            conditions.append("wa.importance_tier = $tier")
            params["tier"] = tier
        if search:
            conditions.append("toLower(wa.title) CONTAINS toLower($search)")
            params["search"] = search

        where_clause = " AND ".join(conditions)

        count_query = f"""
        MATCH (wa:WikiArticle)
        WHERE {where_clause}
        RETURN count(wa) AS total
        """

        list_query = f"""
        MATCH (wa:WikiArticle)
        WHERE {where_clause}
        RETURN wa
        ORDER BY wa.importance_score DESC, wa.updated_at DESC
        SKIP $offset LIMIT $limit
        """

        with self._driver.session() as session:
            total = session.run(count_query, **params).single()["total"]
            results = session.run(list_query, **params)
            articles = []
            for r in results:
                d = self._article_to_dict(r["wa"])
                d.pop("markdown", None)  # pas de markdown dans la liste
                articles.append(d)

        return {"articles": articles, "total": total, "limit": limit, "offset": offset}

    def get_categories(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Récupère les catégories avec le nombre d'articles."""
        query = """
        MATCH (wc:WikiCategory {tenant_id: $tenant_id})
        OPTIONAL MATCH (wa:WikiArticle {tenant_id: $tenant_id, status: 'published'})-[:IN_CATEGORY]->(wc)
        RETURN wc.category_key AS category_key,
               wc.label AS label,
               count(wa) AS article_count
        ORDER BY article_count DESC
        """
        with self._driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [
                {
                    "category_key": r["category_key"],
                    "label": r["label"],
                    "article_count": r["article_count"],
                }
                for r in result
            ]

    def get_home_data(self, tenant_id: str) -> Dict[str, Any]:
        """Données pour la homepage Atlas : stats, Tier 1, récents, gaps, blind spots, corpus narrative."""
        stats = self._get_corpus_stats(tenant_id)
        domains = self._get_knowledge_domains(tenant_id)
        recent = self._get_recent_articles(tenant_id, limit=5)
        tier1 = self._get_tier1_concepts(tenant_id)
        contradiction_count = self._get_contradiction_count(tenant_id)
        blind_spots = self._get_blind_spots(tenant_id)
        start_here = self._get_start_here(tenant_id)
        corpus_narrative = self._get_corpus_narrative(tenant_id)

        return {
            "corpus_stats": stats,
            "knowledge_domains": domains,
            "recent_articles": recent,
            "tier1_concepts": tier1,
            "contradiction_count": contradiction_count,
            "blind_spots": blind_spots,
            "start_here": start_here,
            "corpus_narrative": corpus_narrative,
        }

    def get_article_claims(
        self, slug: str, tenant_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Récupère les claims liés à l'entité source d'un article (drill-down)."""
        query = """
        MATCH (wa:WikiArticle {slug: $slug, tenant_id: $tenant_id})-[:ABOUT]->(e:Entity)
        MATCH (c:Claim)-[:ABOUT]->(e)
        WHERE c.tenant_id = $tenant_id
        OPTIONAL MATCH (c)-[:EXTRACTED_FROM]->(ep)
        RETURN c.claim_id AS claim_id,
               c.subject_text AS subject_text,
               c.predicate AS predicate,
               c.object_text AS object_text,
               c.claim_type AS claim_type,
               c.confidence AS confidence,
               c.doc_id AS doc_id,
               ep.title AS source_title
        ORDER BY c.confidence DESC
        LIMIT $limit
        """
        with self._driver.session() as session:
            result = session.run(query, slug=slug, tenant_id=tenant_id, limit=limit)
            claims = []
            for r in result:
                text = f"{r['subject_text'] or ''} {r['predicate'] or ''} {r['object_text'] or ''}".strip()
                claims.append(
                    {
                        "claim_id": r["claim_id"],
                        "text": text,
                        "claim_type": r["claim_type"] or "FACTUAL",
                        "confidence": r["confidence"] or 0.0,
                        "doc_id": r["doc_id"],
                        "source_title": r["source_title"] or "",
                    }
                )
            return claims

    def delete_article(self, slug: str, tenant_id: str) -> bool:
        """Supprime un article et ses relations."""
        query = """
        MATCH (wa:WikiArticle {slug: $slug, tenant_id: $tenant_id})
        DETACH DELETE wa
        RETURN count(*) AS deleted
        """
        with self._driver.session() as session:
            result = session.run(query, slug=slug, tenant_id=tenant_id)
            deleted = result.single()["deleted"]
            if deleted > 0:
                logger.info(f"[OSMOSE:WikiPersister] Article '{slug}' supprimé")
                return True
            return False

    # ── Helpers privés ─────────────────────────────────────────────────────

    def _get_corpus_stats(self, tenant_id: str) -> Dict[str, Any]:
        query = """
        OPTIONAL MATCH (c:Claim {tenant_id: $tenant_id})
        WITH count(DISTINCT c) AS total_claims, count(DISTINCT c.doc_id) AS total_documents
        OPTIONAL MATCH (e:Entity {tenant_id: $tenant_id})
        WITH total_documents, total_claims, count(DISTINCT e) AS total_entities
        OPTIONAL MATCH (wa:WikiArticle {tenant_id: $tenant_id, status: 'published'})
        WITH total_documents, total_claims, total_entities, count(DISTINCT wa) AS total_articles
        RETURN total_documents, total_claims, total_entities, total_articles
        """
        with self._driver.session() as session:
            r = session.run(query, tenant_id=tenant_id).single()
            total_entities = r["total_entities"]
            total_articles = r["total_articles"]
            coverage_pct = round(
                (total_articles / total_entities * 100) if total_entities > 0 else 0, 1
            )
            return {
                "total_documents": r["total_documents"],
                "total_claims": r["total_claims"],
                "total_entities": total_entities,
                "total_articles": total_articles,
                "coverage_pct": coverage_pct,
            }

    def _get_tier1_concepts(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Tier 1 concepts : depuis WikiArticle (tier=1) + Entity sans article (top scorés)."""
        query = """
        MATCH (wa:WikiArticle {tenant_id: $tenant_id, importance_tier: 1, status: 'published'})
        RETURN wa.slug AS slug,
               wa.title AS name,
               wa.entity_type AS entity_type,
               wa.importance_score AS importance_score,
               true AS has_article
        ORDER BY wa.importance_score DESC
        LIMIT 12
        """
        with self._driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [
                {
                    "name": r["name"],
                    "entity_type": r["entity_type"],
                    "importance_score": r["importance_score"],
                    "has_article": r["has_article"],
                    "slug": r["slug"],
                }
                for r in result
            ]

    def _get_recent_articles(self, tenant_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        query = """
        MATCH (wa:WikiArticle {tenant_id: $tenant_id, status: 'published'})
        RETURN wa.slug AS slug,
               wa.title AS title,
               wa.entity_type AS entity_type,
               wa.category_key AS category_key,
               wa.importance_tier AS importance_tier,
               wa.generation_confidence AS generation_confidence,
               wa.updated_at AS updated_at
        ORDER BY wa.updated_at DESC
        LIMIT $limit
        """
        with self._driver.session() as session:
            result = session.run(query, tenant_id=tenant_id, limit=limit)
            return [dict(r) for r in result]

    def _get_knowledge_domains(self, tenant_id: str) -> List[Dict[str, Any]]:
        """
        Construit la structure des domaines de connaissance pour la homepage Atlas.

        Chaque domaine racine (Compliance, Security, etc.) contient :
        - Ses sous-domaines
        - Les articles liés (via WikiArticle→Entity←Claim→Facet)
        - Le nombre de claims
        - La question canonique
        """
        # 1. Récupérer les domaines racines
        root_query = """
        MATCH (f:Facet {tenant_id: $tenant_id, facet_kind: 'domain'})
        WHERE f.domain = f.domain_root
        RETURN f.facet_name AS name, f.domain AS domain_key,
               f.canonical_question AS question, f.source_doc_count AS doc_count
        ORDER BY f.source_doc_count DESC
        """

        # 2. Récupérer les sous-domaines
        sub_query = """
        MATCH (f:Facet {tenant_id: $tenant_id, facet_kind: 'domain'})
        WHERE f.domain <> f.domain_root
        RETURN f.domain_root AS root, f.facet_name AS name, f.domain AS domain_key
        ORDER BY f.domain_root
        """

        # 3. Articles par domaine racine (via le chemin WikiArticle→Entity←Claim→Facet)
        articles_query = """
        MATCH (wa:WikiArticle {tenant_id: $tenant_id, status: 'published'})
              -[:ABOUT]->(e:Entity)<-[:ABOUT]-(c:Claim)-[:HAS_FACET]->(f:Facet)
        WHERE f.facet_kind = 'domain' AND f.domain = f.domain_root
        WITH f.domain AS domain_key, wa.slug AS slug, wa.title AS title,
             wa.importance_tier AS tier, count(DISTINCT c) AS relevance
        ORDER BY domain_key, relevance DESC
        RETURN domain_key, collect({slug: slug, title: title, tier: tier})[..8] AS articles,
               count(DISTINCT slug) AS article_count
        """

        with self._driver.session() as session:
            # Domaines racines
            roots_result = session.run(root_query, tenant_id=tenant_id)
            roots = {}
            for r in roots_result:
                roots[r["domain_key"]] = {
                    "name": r["name"],
                    "domain_key": r["domain_key"],
                    "question": r["question"],
                    "doc_count": r["doc_count"] or 0,
                    "sub_domains": [],
                    "articles": [],
                    "article_count": 0,
                }

            # Sous-domaines
            subs_result = session.run(sub_query, tenant_id=tenant_id)
            for r in subs_result:
                root_key = r["root"]
                if root_key in roots:
                    # Extraire le nom court du sous-domaine ("Compliance / Gdpr" → "GDPR")
                    name = r["name"]
                    short = name.split("/")[-1].strip() if "/" in name else name
                    roots[root_key]["sub_domains"].append(short)

            # Articles liés
            articles_result = session.run(articles_query, tenant_id=tenant_id)
            for r in articles_result:
                key = r["domain_key"]
                if key in roots:
                    roots[key]["articles"] = r["articles"]
                    roots[key]["article_count"] = r["article_count"]

        # Trier par article_count desc, ne garder que les domaines avec du contenu
        domains = sorted(roots.values(), key=lambda d: d["article_count"], reverse=True)
        return domains

    def get_domain_data(self, facet_key: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Données complètes pour une page facette/domaine.

        Retourne: info facette, top concepts, articles, documents contributeurs,
        stats, gaps, questions fréquentes, blind spots locaux.
        """
        with self._driver.session() as session:
            # 1. Info facette
            facet_result = session.run(
                """
                MATCH (f:Facet {tenant_id: $tid})
                WHERE f.facet_id = $fkey OR f.facet_name = $fkey OR f.domain = $fkey
                RETURN f.facet_id AS facet_id, f.facet_name AS name,
                       f.facet_kind AS kind, f.lifecycle AS lifecycle,
                       f.source_doc_count AS doc_count,
                       f.canonical_question AS question,
                       f.domain AS domain_key
                LIMIT 1
                """,
                tid=tenant_id, fkey=facet_key,
            ).single()

            if not facet_result:
                return None

            facet_id = facet_result["facet_id"]
            domain_key = facet_result["domain_key"] or facet_key

            # 2. Top 10 concepts du domaine
            concepts_result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tid})-[:HAS_FACET]->(f:Facet {facet_id: $fid}),
                      (c)-[:ABOUT]->(e:Entity)
                WITH e, count(DISTINCT c) AS claim_count, count(DISTINCT c.doc_id) AS doc_count
                OPTIONAL MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e)
                RETURN e.name AS name, e.entity_type AS entity_type,
                       claim_count, doc_count,
                       wa.slug AS article_slug, wa.title AS article_title,
                       wa.importance_tier AS tier
                ORDER BY claim_count DESC LIMIT 10
                """,
                tid=tenant_id, fid=facet_id,
            )
            top_concepts = [
                {
                    "name": r["name"],
                    "entity_type": r["entity_type"] or "concept",
                    "claim_count": r["claim_count"],
                    "doc_count": r["doc_count"],
                    "article_slug": r["article_slug"],
                    "article_title": r["article_title"],
                    "tier": r["tier"],
                }
                for r in concepts_result
            ]

            # 3. Articles du domaine
            articles_result = session.run(
                """
                MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e:Entity),
                      (c:Claim {tenant_id: $tid})-[:ABOUT]->(e), (c)-[:HAS_FACET]->(f:Facet {facet_id: $fid})
                WITH wa, count(DISTINCT c) AS relevance
                RETURN wa.slug AS slug, wa.title AS title,
                       wa.importance_tier AS importance_tier,
                       wa.importance_score AS importance_score,
                       wa.generation_confidence AS confidence,
                       relevance
                ORDER BY relevance DESC LIMIT 20
                """,
                tid=tenant_id, fid=facet_id,
            )
            articles = [
                {
                    "slug": r["slug"],
                    "title": r["title"],
                    "importance_tier": r["importance_tier"] or 3,
                    "importance_score": r["importance_score"] or 0,
                    "confidence": r["confidence"] or 0,
                    "relevance": r["relevance"],
                }
                for r in articles_result
            ]

            # 4. Documents contributeurs
            docs_result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tid})-[:HAS_FACET]->(f:Facet {facet_id: $fid})
                WITH c.doc_id AS doc_id, count(c) AS claim_count
                RETURN doc_id, claim_count
                ORDER BY claim_count DESC LIMIT 10
                """,
                tid=tenant_id, fid=facet_id,
            )
            documents = [
                {"doc_id": r["doc_id"], "claim_count": r["claim_count"]}
                for r in docs_result
            ]

            # 5. Stats du domaine
            stats_result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tid})-[:HAS_FACET]->(f:Facet {facet_id: $fid})
                WITH count(c) AS total_claims, count(DISTINCT c.doc_id) AS doc_count
                RETURN total_claims, doc_count
                """,
                tid=tenant_id, fid=facet_id,
            ).single()

            contradiction_result = session.run(
                """
                MATCH (c1:Claim {tenant_id: $tid})-[:HAS_FACET]->(f:Facet {facet_id: $fid}),
                      (c1)-[:CONTRADICTS]-(c2:Claim)
                RETURN count(DISTINCT c1) AS cnt
                """,
                tid=tenant_id, fid=facet_id,
            ).single()

            # 6. Gaps — concepts sans article
            gaps_result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tid})-[:HAS_FACET]->(f:Facet {facet_id: $fid}),
                      (c)-[:ABOUT]->(e:Entity)
                WHERE NOT exists {
                    MATCH (wa:WikiArticle {tenant_id: $tid})-[:ABOUT]->(e)
                }
                WITH e, count(DISTINCT c) AS claim_count
                WHERE claim_count >= 3
                RETURN e.name AS name, e.entity_type AS entity_type, claim_count
                ORDER BY claim_count DESC LIMIT 5
                """,
                tid=tenant_id, fid=facet_id,
            )
            gaps = [
                {"name": r["name"], "entity_type": r["entity_type"] or "concept", "claim_count": r["claim_count"]}
                for r in gaps_result
            ]

            # 7. Questions fréquentes — top concepts → questions-types
            suggested_questions = []
            for c in top_concepts[:5]:
                name = c["name"]
                suggested_questions.append({
                    "question": f"Que sait le corpus sur {name} ?",
                    "concept": name,
                })
            # Si contradictions, ajouter une question contradiction
            contra_count = contradiction_result["cnt"] if contradiction_result else 0
            if contra_count > 0 and top_concepts:
                top_name = top_concepts[0]["name"]
                suggested_questions.append({
                    "question": f"Quelles sont les contradictions concernant {top_name} ?",
                    "concept": top_name,
                })

            return {
                "facet_id": facet_id,
                "name": facet_result["name"],
                "kind": facet_result["kind"] or "domain",
                "lifecycle": facet_result["lifecycle"] or "validated",
                "doc_count": facet_result["doc_count"] or 0,
                "question": facet_result["question"] or "",
                "domain_key": domain_key,
                "top_concepts": top_concepts,
                "articles": articles,
                "documents": documents,
                "stats": {
                    "total_claims": stats_result["total_claims"] if stats_result else 0,
                    "doc_count": stats_result["doc_count"] if stats_result else 0,
                    "contradiction_count": contra_count,
                    "article_count": len(articles),
                    "gap_count": len(gaps),
                },
                "gaps": gaps,
                "suggested_questions": suggested_questions[:6],
            }

    def _get_corpus_narrative(self, tenant_id: str) -> Dict[str, Any]:
        """Données structurées pour le récit du corpus (pas de texte LLM)."""
        narrative: Dict[str, Any] = {
            "top_entity_types": [],
            "top_entities": [],
            "doc_type_distribution": [],
            "entity_count_with_articles": 0,
            "entity_count_without_articles": 0,
        }

        # Charger la stoplist depuis les domain packs actifs (domain-specific, pas hardcodé)
        entity_stoplist: set = set()
        try:
            from knowbase.domain_packs.registry import get_pack_registry

            registry = get_pack_registry()
            for pack in registry.get_active_packs(tenant_id):
                pack_stoplist = pack.get_entity_stoplist()
                entity_stoplist.update(s.lower() for s in pack_stoplist if isinstance(s, str))
        except Exception as e:
            logger.debug(f"[ATLAS:Narrative] Could not load pack entity stoplist: {e}")

        with self._driver.session() as session:
            # Top entity_types par nombre de claims
            try:
                result = session.run(
                    """
                    MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim {tenant_id: $tid})
                    WITH e.entity_type AS etype, count(DISTINCT c) AS cnt
                    WHERE etype IS NOT NULL
                    RETURN etype AS type, cnt AS count
                    ORDER BY cnt DESC LIMIT 5
                    """,
                    tid=tenant_id,
                )
                narrative["top_entity_types"] = [
                    {"type": r["type"], "count": r["count"]} for r in result
                ]
            except Exception as e:
                logger.debug(f"[ATLAS:Narrative] top_entity_types failed: {e}")

            # Top 10 entités par claim_count
            # Filtres : pas d'actors/other, nom 4-60 chars, pas supprimé, dedup par canonical
            try:
                result = session.run(
                    """
                    MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim {tenant_id: $tid})
                    WHERE NOT e.entity_type IN ['actor', 'other']
                      AND size(e.name) >= 4
                      AND size(e.name) <= 60
                      AND e._hygiene_status IS NULL
                    WITH e, count(DISTINCT c) AS claim_count
                    OPTIONAL MATCH (e)-[:SAME_CANON_AS]->(ce:CanonicalEntity)
                    WITH coalesce(ce.canonical_entity_id, e.entity_id) AS group_key,
                         e, claim_count
                    ORDER BY claim_count DESC
                    WITH group_key, head(collect(e)) AS best_entity,
                         sum(claim_count) AS total_claims
                    ORDER BY total_claims DESC LIMIT 20
                    OPTIONAL MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(best_entity)
                    RETURN best_entity.name AS name, total_claims AS claim_count,
                           wa.slug IS NOT NULL AS has_article,
                           wa.slug AS slug
                    ORDER BY total_claims DESC
                    """,
                    tid=tenant_id,
                )
                filtered = []
                for r in result:
                    name = r["name"]
                    # Exclure les termes de la stoplist du domain context
                    if name.lower() in entity_stoplist:
                        continue
                    # Exclure les phrases trop longues (> 4 mots) — heuristique agnostique
                    if len(name.split()) > 4:
                        continue
                    filtered.append({
                        "name": name,
                        "claim_count": r["claim_count"],
                        "has_article": bool(r["has_article"]),
                        "slug": r["slug"],
                    })
                narrative["top_entities"] = filtered[:10]
            except Exception as e:
                logger.debug(f"[ATLAS:Narrative] top_entities failed: {e}")

            # Distribution des doc_types
            try:
                result = session.run(
                    """
                    MATCH (c:Claim {tenant_id: $tid})-[:EXTRACTED_FROM]->(ep)
                    WHERE ep.doc_type IS NOT NULL
                    WITH ep.doc_type AS dtype, count(DISTINCT ep) AS cnt
                    RETURN dtype AS type, cnt AS count
                    ORDER BY cnt DESC LIMIT 8
                    """,
                    tid=tenant_id,
                )
                narrative["doc_type_distribution"] = [
                    {"type": r["type"], "count": r["count"]} for r in result
                ]
            except Exception as e:
                logger.debug(f"[ATLAS:Narrative] doc_type_distribution failed: {e}")

            # Compteurs entités avec/sans article
            try:
                result = session.run(
                    """
                    MATCH (e:Entity {tenant_id: $tid})
                    OPTIONAL MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e)
                    WITH e, wa IS NOT NULL AS has_article
                    RETURN has_article, count(e) AS cnt
                    """,
                    tid=tenant_id,
                )
                for r in result:
                    if r["has_article"]:
                        narrative["entity_count_with_articles"] = r["cnt"]
                    else:
                        narrative["entity_count_without_articles"] = r["cnt"]
            except Exception as e:
                logger.debug(f"[ATLAS:Narrative] entity counts failed: {e}")

        return narrative

    def _get_contradiction_count(self, tenant_id: str) -> int:
        """Nombre total de contradictions détectées dans le corpus."""
        query = """
        MATCH (c1:Claim {tenant_id: $tid})-[r:CONTRADICTS]-(c2:Claim)
        RETURN count(r) / 2 AS total
        """
        with self._driver.session() as session:
            r = session.run(query, tid=tenant_id).single()
            return r["total"] if r else 0

    def _get_blind_spots(self, tenant_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Zones à surveiller : contradictions élevées, couverture faible, concepts sans article."""
        spots: List[Dict[str, Any]] = []

        with self._driver.session() as session:
            # 1. Facettes avec contradictions — séparées par type
            try:
                result = session.run(
                    """
                    MATCH (c1:Claim {tenant_id: $tid})-[:HAS_FACET]->(f:Facet),
                          (c1)-[r:CONTRADICTS]-(c2:Claim)
                    WHERE r.tension_level IS NULL OR r.tension_level <> 'none'
                    WITH f.facet_name AS domain,
                         r.tension_nature AS nature,
                         count(DISTINCT c1) AS cnt
                    WHERE cnt >= 2
                    RETURN domain, nature, cnt
                    ORDER BY cnt DESC LIMIT 6
                    """,
                    tid=tenant_id,
                )
                for r in result:
                    nature = r["nature"]
                    if nature == "value_conflict":
                        spots.append({
                            "type": "value_contradiction",
                            "domain": r["domain"],
                            "detail": f"{r['cnt']} vraies contradictions de valeur",
                            "severity": "warning",
                        })
                    elif nature == "scope_conflict":
                        spots.append({
                            "type": "scope_variation",
                            "domain": r["domain"],
                            "detail": f"{r['cnt']} variations contextuelles",
                            "severity": "info",
                        })
                    elif nature is None:
                        # Non classifiées → traiter comme avant
                        spots.append({
                            "type": "high_contradictions",
                            "domain": r["domain"],
                            "detail": f"{r['cnt']} claims en contradiction (non classifiées)",
                            "severity": "warning",
                        })
            except Exception as e:
                logger.debug(f"[ATLAS:BlindSpots] Contradictions query failed: {e}")

            # 2. Facettes avec couverture faible (< 3 documents)
            try:
                result = session.run(
                    """
                    MATCH (f:Facet {tenant_id: $tid, lifecycle: 'validated'})
                    WHERE f.source_doc_count IS NOT NULL AND f.source_doc_count < 3
                    RETURN f.facet_name AS domain, f.source_doc_count AS doc_count
                    ORDER BY f.source_doc_count ASC LIMIT 2
                    """,
                    tid=tenant_id,
                )
                for r in result:
                    spots.append({
                        "type": "low_coverage",
                        "domain": r["domain"],
                        "detail": f"Seulement {r['doc_count']} document{'s' if r['doc_count'] != 1 else ''}",
                        "severity": "warning",
                    })
            except Exception as e:
                logger.debug(f"[ATLAS:BlindSpots] Low coverage query failed: {e}")

            # 3. Concepts importants sans article (top 3 par claim_count)
            #    Filtre : exclure entity_type trop génériques, noms < 4 chars, et mono-document
            try:
                result = session.run(
                    """
                    MATCH (e:Entity {tenant_id: $tid})
                    WHERE NOT exists {
                        MATCH (wa:WikiArticle {tenant_id: $tid})-[:ABOUT]->(e)
                    }
                    AND NOT e.entity_type IN ['actor', 'other']
                    AND size(e.name) >= 4
                    OPTIONAL MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e)
                    WITH e, count(DISTINCT c) AS claim_count, count(DISTINCT c.doc_id) AS doc_count
                    WHERE claim_count >= 5 AND doc_count >= 2
                    RETURN e.name AS name, claim_count
                    ORDER BY claim_count DESC LIMIT 10
                    """,
                    tid=tenant_id,
                )
                # Charger la stoplist du domain pack pour filtrer les termes génériques
                bs_stoplist: set = set()
                try:
                    from knowbase.domain_packs.registry import get_pack_registry as _get_registry
                    for pack in _get_registry().get_active_packs(tenant_id):
                        bs_stoplist.update(s.lower() for s in pack.get_entity_stoplist() if isinstance(s, str))
                except Exception:
                    pass

                for r in result:
                    name = r["name"]
                    if name.lower() in bs_stoplist:
                        continue
                    if len(name.split()) > 4:
                        continue
                    spots.append({
                        "type": "missing_article",
                        "domain": name,
                        "detail": f"{r['claim_count']} claims mais pas d'article",
                        "severity": "info",
                    })
            except Exception as e:
                logger.debug(f"[ATLAS:BlindSpots] Missing articles query failed: {e}")

        # Trier : contradictions d'abord, puis variations, puis couverture, puis missing
        priority = {
            "value_contradiction": 0,
            "high_contradictions": 1,
            "scope_variation": 2,
            "low_coverage": 3,
            "missing_article": 4,
        }
        spots.sort(key=lambda s: priority.get(s["type"], 9))
        return spots[:limit]

    def _get_start_here(self, tenant_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Articles Tier 1 publiés — points d'entrée recommandés."""
        query = """
        MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})
        WHERE wa.importance_tier = 1
        RETURN wa.slug AS slug, wa.title AS title, wa.importance_score AS importance_score
        ORDER BY wa.importance_score DESC
        LIMIT $limit
        """
        with self._driver.session() as session:
            result = session.run(query, tid=tenant_id, limit=limit)
            return [
                {
                    "slug": r["slug"],
                    "title": r["title"],
                    "importance_score": r["importance_score"] or 0.0,
                }
                for r in result
            ]

    def get_reading_path(self, slug: str, tenant_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Reading path — parcours de lecture recommandé pour un article.

        Trouve les articles publiés qui partagent des entités avec l'article courant,
        triés par tier (généraux d'abord) puis importance_score.
        """
        query = """
        MATCH (wa:WikiArticle {slug: $slug, tenant_id: $tid})-[:ABOUT]->(e:Entity),
              (c:Claim {tenant_id: $tid})-[:ABOUT]->(e), (c)-[:ABOUT]->(e2:Entity),
              (wa2:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e2)
        WHERE wa2 <> wa
        WITH wa2, e2, count(DISTINCT c) AS co_occurrence
        ORDER BY wa2.importance_tier ASC, wa2.importance_score DESC, co_occurrence DESC
        WITH wa2, collect(e2.name)[0] AS concept_name
        RETURN DISTINCT wa2.slug AS slug, wa2.title AS title,
               wa2.importance_tier AS importance_tier, concept_name
        LIMIT $limit
        """
        with self._driver.session() as session:
            result = session.run(query, slug=slug, tid=tenant_id, limit=limit)
            return [
                {
                    "slug": r["slug"],
                    "title": r["title"],
                    "importance_tier": r["importance_tier"] or 3,
                    "concept_name": r["concept_name"] or "",
                }
                for r in result
            ]

    def get_linked_articles(self, slug: str, tenant_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Articles liés — voisinage sémantique via entités partagées.
        """
        query = """
        MATCH (wa:WikiArticle {slug: $slug, tenant_id: $tid})-[:ABOUT]->(e:Entity),
              (c:Claim {tenant_id: $tid})-[:ABOUT]->(e),
              (c)-[:ABOUT]->(e2:Entity),
              (wa2:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e2)
        WHERE wa2 <> wa
        WITH wa2, count(DISTINCT e2) AS shared_concepts
        ORDER BY shared_concepts DESC
        RETURN wa2.slug AS slug, wa2.title AS title,
               wa2.importance_tier AS importance_tier, shared_concepts
        LIMIT $limit
        """
        with self._driver.session() as session:
            result = session.run(query, slug=slug, tid=tenant_id, limit=limit)
            return [
                {
                    "slug": r["slug"],
                    "title": r["title"],
                    "importance_tier": r["importance_tier"] or 3,
                    "shared_concepts": r["shared_concepts"],
                }
                for r in result
            ]

    def _get_missing_articles(self, tenant_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Knowledge gaps = concepts d'importance significative sans article persisté.
        Tier 1 ou Tier 2 uniquement.
        """
        # Concepts avec beaucoup de claims mais sans WikiArticle
        query = """
        MATCH (e:Entity {tenant_id: $tenant_id})
        WHERE NOT exists {
            MATCH (wa:WikiArticle {tenant_id: $tenant_id})-[:ABOUT]->(e)
        }
        OPTIONAL MATCH (c:Claim)-[:ABOUT]->(e)
        WHERE c.tenant_id = $tenant_id
        WITH e, count(DISTINCT c) AS claim_count, count(DISTINCT c.doc_id) AS doc_count
        WHERE claim_count >= 3
        RETURN e.name AS name,
               e.entity_type AS entity_type,
               claim_count,
               doc_count
        ORDER BY claim_count DESC
        LIMIT $limit
        """
        with self._driver.session() as session:
            result = session.run(query, tenant_id=tenant_id, limit=limit)
            return [
                {
                    "name": r["name"],
                    "entity_type": r["entity_type"],
                    "claim_count": r["claim_count"],
                    "doc_count": r["doc_count"],
                    "has_article": False,
                }
                for r in result
            ]

    def enrich_related_from_markdown(
        self,
        markdown: str,
        existing_related: List[Dict[str, Any]],
        concept_name: str,
        tenant_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Enrichit related_concepts en scannant le markdown pour trouver
        des entités Neo4j mentionnées mais absentes de la liste co-occurrence.

        Stratégie :
        1. Récupérer les entités avec >= 3 claims (significatives)
        2. Chercher leur nom dans le markdown (case-insensitive, mot entier)
        3. Ajouter celles trouvées qui ne sont pas déjà dans existing_related
        """
        existing_names = {r["entity_name"].lower() for r in existing_related}
        existing_names.add(concept_name.lower())  # exclure le concept lui-même

        # Récupérer les entités significatives du tenant
        query = """
        MATCH (e:Entity {tenant_id: $tenant_id})
        WHERE e.name IS NOT NULL AND size(e.name) >= 3
        OPTIONAL MATCH (c:Claim)-[:ABOUT]->(e)
        WHERE c.tenant_id = $tenant_id
        WITH e.name AS name, e.entity_type AS etype, count(c) AS claim_count
        WHERE claim_count >= 3
        RETURN name, etype, claim_count
        ORDER BY claim_count DESC
        LIMIT 200
        """

        candidates: List[Dict[str, Any]] = []
        md_lower = markdown.lower()

        with self._driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            for r in result:
                name = r["name"]
                if name.lower() in existing_names:
                    continue
                # Chercher le nom comme mot entier dans le markdown
                pattern = re.compile(
                    r'\b' + re.escape(name) + r'\b',
                    re.IGNORECASE,
                )
                if pattern.search(markdown):
                    candidates.append({
                        "entity_name": name,
                        "entity_type": r["etype"] or "concept",
                        "co_occurrence_count": 0,  # trouvé par mention textuelle
                    })
                    existing_names.add(name.lower())

        # Fusionner : co-occurrence d'abord, puis mentions textuelles
        enriched = list(existing_related) + candidates
        # Plafonner à 12 pour ne pas surcharger le graph
        return enriched[:12]

    def _article_to_dict(self, node) -> Dict[str, Any]:
        """Convertit un nœud Neo4j WikiArticle en dict."""
        props = dict(node)
        # Désérialiser les champs JSON
        for json_field in ("all_gaps", "source_details", "related_concepts", "outgoing_links"):
            if json_field in props and isinstance(props[json_field], str):
                try:
                    props[json_field] = json.loads(props[json_field])
                except (json.JSONDecodeError, TypeError):
                    props[json_field] = []
        # Désérialiser linking_metadata (dict)
        if "linking_metadata" in props and isinstance(props["linking_metadata"], str):
            try:
                props["linking_metadata"] = json.loads(props["linking_metadata"])
            except (json.JSONDecodeError, TypeError):
                props["linking_metadata"] = {}
        return props
