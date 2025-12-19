"""
Adaptive Ontology Manager

Gère le cache d'ontologie auto-apprenant dans Neo4j.

Phase 1.6+ : Zero-Config Intelligence - L'ontologie s'apprend automatiquement
lors de l'ingestion de documents.

Phase 1.8.2: Gatekeeper Prefetch Ontology - Préchargement intelligent par type
de document pour améliorer le cache hit rate (50% → 70%).
"""

from typing import Optional, List, Dict, Any, Set
from datetime import datetime
import logging
import re
import asyncio
import time

logger = logging.getLogger(__name__)


# =========================================================================
# Phase 1.8.2 - Document Type → Domain Mapping
# =========================================================================

DOCUMENT_TYPE_DOMAIN_MAPPING: Dict[str, List[str]] = {
    # Documents techniques SAP
    "sap_technical": ["SAP", "ERP", "Cloud", "Integration"],
    "sap_functional": ["SAP", "Business Process", "Finance", "HR"],
    "sap_presentation": ["SAP", "Product", "Solution"],

    # Documents commerciaux
    "rfp": ["Business", "Requirements", "Compliance"],
    "proposal": ["Solution", "Services", "Implementation"],
    "contract": ["Legal", "Commercial", "SLA"],

    # Documents pharma/réglementaires
    "pharma_regulatory": ["FDA", "Pharma", "Regulatory", "Compliance"],
    "pharma_clinical": ["Clinical", "Trial", "Safety", "Pharma"],
    "pharma_quality": ["Quality", "GxP", "Validation", "Pharma"],

    # Documents CRM/Salesforce
    "crm_documentation": ["CRM", "Salesforce", "Sales", "Marketing"],
    "crm_integration": ["CRM", "Integration", "API", "Data"],

    # Documents génériques
    "technical_specification": ["Technical", "Architecture", "API"],
    "user_guide": ["User", "Guide", "Tutorial"],
    "presentation": ["Overview", "Summary", "Presentation"],

    # Fallback
    "default": ["Business", "Technical", "General"]
}


def get_domains_for_document_type(document_type: str) -> List[str]:
    """
    Retourne les domaines associés à un type de document.

    Args:
        document_type: Type de document (ex: "pharma_regulatory")

    Returns:
        Liste des domaines pertinents
    """
    return DOCUMENT_TYPE_DOMAIN_MAPPING.get(
        document_type,
        DOCUMENT_TYPE_DOMAIN_MAPPING["default"]
    )


# Validation et sanitization (P0 - Security hardening)
VALID_CONCEPT_NAME_PATTERN = re.compile(r"^[\w\s\-_\/\.\,\(\)\'\"\&]+$", re.UNICODE)
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

    def __init__(self, neo4j_client, redis_client=None):
        """
        Args:
            neo4j_client: Instance Neo4jClient
            redis_client: Instance Redis pour rate limiting (optionnel)
        """
        self.neo4j = neo4j_client
        self.redis = redis_client

        logger.info(
            f"[AdaptiveOntology] Manager initialized "
            f"(redis_enabled={redis_client is not None})"
        )

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
               COALESCE(o.usage_count, 0) AS usage_count,
               COALESCE(o.ambiguity_warning, null) AS ambiguity_warning,
               COALESCE(o.possible_matches, []) AS possible_matches,
               COALESCE(o.ontology_id, o.canonical_name) AS ontology_id
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

        # Smart acronym detection: Si raw est acronyme de canonical, OK
        def is_valid_acronym(short: str, long: str) -> bool:
            """Vérifie si short est un acronyme valide de long."""
            # Extraire initiales des mots significatifs (>2 chars) du long form
            import re
            words = [w for w in re.findall(r'\w+', long) if len(w) > 2 or w.upper() == w]
            if not words:
                return False
            acronym_from_long = ''.join(w[0].upper() for w in words)
            # Accepter si match exact OU sous-séquence (ex: "ERP" dans "Enterprise Resource Planning")
            short_upper = short.upper().replace(' ', '')
            return (short_upper == acronym_from_long or
                    short_upper in acronym_from_long or
                    all(c in acronym_from_long for c in short_upper))

        is_acronym = is_valid_acronym(raw_name, canonical_name)

        # Threshold adaptatif: 0.15 pour acronymes, 0.30 pour le reste
        min_similarity = 0.15 if is_acronym else 0.30

        if similarity < min_similarity:
            logger.error(
                f"[AdaptiveOntology:Store] ❌ HALLUCINATION DETECTED: "
                f"raw='{raw_name}' vs canonical='{canonical_name}' "
                f"(similarity={similarity:.2f}, acronym={is_acronym}, threshold={min_similarity})"
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

    async def store_async(
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
        Version async de store() pour utilisation dans boucle événementielle asyncio.

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
            logger.warning("[AdaptiveOntology:StoreAsync] Neo4j not connected, skipping store")
            return ""

        # P0 + P2: Validation inputs
        try:
            canonical_name = _sanitize_concept_name(canonical_name)
            raw_name = _sanitize_concept_name(raw_name)
            tenant_id = _validate_tenant_id(tenant_id)
        except ValueError as e:
            logger.error(f"[AdaptiveOntology:StoreAsync] Validation error: {e}")
            return ""

        # P0: Validation confidence (cache poisoning protection)
        confidence = canonicalization_result.get("confidence", 0.0)
        if confidence < min_confidence:
            logger.warning(
                f"[AdaptiveOntology:StoreAsync] ❌ Low confidence {confidence:.2f} < {min_confidence}, "
                f"skipping store for '{canonical_name}'"
            )
            return ""

        # P0: Validation similarité raw_name ↔ canonical_name (hallucination detection)
        from difflib import SequenceMatcher
        similarity = SequenceMatcher(None, raw_name.lower(), canonical_name.lower()).ratio()

        # Smart acronym detection: Si raw est acronyme de canonical, OK
        def is_valid_acronym(short: str, long: str) -> bool:
            """Vérifie si short est un acronyme valide de long."""
            # Extraire initiales des mots significatifs (>2 chars) du long form
            import re
            words = [w for w in re.findall(r'\w+', long) if len(w) > 2 or w.upper() == w]
            if not words:
                return False
            acronym_from_long = ''.join(w[0].upper() for w in words)
            # Accepter si match exact OU sous-séquence (ex: "ERP" dans "Enterprise Resource Planning")
            short_upper = short.upper().replace(' ', '')
            return (short_upper == acronym_from_long or
                    short_upper in acronym_from_long or
                    all(c in acronym_from_long for c in short_upper))

        is_acronym = is_valid_acronym(raw_name, canonical_name)

        # Threshold adaptatif: 0.15 pour acronymes, 0.30 pour le reste
        min_similarity = 0.15 if is_acronym else 0.30

        if similarity < min_similarity:
            logger.error(
                f"[AdaptiveOntology:StoreAsync] ❌ HALLUCINATION DETECTED: "
                f"raw='{raw_name}' vs canonical='{canonical_name}' "
                f"(similarity={similarity:.2f}, acronym={is_acronym}, threshold={min_similarity})"
            )
            return ""

        # P0: Validation taille aliases (DoS protection)
        aliases = canonicalization_result.get("aliases", [])
        if raw_name not in aliases:
            aliases = [raw_name] + aliases

        MAX_ALIASES = 50
        if len(aliases) > MAX_ALIASES:
            logger.warning(
                f"[AdaptiveOntology:StoreAsync] Truncating aliases: {len(aliases)} → {MAX_ALIASES}"
            )
            aliases = aliases[:MAX_ALIASES]

        # P0: Vérifier si canonical_name existe déjà (merge au lieu de duplicate)
        existing = self.lookup(canonical_name, tenant_id)
        if existing and existing["canonical_name"] == canonical_name:
            logger.info(
                f"[AdaptiveOntology:StoreAsync] Canonical name '{canonical_name}' already exists, "
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
            # Exécuter dans un thread pool pour ne pas bloquer l'event loop
            loop = asyncio.get_event_loop()

            def _sync_store():
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
                    return record["ontology_id"]

            ontology_id = await loop.run_in_executor(None, _sync_store)

            logger.info(
                f"[AdaptiveOntology:StoreAsync] Created ontology entry '{canonical_name}' "
                f"(id={ontology_id[:8]}, aliases={len(aliases)})"
            )

            return ontology_id

        except Exception as e:
            logger.error(f"[AdaptiveOntology:StoreAsync] Error storing '{canonical_name}': {e}")
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

    def check_llm_budget(
        self,
        document_id: str,
        max_llm_calls_per_doc: int = 50
    ) -> bool:
        """
        Vérifie si budget LLM disponible pour document (P0 - Rate limiting).

        Args:
            document_id: ID du document en traitement
            max_llm_calls_per_doc: Limite max appels LLM par document

        Returns:
            True si budget disponible, False si dépassé

        Example:
            >>> if ontology.check_llm_budget(doc_id):
            ...     llm_result = canonicalizer.canonicalize(...)
            ... else:
            ...     # Fallback sans LLM
        """

        if not self.redis:
            # Si Redis indisponible → autoriser (dégradation gracieuse)
            logger.warning(
                "[AdaptiveOntology:Budget] Redis not available, allowing LLM call (no rate limit)"
            )
            return True

        # Clé Redis : llm_budget:{document_id}
        budget_key = f"llm_budget:{document_id}"

        try:
            # Incrémenter compteur (TTL 1h)
            current_count = self.redis.incr(budget_key)

            # Si première incrémentation, définir TTL 1h
            if current_count == 1:
                self.redis.expire(budget_key, 3600)

            if current_count > max_llm_calls_per_doc:
                logger.warning(
                    f"[AdaptiveOntology:Budget] ❌ Budget EXCEEDED for doc '{document_id}': "
                    f"{current_count}/{max_llm_calls_per_doc} LLM calls"
                )
                return False

            logger.debug(
                f"[AdaptiveOntology:Budget] ✅ Budget OK for doc '{document_id}': "
                f"{current_count}/{max_llm_calls_per_doc} LLM calls"
            )

            return True

        except Exception as e:
            # Erreur Redis → autoriser (dégradation gracieuse)
            logger.error(
                f"[AdaptiveOntology:Budget] Redis error, allowing LLM call: {e}"
            )
            return True

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

    # =========================================================================
    # Phase 1.8.2 - Gatekeeper Prefetch Ontology
    # =========================================================================

    def prefetch_for_document_type(
        self,
        document_type: str,
        tenant_id: str,
        ttl_seconds: int = 3600,
        max_entries: int = 500
    ) -> int:
        """
        Précharge les entrées ontologie pertinentes pour un type de document.

        Phase 1.8.2: Améliore cache hit rate de 50% → 70% en préchargeant
        les concepts par domaine avant l'extraction.

        Args:
            document_type: Type de document (ex: "pharma_regulatory", "sap_technical")
            tenant_id: ID tenant
            ttl_seconds: Durée de vie cache en secondes (défaut 1h)
            max_entries: Nombre max d'entrées à précharger par domaine

        Returns:
            Nombre d'entrées préchargées

        Example:
            >>> count = manager.prefetch_for_document_type("pharma_regulatory", "default")
            >>> print(f"Préchargé {count} entrées ontologie")
        """
        if not self.neo4j.is_connected():
            logger.warning("[AdaptiveOntology:Prefetch] Neo4j not connected")
            return 0

        # P2: Validation tenant_id
        try:
            tenant_id = _validate_tenant_id(tenant_id)
        except ValueError as e:
            logger.error(f"[AdaptiveOntology:Prefetch] Validation error: {e}")
            return 0

        # Obtenir les domaines pertinents pour ce type de document
        domains = get_domains_for_document_type(document_type)

        if not domains:
            logger.debug(f"[AdaptiveOntology:Prefetch] No domains for type '{document_type}'")
            return 0

        # Clé cache Redis pour le prefetch
        cache_key = f"ontology_prefetch:{tenant_id}:{document_type}"

        # Vérifier si déjà en cache (éviter requêtes répétées)
        if self.redis:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    logger.debug(
                        f"[AdaptiveOntology:Prefetch] Cache HIT for '{document_type}' "
                        f"(tenant={tenant_id})"
                    )
                    return int(cached)
            except Exception as e:
                logger.warning(f"[AdaptiveOntology:Prefetch] Redis get error: {e}")

        # Requête Neo4j pour récupérer les entrées par domaines
        query = """
        MATCH (o:AdaptiveOntology)
        WHERE o.tenant_id = $tenant_id
          AND o.domain IN $domains
          AND o.confidence >= 0.7
        RETURN o.canonical_name AS canonical_name,
               o.aliases AS aliases,
               o.concept_type AS concept_type,
               o.domain AS domain,
               o.confidence AS confidence,
               o.usage_count AS usage_count
        ORDER BY o.usage_count DESC
        LIMIT $max_entries
        """

        start_time = time.time()
        prefetched_count = 0

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    tenant_id=tenant_id,
                    domains=domains,
                    max_entries=max_entries
                )

                # Stocker les entrées préchargées dans le cache local
                prefetched_entries = []
                for record in result:
                    entry = {
                        "canonical_name": record["canonical_name"],
                        "aliases": record["aliases"] or [],
                        "concept_type": record["concept_type"],
                        "domain": record["domain"],
                        "confidence": record["confidence"],
                        "usage_count": record["usage_count"]
                    }
                    prefetched_entries.append(entry)
                    prefetched_count += 1

                # Stocker dans Redis si disponible
                if self.redis and prefetched_entries:
                    try:
                        import json
                        self.redis.setex(
                            cache_key,
                            ttl_seconds,
                            str(prefetched_count)
                        )
                        # Stocker aussi les données préchargées
                        data_key = f"{cache_key}:data"
                        self.redis.setex(
                            data_key,
                            ttl_seconds,
                            json.dumps(prefetched_entries)
                        )
                    except Exception as e:
                        logger.warning(f"[AdaptiveOntology:Prefetch] Redis set error: {e}")

            elapsed = (time.time() - start_time) * 1000

            logger.info(
                f"[AdaptiveOntology:Prefetch] ✅ Préchargé {prefetched_count} entrées "
                f"pour type='{document_type}' domains={domains} "
                f"(tenant={tenant_id}, {elapsed:.1f}ms)"
            )

            return prefetched_count

        except Exception as e:
            logger.error(f"[AdaptiveOntology:Prefetch] Error: {e}")
            return 0

    def get_prefetched_entries(
        self,
        document_type: str,
        tenant_id: str
    ) -> List[Dict[str, Any]]:
        """
        Récupère les entrées ontologie préchargées depuis le cache.

        Args:
            document_type: Type de document
            tenant_id: ID tenant

        Returns:
            Liste des entrées préchargées (vide si pas en cache)
        """
        if not self.redis:
            logger.debug("[AdaptiveOntology:GetPrefetched] Redis not available")
            return []

        cache_key = f"ontology_prefetch:{tenant_id}:{document_type}:data"

        try:
            import json
            cached_data = self.redis.get(cache_key)
            if cached_data:
                entries = json.loads(cached_data)
                logger.debug(
                    f"[AdaptiveOntology:GetPrefetched] Retrieved {len(entries)} entries "
                    f"from cache for type='{document_type}'"
                )
                return entries
        except Exception as e:
            logger.warning(f"[AdaptiveOntology:GetPrefetched] Error: {e}")

        return []

    def lookup_in_prefetch(
        self,
        raw_name: str,
        document_type: str,
        tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Cherche d'abord dans le cache prefetch avant Neo4j.

        Optimisation Phase 1.8.2: Réduit les requêtes Neo4j en utilisant
        le cache prefetch local.

        Args:
            raw_name: Nom brut à chercher
            document_type: Type de document (pour clé cache)
            tenant_id: ID tenant

        Returns:
            Dict avec canonical_name, etc. ou None si non trouvé
        """
        # Normaliser pour comparaison
        normalized_raw = raw_name.strip().lower()

        # 1. Chercher dans le cache prefetch
        prefetched = self.get_prefetched_entries(document_type, tenant_id)

        for entry in prefetched:
            # Vérifier canonical_name
            if entry["canonical_name"].lower() == normalized_raw:
                logger.debug(
                    f"[AdaptiveOntology:LookupPrefetch] ✅ PREFETCH HIT "
                    f"'{raw_name}' → '{entry['canonical_name']}'"
                )
                return entry

            # Vérifier aliases
            for alias in entry.get("aliases", []):
                if alias.lower() == normalized_raw:
                    logger.debug(
                        f"[AdaptiveOntology:LookupPrefetch] ✅ PREFETCH HIT (alias) "
                        f"'{raw_name}' → '{entry['canonical_name']}'"
                    )
                    return entry

        # 2. Fallback sur lookup Neo4j standard
        logger.debug(
            f"[AdaptiveOntology:LookupPrefetch] Prefetch MISS for '{raw_name}', "
            f"falling back to Neo4j"
        )
        return self.lookup(raw_name, tenant_id)

    def invalidate_prefetch_cache(
        self,
        document_type: str,
        tenant_id: str
    ) -> bool:
        """
        Invalide le cache prefetch pour un type de document.

        Utile après modification de l'ontologie.

        Args:
            document_type: Type de document
            tenant_id: ID tenant

        Returns:
            True si invalidé, False sinon
        """
        if not self.redis:
            return False

        cache_key = f"ontology_prefetch:{tenant_id}:{document_type}"
        data_key = f"{cache_key}:data"

        try:
            self.redis.delete(cache_key, data_key)
            logger.info(
                f"[AdaptiveOntology:InvalidatePrefetch] Cache invalidated "
                f"for type='{document_type}' (tenant={tenant_id})"
            )
            return True
        except Exception as e:
            logger.error(f"[AdaptiveOntology:InvalidatePrefetch] Error: {e}")
            return False

    def get_prefetch_stats(self, tenant_id: str) -> Dict[str, Any]:
        """
        Retourne statistiques du cache prefetch.

        Args:
            tenant_id: ID tenant

        Returns:
            Dict avec stats prefetch (cached_types, total_entries, etc.)
        """
        if not self.redis:
            return {"error": "Redis not available"}

        stats = {
            "cached_types": [],
            "total_cached_entries": 0
        }

        try:
            # Scanner les clés prefetch pour ce tenant
            pattern = f"ontology_prefetch:{tenant_id}:*:data"
            cursor = 0
            keys = []

            # Utiliser SCAN pour éviter KEYS sur grande DB
            while True:
                cursor, partial_keys = self.redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100
                )
                keys.extend(partial_keys)
                if cursor == 0:
                    break

            for key in keys:
                # Extraire document_type de la clé
                parts = key.split(":")
                if len(parts) >= 4:
                    doc_type = parts[2]
                    # Compter les entrées
                    import json
                    data = self.redis.get(key)
                    if data:
                        entries = json.loads(data)
                        stats["cached_types"].append({
                            "document_type": doc_type,
                            "entries_count": len(entries)
                        })
                        stats["total_cached_entries"] += len(entries)

        except Exception as e:
            logger.error(f"[AdaptiveOntology:PrefetchStats] Error: {e}")
            stats["error"] = str(e)

        return stats
