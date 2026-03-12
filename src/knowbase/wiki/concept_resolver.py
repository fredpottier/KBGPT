"""
ConceptResolver — Résolution d'un nom de concept en ResolvedConcept via Neo4j.

Stratégie en 4 niveaux :
  1. Exact match (confidence 1.0)
  2. CanonicalEntity match via SAME_CANON_AS (confidence 0.95)
  3. Alias match — table statique POC (confidence 0.85)
  4. Fuzzy CONTAINS match (confidence 0.5-0.7)

Après chaque match, expansion canonique :
  Entity trouvée → CanonicalEntity (via SAME_CANON_AS) → toutes les variantes liées.
  Cela résout le problème de canonicalisation : "S/4HANA" ramène aussi
  "SAP S/4HANA", "S/4HANA Cloud Private Edition", etc.

Garde-fous :
  - Fuzzy > 5 entités → ambiguity_notes, confidence plafonnée à 0.5
  - Aucun match → erreur explicite (pas de pack vide silencieux)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from knowbase.wiki.models import ResolvedConcept

logger = logging.getLogger(__name__)

# Table d'alias statique pour le POC
KNOWN_ALIASES: Dict[str, List[str]] = {
    "EDPB": ["European Data Protection Board", "edpb"],
    "controller": ["data controller", "controllers"],
    "DPA": ["Data Protection Authority", "Data Protection Authorities", "DPAs"],
    "GDPR": ["General Data Protection Regulation", "gdpr"],
}


class ConceptResolver:
    """Résout un nom de concept en ResolvedConcept via requêtes Cypher."""

    def __init__(self, neo4j_driver):
        self._driver = neo4j_driver

    def resolve(self, concept_name: str, tenant_id: str = "default") -> ResolvedConcept:
        """
        Résout un concept par nom exact + canonical + alias + fuzzy matching.

        Raises:
            ValueError: si aucun match trouvé à aucun niveau.
        """
        logger.info(f"[OSMOSE:ConceptResolver] Résolution de '{concept_name}' (tenant={tenant_id})")

        # Niveau 1 : Exact match sur Entity.name
        entities = self._find_exact(concept_name, tenant_id)
        if entities:
            expanded = self._expand_canonical(entities, tenant_id)
            method = "exact+canon" if len(expanded) > len(entities) else "exact"
            logger.info(
                f"[OSMOSE:ConceptResolver] Match exact : {len(entities)} entité(s)"
                f" → {len(expanded)} après expansion canonique"
            )
            return self._build_resolved(expanded, concept_name, tenant_id, method, 1.0)

        # Niveau 2 : Match via CanonicalEntity.canonical_name
        entities = self._find_via_canonical(concept_name, tenant_id)
        if entities:
            logger.info(
                f"[OSMOSE:ConceptResolver] Match CanonicalEntity : {len(entities)} entité(s)"
            )
            return self._build_resolved(entities, concept_name, tenant_id, "canonical", 0.95)

        # Niveau 3 : Alias match (table statique POC)
        alias_names = self._get_aliases(concept_name)
        if alias_names:
            entities = self._find_by_names(alias_names, tenant_id)
            if entities:
                expanded = self._expand_canonical(entities, tenant_id)
                method = "alias+canon" if len(expanded) > len(entities) else "alias"
                logger.info(
                    f"[OSMOSE:ConceptResolver] Match alias : {len(entities)} entité(s)"
                    f" → {len(expanded)} après expansion canonique"
                )
                return self._build_resolved(expanded, concept_name, tenant_id, method, 0.85)

        # Niveau 4 : Fuzzy CONTAINS
        entities = self._find_fuzzy(concept_name, tenant_id)
        if entities:
            expanded = self._expand_canonical(entities, tenant_id)
            confidence = 0.7 if len(entities) <= 3 else 0.5
            ambiguity = []
            if len(entities) > 5:
                confidence = 0.5
                names = [e["name"] for e in entities[:10]]
                ambiguity.append(f"{len(entities)} entities matched fuzzy: {names}")
                logger.warning(
                    f"[OSMOSE:ConceptResolver] Fuzzy ambigu : {len(entities)} entités"
                )
            else:
                logger.info(
                    f"[OSMOSE:ConceptResolver] Match fuzzy : {len(entities)} entité(s)"
                    f" → {len(expanded)} après expansion canonique"
                )
            return self._build_resolved(
                expanded, concept_name, tenant_id, "fuzzy", confidence, ambiguity
            )

        raise ValueError(
            f"[OSMOSE:ConceptResolver] Aucune entité trouvée pour '{concept_name}' "
            f"(tenant={tenant_id}). Exact, canonical, alias et fuzzy ont échoué."
        )

    # ── Recherche ────────────────────────────────────────────────────────

    def _find_exact(self, name: str, tenant_id: str) -> List[dict]:
        """Recherche par nom exact (case-insensitive) sur Entity."""
        query = """
        MATCH (e:Entity)
        WHERE toLower(e.name) = toLower($name) AND e.tenant_id = $tenant_id
        RETURN e.entity_id AS entity_id, e.name AS name, e.entity_type AS entity_type,
               e.aliases AS aliases
        """
        with self._driver.session() as session:
            result = session.run(query, name=name, tenant_id=tenant_id)
            return [dict(r) for r in result]

    def _find_via_canonical(self, name: str, tenant_id: str) -> List[dict]:
        """
        Recherche via CanonicalEntity.canonical_name, puis redescend vers
        toutes les Entity liées par SAME_CANON_AS.
        """
        query = """
        MATCH (e:Entity)-[:SAME_CANON_AS]->(ce:CanonicalEntity)
        WHERE toLower(ce.canonical_name) = toLower($name)
              AND e.tenant_id = $tenant_id
        RETURN e.entity_id AS entity_id, e.name AS name, e.entity_type AS entity_type,
               e.aliases AS aliases, ce.canonical_name AS canon_name
        """
        with self._driver.session() as session:
            result = session.run(query, name=name, tenant_id=tenant_id)
            return [dict(r) for r in result]

    def _find_by_names(self, names: List[str], tenant_id: str) -> List[dict]:
        """Recherche par liste de noms (alias)."""
        lower_names = [n.lower() for n in names]
        query = """
        MATCH (e:Entity)
        WHERE toLower(e.name) IN $names AND e.tenant_id = $tenant_id
        RETURN e.entity_id AS entity_id, e.name AS name, e.entity_type AS entity_type,
               e.aliases AS aliases
        """
        with self._driver.session() as session:
            result = session.run(query, names=lower_names, tenant_id=tenant_id)
            return [dict(r) for r in result]

    def _find_fuzzy(self, name: str, tenant_id: str) -> List[dict]:
        """Recherche fuzzy CONTAINS, triée par nombre de claims associés."""
        query = """
        MATCH (e:Entity)
        WHERE toLower(e.name) CONTAINS toLower($name) AND e.tenant_id = $tenant_id
        OPTIONAL MATCH (c:Claim)-[:ABOUT]->(e)
        WITH e, count(c) AS claim_count
        ORDER BY claim_count DESC
        RETURN e.entity_id AS entity_id, e.name AS name, e.entity_type AS entity_type,
               e.aliases AS aliases, claim_count
        """
        with self._driver.session() as session:
            result = session.run(query, name=name, tenant_id=tenant_id)
            return [dict(r) for r in result]

    # ── Expansion canonique ──────────────────────────────────────────────

    def _expand_canonical(self, entities: List[dict], tenant_id: str) -> List[dict]:
        """
        Expansion via SAME_CANON_AS : pour chaque entité trouvée, remonte
        au CanonicalEntity puis redescend vers toutes les variantes.

        Les entités orphelines (sans SAME_CANON_AS) sont conservées telles quelles.
        """
        entity_ids = [e["entity_id"] for e in entities]
        if not entity_ids:
            return entities

        query = """
        MATCH (seed:Entity)-[:SAME_CANON_AS]->(ce:CanonicalEntity)<-[:SAME_CANON_AS]-(sibling:Entity)
        WHERE seed.entity_id IN $entity_ids AND sibling.tenant_id = $tenant_id
        RETURN DISTINCT sibling.entity_id AS entity_id, sibling.name AS name,
               sibling.entity_type AS entity_type, sibling.aliases AS aliases,
               ce.canonical_name AS canon_name
        """
        seen_ids = set(entity_ids)
        expanded = list(entities)

        with self._driver.session() as session:
            result = session.run(query, entity_ids=entity_ids, tenant_id=tenant_id)
            for r in result:
                if r["entity_id"] not in seen_ids:
                    expanded.append(dict(r))
                    seen_ids.add(r["entity_id"])

        if len(expanded) > len(entities):
            new_names = [e["name"] for e in expanded if e["entity_id"] not in set(entity_ids)]
            logger.info(
                f"[OSMOSE:ConceptResolver] Expansion canonique : +{len(expanded) - len(entities)} "
                f"entités ({new_names[:5]}{'...' if len(new_names) > 5 else ''})"
            )

        return expanded

    # ── Alias statiques ──────────────────────────────────────────────────

    def _get_aliases(self, concept_name: str) -> List[str]:
        """Récupère les alias connus pour un concept (table statique POC)."""
        lower = concept_name.lower()
        for key, aliases in KNOWN_ALIASES.items():
            if lower == key.lower():
                return aliases
            if lower in [a.lower() for a in aliases]:
                return [key] + [a for a in aliases if a.lower() != lower]
        return []

    # ── Construction du résultat ─────────────────────────────────────────

    def _build_resolved(
        self,
        entities: List[dict],
        concept_name: str,
        tenant_id: str,
        method: str,
        confidence: float,
        ambiguity_notes: Optional[List[str]] = None,
    ) -> ResolvedConcept:
        """Construit un ResolvedConcept à partir des entités trouvées."""
        entity_ids = [e["entity_id"] for e in entities]
        all_aliases = set()
        for e in entities:
            raw_aliases = e.get("aliases") or []
            if isinstance(raw_aliases, str):
                raw_aliases = [raw_aliases]
            all_aliases.update(raw_aliases)
            if e["name"].lower() != concept_name.lower():
                all_aliases.add(e["name"])
        all_aliases.discard(concept_name)

        # Préférer le canon_name s'il existe, sinon le nom de la première entité
        canonical_name = concept_name
        for e in entities:
            if e.get("canon_name"):
                canonical_name = e["canon_name"]
                break
        if canonical_name == concept_name:
            canonical_name = entities[0].get("name", concept_name)

        entity_type = entities[0].get("entity_type", "concept") or "concept"

        # Récupérer claims, docs et facettes
        claims_data = self._get_claims_and_docs(entity_ids, tenant_id)
        facet_domains = self._get_facet_domains(claims_data["claim_ids"], tenant_id)

        return ResolvedConcept(
            canonical_name=canonical_name,
            entity_type=entity_type,
            entity_ids=entity_ids,
            aliases=sorted(all_aliases),
            claim_count=len(claims_data["claim_ids"]),
            doc_ids=claims_data["doc_ids"],
            facet_domains=facet_domains,
            resolution_method=method,
            resolution_confidence=confidence,
            ambiguity_notes=ambiguity_notes or [],
        )

    def _get_claims_and_docs(self, entity_ids: List[str], tenant_id: str) -> dict:
        """Récupère claim_ids et doc_ids liés aux entités."""
        query = """
        MATCH (c:Claim)-[:ABOUT]->(e:Entity)
        WHERE e.entity_id IN $entity_ids AND c.tenant_id = $tenant_id
        RETURN DISTINCT c.claim_id AS claim_id, c.doc_id AS doc_id
        """
        claim_ids = []
        doc_ids = set()
        with self._driver.session() as session:
            result = session.run(query, entity_ids=entity_ids, tenant_id=tenant_id)
            for r in result:
                claim_ids.append(r["claim_id"])
                if r["doc_id"]:
                    doc_ids.add(r["doc_id"])
        return {"claim_ids": claim_ids, "doc_ids": sorted(doc_ids)}

    def _get_facet_domains(self, claim_ids: List[str], tenant_id: str) -> List[str]:
        """Récupère les domaines de facettes liés aux claims."""
        if not claim_ids:
            return []
        query = """
        MATCH (c:Claim)-[:BELONGS_TO_FACET]->(f:Facet)
        WHERE c.claim_id IN $claim_ids AND c.tenant_id = $tenant_id
        RETURN DISTINCT f.domain AS domain
        """
        with self._driver.session() as session:
            result = session.run(query, claim_ids=claim_ids, tenant_id=tenant_id)
            return sorted([r["domain"] for r in result if r["domain"]])
