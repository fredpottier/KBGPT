"""
Adaptive Ontology Manager

Gère le cache d'ontologie auto-apprenant dans Neo4j.

Phase 1.6+ : Zero-Config Intelligence - L'ontologie s'apprend automatiquement
lors de l'ingestion de documents.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)


# Validation et sanitization (P0 - Security hardening)
VALID_CONCEPT_NAME_PATTERN = re.compile(r"^[\w\s\-_\/\.\,\(\)\'\"]+$", re.UNICODE)
MAX_CONCEPT_NAME_LENGTH = 200
VALID_TENANT_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,50}$")


def _sanitize_concept_name(raw_name: str, max_length: int = MAX_CONCEPT_NAME_LENGTH) -> str:
    """
    Nettoie et valide nom concept avant utilisation (P0 - Injection protection).

    Args:
        raw_name: Nom brut à valider
        max_length: Longueur max autorisée

    Returns:
        Nom nettoyé

    Raises:
        ValueError: Si nom invalide (longueur, caractères)
    """
    if not raw_name or not raw_name.strip():
        raise ValueError("Concept name cannot be empty")

    # Longueur max
    if len(raw_name) > max_length:
        raise ValueError(f"Concept name too long: {len(raw_name)} > {max_length}")

    # Caractères autorisés: alphanumériques Unicode, espaces, -_/.,()'"
    if not VALID_CONCEPT_NAME_PATTERN.match(raw_name):
        raise ValueError(f"Invalid characters in concept name: {raw_name}")

    return raw_name.strip()


def _validate_tenant_id(tenant_id: str) -> str:
    """
    Valide tenant_id (P2 - Tenant isolation).

    Args:
        tenant_id: Tenant ID à valider

    Returns:
        Tenant ID validé

    Raises:
        ValueError: Si tenant_id invalide
    """
    if not VALID_TENANT_ID_PATTERN.match(tenant_id):
        raise ValueError(f"Invalid tenant_id format: {tenant_id}")
    return tenant_id


class AdaptiveOntologyManager:
    """Gestionnaire ontologie adaptive Neo4j."""

    def __init__(self, neo4j_client):
        """
        Args:
            neo4j_client: Instance Neo4jClient
        """
        self.neo4j = neo4j_client

        logger.info("[AdaptiveOntology] Manager initialized")

    def lookup(
        self,
        raw_name: str,
        tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Cherche canonical_name dans cache ontologie.

        Args:
            raw_name: Nom brut (ex: "S/4HANA Cloud's")
            tenant_id: ID tenant

        Returns:
            Dict avec canonical_name, confidence, etc. ou None si non trouvé

        Example:
            >>> result = manager.lookup("S/4 Cloud Public", "default")
            >>> result["canonical_name"]
            "SAP S/4HANA Cloud, Public Edition"
        """

        if not self.neo4j.is_connected():
            logger.warning("[AdaptiveOntology:Lookup] Neo4j not connected, skipping lookup")
            return None

        # P0 + P2: Validation et sanitization
        try:
            raw_name = _sanitize_concept_name(raw_name)
            tenant_id = _validate_tenant_id(tenant_id)
        except ValueError as e:
            logger.error(f"[AdaptiveOntology:Lookup] Validation error: {e}")
            return None

        # Normaliser raw_name (strip, lower pour comparison)
        normalized_raw = raw_name.strip().lower()

        query = """
        MATCH (o:AdaptiveOntology)
        WHERE o.tenant_id = $tenant_id
          AND (
              toLower(o.canonical_name) = $normalized_raw
              OR ANY(alias IN o.aliases WHERE toLower(alias) = $normalized_raw)
          )
        RETURN o.canonical_name AS canonical_name,
               o.aliases AS aliases,
               o.concept_type AS concept_type,
               o.domain AS domain,
               o.confidence AS confidence,
               o.source AS source,
               o.usage_count AS usage_count,
               o.ambiguity_warning AS ambiguity_warning,
               o.possible_matches AS possible_matches,
               o.ontology_id AS ontology_id
        LIMIT 1
        """

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    normalized_raw=normalized_raw,
                    tenant_id=tenant_id
                )

                record = result.single()

                if record:
                    logger.debug(
                        f"[AdaptiveOntology:Lookup] ✅ Cache HIT for '{raw_name}' → '{record['canonical_name']}'"
                    )
                    return dict(record)
                else:
                    logger.debug(
                        f"[AdaptiveOntology:Lookup] ❌ Cache MISS for '{raw_name}'"
                    )
                    return None

        except Exception as e:
            logger.error(f"[AdaptiveOntology:Lookup] Error looking up '{raw_name}': {e}")
            return None

    def store(
        self,
        tenant_id: str,
        canonical_name: str,
        raw_name: str,
        canonicalization_result: Dict[str, Any],
        context: Optional[str] = None,
        document_id: Optional[str] = None,
        min_confidence: float = 0.6
    ) -> str:
        """
        Stocke résultat canonicalisation dans ontologie (P0 - Cache poisoning protection).

        Args:
            tenant_id: ID tenant
            canonical_name: Nom canonique trouvé
            raw_name: Nom brut d'origine
            canonicalization_result: Résultat LLM complet
            context: Contexte textuel (optionnel)
            document_id: ID document source (optionnel)
            min_confidence: Confidence minimale pour stocker (P0 protection)

        Returns:
            ontology_id créé
        """

        if not self.neo4j.is_connected():
            logger.warning("[AdaptiveOntology:Store] Neo4j not connected, skipping store")
            return ""

        # P0 + P2: Validation inputs
        try:
            canonical_name = _sanitize_concept_name(canonical_name)
            raw_name = _sanitize_concept_name(raw_name)
            tenant_id = _validate_tenant_id(tenant_id)
        except ValueError as e:
            logger.error(f"[AdaptiveOntology:Store] Validation error: {e}")
            return ""

        # P0: Validation confidence (cache poisoning protection)
        confidence = canonicalization_result.get("confidence", 0.0)
        if confidence < min_confidence:
            logger.warning(
                f"[AdaptiveOntology:Store] ❌ Low confidence {confidence:.2f} < {min_confidence}, "
                f"skipping store for '{canonical_name}'"
            )
            return ""

        # P0: Validation similarité raw_name ↔ canonical_name (hallucination detection)
        from difflib import SequenceMatcher
        similarity = SequenceMatcher(None, raw_name.lower(), canonical_name.lower()).ratio()
        if similarity < 0.3:
            logger.error(
                f"[AdaptiveOntology:Store] ❌ HALLUCINATION DETECTED: "
                f"raw='{raw_name}' vs canonical='{canonical_name}' (similarity={similarity:.2f})"
            )
            return ""

        # P0: Validation taille aliases (DoS protection)
        aliases = canonicalization_result.get("aliases", [])
        if raw_name not in aliases:
            aliases = [raw_name] + aliases

        MAX_ALIASES = 50
        if len(aliases) > MAX_ALIASES:
            logger.warning(
                f"[AdaptiveOntology:Store] Truncating aliases: {len(aliases)} → {MAX_ALIASES}"
            )
            aliases = aliases[:MAX_ALIASES]

        # P0: Vérifier si canonical_name existe déjà (merge au lieu de duplicate)
        existing = self.lookup(canonical_name, tenant_id)
        if existing and existing["canonical_name"] == canonical_name:
            logger.info(
                f"[AdaptiveOntology:Store] Canonical name '{canonical_name}' already exists, "
                f"merging alias '{raw_name}' with existing entry"
            )
            # Merge: ajouter raw_name comme alias de l'entrée existante
            self.add_alias(canonical_name, tenant_id, raw_name)
            return existing["ontology_id"]

        query = """
        CREATE (o:AdaptiveOntology {
            ontology_id: randomUUID(),
            tenant_id: $tenant_id,
            canonical_name: $canonical_name,
            aliases: $aliases,
            concept_type: $concept_type,
            domain: $domain,
            source: $source,
            confidence: $confidence,
            validated_by: 'auto',
            usage_count: 1,
            first_seen: datetime(),
            last_seen: datetime(),
            first_document_id: $document_id,
            example_context: $context,
            ambiguity_warning: $ambiguity_warning,
            possible_matches: $possible_matches
        })
        RETURN o.ontology_id AS ontology_id
        """

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    tenant_id=tenant_id,
                    canonical_name=canonical_name,
                    aliases=aliases,
                    concept_type=canonicalization_result.get("concept_type"),
                    domain=canonicalization_result.get("domain"),
                    source=canonicalization_result.get("source", "llm_gpt4o_mini"),
                    confidence=canonicalization_result.get("confidence", 0.0),
                    document_id=document_id,
                    context=context[:500] if context else None,
                    ambiguity_warning=canonicalization_result.get("ambiguity_warning"),
                    possible_matches=canonicalization_result.get("possible_matches", [])
                )

                record = result.single()
                ontology_id = record["ontology_id"]

                logger.info(
                    f"[AdaptiveOntology:Store] Created ontology entry '{canonical_name}' "
                    f"(id={ontology_id[:8]}, aliases={len(aliases)})"
                )

                return ontology_id

        except Exception as e:
            logger.error(f"[AdaptiveOntology:Store] Error storing '{canonical_name}': {e}")
            return ""

    def add_alias(
        self,
        canonical_name: str,
        tenant_id: str,
        new_alias: str
    ) -> bool:
        """
        Ajoute alias à ontologie existante (auto-enrichissement).

        Args:
            canonical_name: Nom canonique existant
            tenant_id: ID tenant
            new_alias: Nouvelle variante à ajouter

        Returns:
            True si ajouté, False si déjà existant
        """

        if not self.neo4j.is_connected():
            logger.warning("[AdaptiveOntology:AddAlias] Neo4j not connected")
            return False

        # P0 + P2: Validation inputs
        try:
            canonical_name = _sanitize_concept_name(canonical_name)
            new_alias = _sanitize_concept_name(new_alias)
            tenant_id = _validate_tenant_id(tenant_id)
        except ValueError as e:
            logger.error(f"[AdaptiveOntology:AddAlias] Validation error: {e}")
            return False

        query = """
        MATCH (o:AdaptiveOntology)
        WHERE o.tenant_id = $tenant_id
          AND o.canonical_name = $canonical_name
          AND NOT $new_alias IN o.aliases

        SET o.aliases = o.aliases + [$new_alias],
            o.usage_count = o.usage_count + 1,
            o.last_seen = datetime()

        RETURN o.ontology_id AS ontology_id
        """

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    tenant_id=tenant_id,
                    canonical_name=canonical_name,
                    new_alias=new_alias.strip()
                )

                record = result.single()

                if record:
                    logger.debug(
                        f"[AdaptiveOntology:Enrich] Added alias '{new_alias}' → '{canonical_name}'"
                    )
                    return True
                else:
                    logger.debug(
                        f"[AdaptiveOntology:Enrich] Alias '{new_alias}' already exists for '{canonical_name}'"
                    )
                    return False

        except Exception as e:
            logger.error(f"[AdaptiveOntology:AddAlias] Error adding alias: {e}")
            return False

    def increment_usage(
        self,
        canonical_name: str,
        tenant_id: str
    ) -> None:
        """Incrémente compteur usage (statistiques)."""

        if not self.neo4j.is_connected():
            return

        # P0 + P2: Validation inputs
        try:
            canonical_name = _sanitize_concept_name(canonical_name)
            tenant_id = _validate_tenant_id(tenant_id)
        except ValueError as e:
            logger.error(f"[AdaptiveOntology:Usage] Validation error: {e}")
            return

        query = """
        MATCH (o:AdaptiveOntology)
        WHERE o.tenant_id = $tenant_id
          AND o.canonical_name = $canonical_name

        SET o.usage_count = o.usage_count + 1,
            o.last_seen = datetime()
        """

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                session.run(
                    query,
                    tenant_id=tenant_id,
                    canonical_name=canonical_name
                )

                logger.debug(
                    f"[AdaptiveOntology:Usage] Incremented usage for '{canonical_name}'"
                )

        except Exception as e:
            logger.error(f"[AdaptiveOntology:Usage] Error incrementing usage: {e}")

    def get_stats(self, tenant_id: str) -> Dict[str, Any]:
        """
        Retourne statistiques ontologie.

        Returns:
            Dict avec total_entries, cache_hit_rate, top_concepts, etc.
        """

        if not self.neo4j.is_connected():
            return {"total_entries": 0, "error": "Neo4j not connected"}

        query = """
        MATCH (o:AdaptiveOntology {tenant_id: $tenant_id})
        RETURN count(o) AS total_entries,
               avg(o.confidence) AS avg_confidence,
               sum(o.usage_count) AS total_usage
        """

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(query, tenant_id=tenant_id)
                record = result.single()

                if record:
                    return {
                        "total_entries": record["total_entries"],
                        "avg_confidence": round(record["avg_confidence"] or 0.0, 2),
                        "total_usage": record["total_usage"] or 0
                    }
                else:
                    return {"total_entries": 0}

        except Exception as e:
            logger.error(f"[AdaptiveOntology:Stats] Error getting stats: {e}")
            return {"total_entries": 0, "error": str(e)}
