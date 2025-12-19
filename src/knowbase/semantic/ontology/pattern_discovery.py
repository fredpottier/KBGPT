"""
🌊 OSMOSE Phase 2.3 - Pattern Discovery Service

Service de détection automatique de patterns dans le Knowledge Graph
pour identifier de nouveaux types d'entités émergents.

Algorithmes utilisés:
1. Frequency Analysis: Concepts avec >N occurrences non typés
2. Clustering Analysis: Groupes de concepts similaires
3. Relation Pattern Mining: Types de relations récurrents
4. Context Analysis: Contextes d'apparition similaires

Seuils par défaut:
- MIN_OCCURRENCES: 20 (concept doit apparaître 20+ fois)
- MIN_CLUSTER_SIZE: 5 (cluster doit contenir 5+ concepts)
- MIN_PATTERN_CONFIDENCE: 0.7 (confidence minimale pour proposer)
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings
from knowbase.semantic.models import ConceptType

settings = get_settings()
logger = setup_logging(settings.logs_dir, "pattern_discovery.log")


class PatternType(str, Enum):
    """Types de patterns détectables."""
    NEW_ENTITY_TYPE = "new_entity_type"       # Nouveau type d'entité proposé
    TYPE_REFINEMENT = "type_refinement"       # Sous-type d'un type existant
    RELATION_PATTERN = "relation_pattern"     # Pattern de relation récurrent
    CLUSTER_PATTERN = "cluster_pattern"       # Groupe de concepts similaires
    NAMING_PATTERN = "naming_pattern"         # Pattern de nommage (ex: *_API, *_Service)


@dataclass
class DiscoveredPattern:
    """Pattern découvert dans le Knowledge Graph."""
    pattern_id: str
    pattern_type: PatternType

    # Description
    suggested_name: str                       # Nom proposé (ex: "CLINICAL_TRIAL")
    description: str                          # Description du pattern

    # Métriques
    occurrences: int                          # Nombre d'occurrences
    confidence: float                         # Confidence score [0-1]
    support_concepts: List[str] = field(default_factory=list)  # Concepts qui supportent ce pattern

    # Contexte
    example_contexts: List[str] = field(default_factory=list)  # Exemples de contextes
    parent_type: Optional[str] = None         # Type parent si refinement

    # Metadata
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    tenant_id: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type.value,
            "suggested_name": self.suggested_name,
            "description": self.description,
            "occurrences": self.occurrences,
            "confidence": self.confidence,
            "support_concepts": self.support_concepts[:10],  # Limiter
            "example_contexts": self.example_contexts[:3],
            "parent_type": self.parent_type,
            "discovered_at": self.discovered_at.isoformat(),
            "tenant_id": self.tenant_id,
        }


class PatternDiscoveryService:
    """
    Service de découverte automatique de patterns dans le KG.

    Analyse périodiquement le Knowledge Graph pour identifier:
    - Nouveaux types d'entités émergents
    - Raffinements de types existants
    - Patterns de relations récurrents

    IMPORTANT: Cette implémentation est DOMAIN-AGNOSTIC par défaut.
    La détection se base uniquement sur:
    - Analyse de fréquence (concepts récurrents)
    - Patterns de nommage (suffixes/préfixes)
    - Clustering via graphe (concepts fortement connectés)

    Les domain_patterns optionnels ne sont activés que si
    use_domain_hints=True (désactivé par défaut).
    """

    # Seuils configurables
    MIN_OCCURRENCES = 20          # Minimum occurrences pour proposer nouveau type
    MIN_CLUSTER_SIZE = 5          # Taille minimum cluster
    MIN_PATTERN_CONFIDENCE = 0.7  # Confidence minimale
    TOP_K_PATTERNS = 20           # Nombre max patterns à retourner

    def __init__(self, use_domain_hints: bool = False):
        """
        Initialise le service de découverte de patterns.

        Args:
            use_domain_hints: Si True, utilise des indices de domaine
                              pré-définis (NON recommandé - casse le
                              principe domain-agnostic). Défaut: False
        """
        self._neo4j_client = None
        self._existing_types: Set[str] = set()
        self._use_domain_hints = use_domain_hints

    @property
    def neo4j_client(self):
        """Lazy loading du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.neo4j_custom.client import get_neo4j_client
            self._neo4j_client = get_neo4j_client()
        return self._neo4j_client

    def _get_existing_types(self) -> Set[str]:
        """Récupère les types existants (enum + registry)."""
        # Types de base de l'enum
        base_types = {t.value.upper() for t in ConceptType}

        # Types du registry (approved)
        try:
            cypher = """
            MATCH (c:CanonicalConcept)
            WHERE c.type IS NOT NULL
            RETURN DISTINCT toUpper(c.type) AS type
            """
            results = self.neo4j_client.execute_query(cypher, {})
            kg_types = {r["type"] for r in results if r.get("type")}
            return base_types | kg_types
        except Exception as e:
            logger.warning(f"[OSMOSE] Erreur récupération types: {e}")
            return base_types

    async def discover_new_entity_types(
        self,
        tenant_id: str = "default",
        min_occurrences: int = None,
        max_results: int = None
    ) -> List[DiscoveredPattern]:
        """
        Découvre de nouveaux types d'entités potentiels.

        Analyse les concepts "entity" génériques qui pourraient être
        des types plus spécifiques (ex: CLINICAL_TRIAL, DRUG, SYMPTOM).

        Stratégie:
        1. Récupérer concepts type="entity" avec haute fréquence
        2. Analyser patterns de nommage (suffixes, préfixes communs)
        3. Analyser contextes d'apparition
        4. Proposer nouveaux types avec confidence

        Args:
            tenant_id: Tenant ID
            min_occurrences: Seuil minimum (défaut: MIN_OCCURRENCES)
            max_results: Nombre max résultats (défaut: TOP_K_PATTERNS)

        Returns:
            Liste de DiscoveredPattern
        """
        min_occ = min_occurrences or self.MIN_OCCURRENCES
        max_res = max_results or self.TOP_K_PATTERNS

        logger.info(f"[OSMOSE] Discovering new entity types (min_occ={min_occ})...")

        patterns = []

        # 1. Analyser les concepts "entity" fréquents
        entity_patterns = await self._analyze_frequent_entities(tenant_id, min_occ)
        patterns.extend(entity_patterns)

        # 2. Analyser les patterns de nommage
        naming_patterns = await self._analyze_naming_patterns(tenant_id, min_occ)
        patterns.extend(naming_patterns)

        # 3. Analyser les clusters de concepts similaires
        cluster_patterns = await self._analyze_concept_clusters(tenant_id)
        patterns.extend(cluster_patterns)

        # Trier par confidence et limiter
        patterns.sort(key=lambda p: p.confidence, reverse=True)
        patterns = patterns[:max_res]

        logger.info(f"[OSMOSE] Discovered {len(patterns)} potential new types")

        return patterns

    async def _analyze_frequent_entities(
        self,
        tenant_id: str,
        min_occurrences: int
    ) -> List[DiscoveredPattern]:
        """
        Analyse les concepts "entity" génériques fréquents.

        Cherche des groupes de concepts du même domaine qui pourraient
        constituer un nouveau type.
        """
        patterns = []

        # Récupérer concepts entity avec leur fréquence de relations
        cypher = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WHERE c.type = 'entity' OR c.concept_type = 'entity'
        OPTIONAL MATCH (c)-[r]-(other:CanonicalConcept)
        WITH c, count(r) AS relation_count
        WHERE relation_count >= $min_relations
        RETURN
            c.canonical_name AS name,
            c.definition AS definition,
            relation_count,
            c.concept_type AS current_type
        ORDER BY relation_count DESC
        LIMIT 100
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "tenant_id": tenant_id,
                "min_relations": min_occurrences // 2  # Relations = proxy pour importance
            })

            # Grouper par domaine/catégorie détectée
            domain_groups = self._group_by_semantic_domain(results)

            for domain, concepts in domain_groups.items():
                if len(concepts) >= self.MIN_CLUSTER_SIZE:
                    pattern = DiscoveredPattern(
                        pattern_id=f"ent_{domain.lower().replace(' ', '_')}_{len(patterns)}",
                        pattern_type=PatternType.NEW_ENTITY_TYPE,
                        suggested_name=domain.upper().replace(" ", "_"),
                        description=f"Groupe de {len(concepts)} concepts liés au domaine '{domain}'",
                        occurrences=sum(c.get("relation_count", 0) for c in concepts),
                        confidence=min(0.9, 0.5 + len(concepts) / 20),
                        support_concepts=[c["name"] for c in concepts[:10]],
                        example_contexts=[c.get("definition", "")[:100] for c in concepts[:3] if c.get("definition")],
                        parent_type="ENTITY",
                        tenant_id=tenant_id,
                    )
                    patterns.append(pattern)

        except Exception as e:
            logger.error(f"[OSMOSE] Erreur analyse entités: {e}")

        return patterns

    def _group_by_semantic_domain(
        self,
        concepts: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Groupe les concepts par domaine sémantique détecté.

        Mode DOMAIN-AGNOSTIC (défaut):
        - Groupement par tokens communs dans les noms
        - Aucune connaissance métier pré-définie

        Mode DOMAIN-HINTS (use_domain_hints=True):
        - Utilise des patterns de domaines pré-définis
        - NON recommandé pour solution générique
        """
        domain_groups = defaultdict(list)

        if self._use_domain_hints:
            # MODE LEGACY: Patterns de domaines pré-définis (NON recommandé)
            # Gardé uniquement pour compatibilité si explicitement activé
            domain_patterns = {
                "Clinical Trial": ["trial", "study", "phase", "randomized", "placebo"],
                "Drug/Treatment": ["drug", "treatment", "therapy", "medication", "dose"],
                "Medical Condition": ["disease", "syndrome", "disorder", "condition", "symptom"],
                "Organization": ["hospital", "university", "institute", "company", "consortium"],
                "Metric/Measure": ["ratio", "score", "index", "rate", "percentage"],
                "Technology": ["api", "service", "platform", "system", "framework"],
                "Process": ["process", "workflow", "procedure", "protocol", "method"],
            }

            for concept in concepts:
                name = concept.get("name", "").lower()
                definition = (concept.get("definition") or "").lower()
                text = f"{name} {definition}"

                best_domain = "General"
                best_score = 0

                for domain, keywords in domain_patterns.items():
                    score = sum(1 for kw in keywords if kw in text)
                    if score > best_score:
                        best_score = score
                        best_domain = domain

                if best_score >= 2:
                    domain_groups[best_domain].append(concept)
        else:
            # MODE DOMAIN-AGNOSTIC (défaut) : Groupement par tokens communs
            # Extrait les tokens de chaque concept et groupe par token dominant

            # Étape 1: Collecter tous les tokens de tous les concepts
            concept_tokens = {}
            all_tokens = Counter()

            for concept in concepts:
                name = concept.get("name", "")
                # Tokeniser: séparer sur _, -, espaces et camelCase
                tokens = self._tokenize_concept_name(name)
                concept_tokens[concept.get("name", "")] = tokens
                all_tokens.update(tokens)

            # Étape 2: Identifier tokens significatifs (apparaissent dans >3 concepts)
            significant_tokens = {
                token for token, count in all_tokens.items()
                if count >= 3 and len(token) >= 3  # Au moins 3 occurrences, 3 caractères
            }

            # Étape 3: Grouper concepts par leur token dominant
            for concept in concepts:
                name = concept.get("name", "")
                tokens = concept_tokens.get(name, [])

                # Trouver le token significatif le plus fréquent dans ce concept
                best_token = None
                best_count = 0
                for token in tokens:
                    if token in significant_tokens:
                        count = all_tokens[token]
                        if count > best_count:
                            best_count = count
                            best_token = token

                if best_token:
                    domain_groups[best_token.title()].append(concept)

        return dict(domain_groups)

    def _tokenize_concept_name(self, name: str) -> List[str]:
        """
        Tokenise un nom de concept de façon domain-agnostic.

        Gère:
        - snake_case: "my_concept" -> ["my", "concept"]
        - kebab-case: "my-concept" -> ["my", "concept"]
        - CamelCase: "MyConcept" -> ["my", "concept"]
        - Espaces: "my concept" -> ["my", "concept"]
        """
        import re

        # Remplacer séparateurs par espaces
        name = name.replace("_", " ").replace("-", " ")

        # Séparer CamelCase
        name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)

        # Tokeniser et filtrer
        tokens = name.lower().split()
        tokens = [t.strip() for t in tokens if t.strip() and len(t.strip()) >= 2]

        return tokens

    async def _analyze_naming_patterns(
        self,
        tenant_id: str,
        min_occurrences: int
    ) -> List[DiscoveredPattern]:
        """
        Analyse les patterns de nommage (suffixes/préfixes communs).

        Exemples détectables:
        - *_API, *_Service → SERVICE
        - *_Test, *_Study → STUDY
        - SAP_*, S/4* → SAP_COMPONENT
        """
        patterns = []

        # Récupérer tous les noms de concepts
        cypher = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        RETURN c.canonical_name AS name
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {"tenant_id": tenant_id})
            names = [r["name"] for r in results if r.get("name")]

            # Analyser suffixes
            suffix_counts = Counter()
            suffix_examples = defaultdict(list)

            for name in names:
                # Extraire suffixe (après _ ou espace)
                parts = name.replace("-", "_").split("_")
                if len(parts) > 1:
                    suffix = parts[-1].upper()
                    if len(suffix) >= 3:  # Ignorer suffixes courts
                        suffix_counts[suffix] += 1
                        suffix_examples[suffix].append(name)

            # Créer patterns pour suffixes fréquents
            for suffix, count in suffix_counts.most_common(10):
                if count >= min_occurrences // 2:
                    patterns.append(DiscoveredPattern(
                        pattern_id=f"naming_suffix_{suffix.lower()}",
                        pattern_type=PatternType.NAMING_PATTERN,
                        suggested_name=suffix,
                        description=f"Pattern de nommage: concepts se terminant par '_{suffix}'",
                        occurrences=count,
                        confidence=min(0.85, 0.4 + count / 50),
                        support_concepts=suffix_examples[suffix][:10],
                        tenant_id=tenant_id,
                    ))

            # Analyser préfixes
            prefix_counts = Counter()
            prefix_examples = defaultdict(list)

            for name in names:
                parts = name.replace("-", "_").split("_")
                if len(parts) > 1:
                    prefix = parts[0].upper()
                    if len(prefix) >= 2:
                        prefix_counts[prefix] += 1
                        prefix_examples[prefix].append(name)

            for prefix, count in prefix_counts.most_common(10):
                if count >= min_occurrences // 2:
                    patterns.append(DiscoveredPattern(
                        pattern_id=f"naming_prefix_{prefix.lower()}",
                        pattern_type=PatternType.NAMING_PATTERN,
                        suggested_name=f"{prefix}_COMPONENT",
                        description=f"Pattern de nommage: concepts commençant par '{prefix}_'",
                        occurrences=count,
                        confidence=min(0.8, 0.3 + count / 50),
                        support_concepts=prefix_examples[prefix][:10],
                        tenant_id=tenant_id,
                    ))

        except Exception as e:
            logger.error(f"[OSMOSE] Erreur analyse naming patterns: {e}")

        return patterns

    async def _analyze_concept_clusters(
        self,
        tenant_id: str
    ) -> List[DiscoveredPattern]:
        """
        Analyse les clusters de concepts fortement connectés.

        Utilise les relations du KG pour identifier des groupes
        de concepts qui pourraient constituer un nouveau type.
        """
        patterns = []

        # Utiliser l'InferenceEngine pour récupérer les clusters existants
        try:
            from knowbase.semantic.inference import InferenceEngine

            engine = InferenceEngine()
            clusters = await engine.discover_hidden_clusters(
                tenant_id=tenant_id,
                max_results=10
            )

            for cluster in clusters:
                # Vérifier si le cluster pourrait être un nouveau type
                concepts = cluster.concepts_involved
                if len(concepts) >= self.MIN_CLUSTER_SIZE:
                    # Analyser si les concepts sont homogènes (même type potentiel)
                    if self._is_homogeneous_cluster(concepts):
                        patterns.append(DiscoveredPattern(
                            pattern_id=f"cluster_{cluster.insight_id}",
                            pattern_type=PatternType.CLUSTER_PATTERN,
                            suggested_name=self._suggest_cluster_name(concepts),
                            description=cluster.description,
                            occurrences=len(concepts),
                            confidence=cluster.confidence,
                            support_concepts=concepts[:10],
                            tenant_id=tenant_id,
                        ))

        except Exception as e:
            logger.warning(f"[OSMOSE] Erreur analyse clusters: {e}")

        return patterns

    def _is_homogeneous_cluster(self, concepts: List[str]) -> bool:
        """Vérifie si un cluster est sémantiquement homogène."""
        # Heuristique simple: vérifier suffixes/préfixes communs
        if len(concepts) < 3:
            return False

        # Extraire tokens
        all_tokens = []
        for concept in concepts:
            tokens = concept.lower().replace("-", " ").replace("_", " ").split()
            all_tokens.extend(tokens)

        # Compter fréquence tokens
        token_counts = Counter(all_tokens)
        most_common = token_counts.most_common(3)

        # Si un token apparaît dans >50% des concepts, c'est homogène
        if most_common and most_common[0][1] >= len(concepts) * 0.5:
            return True

        return False

    def _suggest_cluster_name(self, concepts: List[str]) -> str:
        """Suggère un nom pour un cluster basé sur les concepts."""
        # Extraire tokens communs
        all_tokens = []
        for concept in concepts:
            tokens = concept.upper().replace("-", "_").split("_")
            all_tokens.extend(tokens)

        token_counts = Counter(all_tokens)
        most_common = token_counts.most_common(1)

        if most_common:
            return f"{most_common[0][0]}_GROUP"
        return "UNNAMED_CLUSTER"

    async def discover_relation_patterns(
        self,
        tenant_id: str = "default",
        min_occurrences: int = None
    ) -> List[DiscoveredPattern]:
        """
        Découvre des patterns de relations récurrents.

        Identifie des combinaisons (source_type, relation, target_type)
        fréquentes qui pourraient indiquer des règles ontologiques.
        """
        min_occ = min_occurrences or self.MIN_OCCURRENCES
        patterns = []

        cypher = """
        MATCH (s:CanonicalConcept {tenant_id: $tenant_id})-[r]->(t:CanonicalConcept)
        WITH
            COALESCE(s.type, s.concept_type, 'entity') AS source_type,
            type(r) AS rel_type,
            COALESCE(t.type, t.concept_type, 'entity') AS target_type,
            count(*) AS count
        WHERE count >= $min_count
        RETURN source_type, rel_type, target_type, count
        ORDER BY count DESC
        LIMIT 20
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "tenant_id": tenant_id,
                "min_count": min_occ // 2
            })

            for r in results:
                pattern_name = f"{r['source_type']}_{r['rel_type']}_{r['target_type']}"
                patterns.append(DiscoveredPattern(
                    pattern_id=f"rel_{pattern_name.lower()}",
                    pattern_type=PatternType.RELATION_PATTERN,
                    suggested_name=pattern_name,
                    description=f"Pattern: {r['source_type']} --[{r['rel_type']}]--> {r['target_type']}",
                    occurrences=r["count"],
                    confidence=min(0.9, 0.5 + r["count"] / 100),
                    tenant_id=tenant_id,
                ))

        except Exception as e:
            logger.error(f"[OSMOSE] Erreur analyse relation patterns: {e}")

        return patterns

    async def discover_type_refinements(
        self,
        tenant_id: str = "default",
        base_type: str = "entity"
    ) -> List[DiscoveredPattern]:
        """
        Découvre des raffinements potentiels pour un type existant.

        Analyse les concepts d'un type donné pour identifier des sous-types.

        Args:
            tenant_id: Tenant ID
            base_type: Type de base à raffiner (ex: "entity")

        Returns:
            Liste de DiscoveredPattern de type TYPE_REFINEMENT
        """
        patterns = []

        # Récupérer concepts du type de base avec contextes
        cypher = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WHERE c.type = $base_type OR c.concept_type = $base_type
        OPTIONAL MATCH (c)-[r]->(related:CanonicalConcept)
        WITH c, collect(DISTINCT type(r)) AS relation_types
        RETURN
            c.canonical_name AS name,
            c.definition AS definition,
            relation_types
        LIMIT 200
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "tenant_id": tenant_id,
                "base_type": base_type.lower()
            })

            # Grouper par patterns de relations
            relation_groups = defaultdict(list)
            for r in results:
                rel_signature = tuple(sorted(r.get("relation_types", [])))
                if rel_signature:
                    relation_groups[rel_signature].append(r)

            # Créer patterns pour groupes significatifs
            for rel_sig, concepts in relation_groups.items():
                if len(concepts) >= self.MIN_CLUSTER_SIZE:
                    rel_name = "_".join(sorted(rel_sig))[:30]
                    patterns.append(DiscoveredPattern(
                        pattern_id=f"refine_{base_type}_{rel_name}",
                        pattern_type=PatternType.TYPE_REFINEMENT,
                        suggested_name=f"{base_type.upper()}_{rel_name.upper()}",
                        description=f"Sous-type de {base_type}: concepts avec relations [{', '.join(rel_sig)}]",
                        occurrences=len(concepts),
                        confidence=min(0.8, 0.4 + len(concepts) / 30),
                        support_concepts=[c["name"] for c in concepts[:10]],
                        parent_type=base_type.upper(),
                        tenant_id=tenant_id,
                    ))

        except Exception as e:
            logger.error(f"[OSMOSE] Erreur analyse type refinements: {e}")

        return patterns

    async def run_full_discovery(
        self,
        tenant_id: str = "default"
    ) -> Dict[str, List[DiscoveredPattern]]:
        """
        Exécute une découverte complète de tous les patterns.

        Returns:
            Dictionnaire avec patterns groupés par type
        """
        logger.info(f"[OSMOSE] Starting full pattern discovery for tenant {tenant_id}")

        results = {
            "new_entity_types": [],
            "relation_patterns": [],
            "type_refinements": [],
        }

        # Découverte parallèle
        new_types, rel_patterns, refinements = await asyncio.gather(
            self.discover_new_entity_types(tenant_id),
            self.discover_relation_patterns(tenant_id),
            self.discover_type_refinements(tenant_id),
        )

        results["new_entity_types"] = new_types
        results["relation_patterns"] = rel_patterns
        results["type_refinements"] = refinements

        total = sum(len(v) for v in results.values())
        logger.info(f"[OSMOSE] Full discovery complete: {total} patterns found")

        return results


# Singleton
_pattern_discovery_service: Optional[PatternDiscoveryService] = None


def get_pattern_discovery_service(use_domain_hints: bool = False) -> PatternDiscoveryService:
    """
    Retourne l'instance singleton du service.

    Args:
        use_domain_hints: Si True, utilise des patterns de domaine pré-définis.
                          DÉCONSEILLÉ - casse le principe domain-agnostic.
                          Défaut: False (mode domain-agnostic)

    Note: Le paramètre n'est utilisé qu'à la première instanciation.
    """
    global _pattern_discovery_service
    if _pattern_discovery_service is None:
        _pattern_discovery_service = PatternDiscoveryService(use_domain_hints=use_domain_hints)
        logger.info(f"[OSMOSE] PatternDiscoveryService initialisé (domain_hints={use_domain_hints})")
    return _pattern_discovery_service


__all__ = [
    "PatternDiscoveryService",
    "DiscoveredPattern",
    "PatternType",
    "get_pattern_discovery_service",
]
