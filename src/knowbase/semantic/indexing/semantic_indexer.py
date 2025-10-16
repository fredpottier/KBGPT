"""
🌊 OSMOSE Semantic Intelligence V2.1 - SemanticIndexer

Canonicalisation cross-lingual et construction hiérarchie.

Composant CRITIQUE pour USP cross-lingual de KnowWhere.
Unifie concepts multilingues: FR "authentification" = EN "authentication"

Pipeline:
1. Embeddings similarity (cross-lingual via multilingual-e5-large)
2. Clustering concepts similaires (threshold 0.85)
3. Sélection nom canonique (priorité anglais)
4. Génération définition unifiée (LLM fusion)
5. Hierarchy construction (parent-child via LLM)
6. Relations extraction (top-5 similaires)

Semaines 8-9 Phase 1 V2.1
"""

from typing import List, Dict, Set, Optional, Tuple
import logging
import json
from collections import Counter
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from knowbase.semantic.models import Concept, CanonicalConcept, ConceptType
from knowbase.semantic.config import SemanticConfig, IndexingConfig
from knowbase.semantic.utils.embeddings import get_embedder
from knowbase.common.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class SemanticIndexer:
    """
    Canonicalisation cross-lingual et construction hiérarchie.

    Responsabilités:
    - Unifier concepts multilingues similaires (threshold 0.85)
    - Sélectionner nom canonique (priorité anglais)
    - Générer définition unifiée (fusion LLM)
    - Construire hiérarchies (parent-child via LLM)
    - Extraire relations sémantiques (top-5 similaires)

    USP KnowWhere:
    - Cross-lingual unification automatique
    - Language-agnostic knowledge graph
    - Meilleur que Copilot/Gemini sur documents multilingues

    Exemple:
    Input concepts:
    - "authentication" (EN)
    - "authentification" (FR)
    - "Authentifizierung" (DE)

    Output canonical:
    - canonical_name: "authentication"
    - aliases: ["authentification", "Authentifizierung"]
    - languages: ["en", "fr", "de"]
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        config: SemanticConfig
    ):
        """
        Initialise le SemanticIndexer.

        Args:
            llm_router: Router LLM pour définitions + hiérarchies
            config: Configuration globale semantic V2.1
        """
        self.llm_router = llm_router
        self.config = config
        self.indexing_config: IndexingConfig = config.indexing
        self.embedder = get_embedder(config)

        logger.info("[OSMOSE] SemanticIndexer V2.1 initialized")

    async def canonicalize_concepts(
        self,
        concepts: List[Concept],
        enable_hierarchy: bool = True,
        enable_relations: bool = True
    ) -> List[CanonicalConcept]:
        """
        Canonicalise concepts cross-lingual.

        Pipeline:
        1. Embeddings multilingues
        2. Similarity matrix (cosine)
        3. Clustering (threshold 0.85)
        4. Sélection nom canonique (priorité EN)
        5. Définition unifiée (LLM)
        6. Hiérarchie (LLM, optional)
        7. Relations (embeddings, optional)

        Args:
            concepts: Liste de concepts à canonicaliser
            enable_hierarchy: Construire hiérarchies parent-child
            enable_relations: Extraire relations sémantiques

        Returns:
            Liste de CanonicalConcept unifiés
        """
        if not concepts:
            logger.warning("[OSMOSE] No concepts to canonicalize")
            return []

        logger.info(f"[OSMOSE] Canonicalizing {len(concepts)} concepts (cross-lingual)")

        # 1. Embeddings
        concept_texts = [c.name for c in concepts]
        logger.debug(f"[OSMOSE] Computing embeddings for {len(concept_texts)} concepts")
        embeddings = self.embedder.encode(concept_texts)

        # 2. Similarity matrix
        similarity_matrix = cosine_similarity(embeddings)
        logger.debug(f"[OSMOSE] Similarity matrix computed: {similarity_matrix.shape}")

        # 3. Clustering concepts similaires
        canonical_groups = self._cluster_similar_concepts(
            concepts,
            similarity_matrix,
            threshold=self.indexing_config.similarity_threshold
        )

        logger.info(
            f"[OSMOSE] Clustered {len(concepts)} concepts into "
            f"{len(canonical_groups)} canonical groups"
        )

        # 4. Construire CanonicalConcept pour chaque groupe
        canonical_concepts = []
        for group in canonical_groups:
            canonical = await self._build_canonical_concept(group)
            canonical_concepts.append(canonical)

        # 5. Hiérarchie (optional)
        if enable_hierarchy and len(canonical_concepts) >= 2:
            logger.info("[OSMOSE] Building concept hierarchy")
            canonical_concepts = await self._build_hierarchy(canonical_concepts)

        # 6. Relations (optional)
        if enable_relations and len(canonical_concepts) >= 2:
            logger.info("[OSMOSE] Extracting semantic relations")
            canonical_concepts = await self._extract_relations(canonical_concepts)

        logger.info(
            f"[OSMOSE] ✅ Canonicalization complete: {len(canonical_concepts)} "
            f"canonical concepts created"
        )

        return canonical_concepts

    def _cluster_similar_concepts(
        self,
        concepts: List[Concept],
        similarity_matrix: np.ndarray,
        threshold: float
    ) -> List[List[Concept]]:
        """
        Cluster concepts similaires via similarity matrix.

        Utilise un algorithme glouton de clustering:
        - Pour chaque concept non visité
        - Trouver tous concepts similaires (similarity > threshold)
        - Former un groupe

        Args:
            concepts: Liste de concepts
            similarity_matrix: Matrice de similarité (n x n)
            threshold: Seuil de similarité (0.85 par défaut)

        Returns:
            Liste de groupes de concepts similaires
        """
        n = len(concepts)
        visited: Set[int] = set()
        canonical_groups: List[List[Concept]] = []

        for i in range(n):
            if i in visited:
                continue

            # Trouver indices similaires
            similar_indices = [
                j for j in range(n)
                if similarity_matrix[i][j] > threshold
            ]

            # Marquer comme visités
            visited.update(similar_indices)

            # Groupe de concepts similaires
            group_concepts = [concepts[j] for j in similar_indices]
            canonical_groups.append(group_concepts)

            logger.debug(
                f"[OSMOSE] Cluster {len(canonical_groups)}: "
                f"{len(group_concepts)} concepts "
                f"(lead: '{concepts[i].name}')"
            )

        return canonical_groups

    async def _build_canonical_concept(
        self,
        concepts: List[Concept]
    ) -> CanonicalConcept:
        """
        Construit un CanonicalConcept à partir d'un groupe de concepts similaires.

        Étapes:
        1. Sélectionner nom canonique (priorité anglais)
        2. Collecter aliases (toutes variantes)
        3. Détecter langues représentées
        4. Générer définition unifiée (LLM si plusieurs définitions)
        5. Calculer confiance moyenne

        Args:
            concepts: Groupe de concepts similaires

        Returns:
            CanonicalConcept unifié
        """
        # 1. Nom canonique
        canonical_name = self._select_canonical_name(concepts)

        # 2. Aliases (dédupliqués)
        aliases = list(set(c.name for c in concepts))

        # 3. Langues
        languages = list(set(c.language for c in concepts))

        # 4. Type (majoritaire)
        concept_type = self._select_concept_type(concepts)

        # 5. Définition unifiée
        definition = await self._generate_unified_definition(concepts)

        # 6. Confidence
        avg_confidence = sum(c.confidence for c in concepts) / len(concepts)

        # 7. Support
        support = len(concepts)

        canonical = CanonicalConcept(
            canonical_name=canonical_name,
            aliases=aliases,
            languages=languages,
            type=concept_type,
            definition=definition,
            hierarchy_parent=None,
            hierarchy_children=[],
            related_concepts=[],
            source_concepts=concepts,
            support=support,
            confidence=avg_confidence
        )

        logger.debug(
            f"[OSMOSE] Canonical concept created: '{canonical_name}' "
            f"({support} sources, {len(languages)} languages)"
        )

        return canonical

    def _select_canonical_name(
        self,
        concepts: List[Concept]
    ) -> str:
        """
        Sélectionne nom canonique avec priorité anglais.

        Stratégie:
        1. Si concepts anglais existent → prendre le plus court
        2. Sinon → prendre le plus fréquent
        3. Sinon → prendre le premier

        Args:
            concepts: Groupe de concepts

        Returns:
            Nom canonique sélectionné
        """
        # Priorité 1: Anglais
        priority_lang = self.indexing_config.canonical_name_priority
        lang_concepts = [c for c in concepts if c.language == priority_lang]

        if lang_concepts:
            # Prendre le plus court (souvent plus générique)
            return min(lang_concepts, key=lambda c: len(c.name)).name

        # Priorité 2: Plus fréquent
        names = [c.name for c in concepts]
        name_counts = Counter(names)
        most_common = name_counts.most_common(1)

        if most_common:
            return most_common[0][0]

        # Fallback: premier
        return concepts[0].name

    def _select_concept_type(
        self,
        concepts: List[Concept]
    ) -> ConceptType:
        """
        Sélectionne le type de concept majoritaire.

        Args:
            concepts: Groupe de concepts

        Returns:
            ConceptType majoritaire
        """
        type_counts = Counter(c.type for c in concepts)
        most_common_type = type_counts.most_common(1)[0][0]
        return most_common_type

    async def _generate_unified_definition(
        self,
        concepts: List[Concept]
    ) -> str:
        """
        Génère définition unifiée via LLM.

        Stratégies:
        - Si 0 définitions → ""
        - Si 1 définition → retourner telle quelle
        - Si 2+ définitions → fusion LLM

        Args:
            concepts: Groupe de concepts

        Returns:
            Définition unifiée (ou vide)
        """
        definitions = [c.definition for c in concepts if c.definition]

        if not definitions:
            return ""

        if len(definitions) == 1:
            return definitions[0]

        # Fusion LLM
        try:
            prompt = f"""Synthesize a single, concise definition from these multiple definitions of the same concept:

{json.dumps(definitions, indent=2, ensure_ascii=False)}

Return a unified definition (1-2 sentences, clear, technical).
Keep the most important information from all definitions.
Use English if possible."""

            from knowbase.common.llm_router import TaskType

            unified = self.llm_router.complete(
                task_type=TaskType.SHORT_ENRICHMENT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200
            ).strip()

            logger.debug(
                f"[OSMOSE] Unified definition generated "
                f"(from {len(definitions)} sources)"
            )

            return unified

        except Exception as e:
            logger.warning(
                f"[OSMOSE] Failed to generate unified definition: {e}. "
                "Using longest definition."
            )
            return max(definitions, key=len)

    async def _build_hierarchy(
        self,
        canonical_concepts: List[CanonicalConcept]
    ) -> List[CanonicalConcept]:
        """
        Construit hiérarchie parent-child via LLM.

        Utilise LLM pour identifier relations hiérarchiques:
        - Parent: Concept plus général ("Security Testing")
        - Children: Concepts plus spécifiques ("SAST", "DAST")

        Args:
            canonical_concepts: Liste de concepts canoniques

        Returns:
            Concepts avec hiérarchies remplies
        """
        if len(canonical_concepts) < 2:
            return canonical_concepts

        # Limiter à 50 concepts pour LLM (éviter prompt trop long)
        if len(canonical_concepts) > 50:
            logger.warning(
                f"[OSMOSE] Too many concepts ({len(canonical_concepts)}) for hierarchy. "
                "Using top 50 by support."
            )
            canonical_concepts_sorted = sorted(
                canonical_concepts,
                key=lambda c: c.support,
                reverse=True
            )
            concepts_for_hierarchy = canonical_concepts_sorted[:50]
        else:
            concepts_for_hierarchy = canonical_concepts

        concept_names = [c.canonical_name for c in concepts_for_hierarchy]

        try:
            prompt = f"""Analyze these concepts and identify hierarchical relationships (parent-child).

A parent concept is more general, a child concept is more specific.
Example: "Security Testing" (parent) → "SAST", "DAST" (children)

Concepts:
{json.dumps(concept_names, indent=2, ensure_ascii=False)}

Return JSON with hierarchies array:
{{
  "hierarchies": [
    {{"parent": "Security Testing", "children": ["SAST", "DAST", "Penetration Testing"]}},
    {{"parent": "Authentication", "children": ["MFA", "SSO", "Biometric"]}}
  ]
}}

Only include clear hierarchies. If no hierarchies, return empty array."""

            from knowbase.common.llm_router import TaskType

            content = self.llm_router.complete(
                task_type=TaskType.SHORT_ENRICHMENT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000
            )

            data = json.loads(content)

            hierarchies = data.get("hierarchies", [])

            if not hierarchies:
                logger.info("[OSMOSE] No hierarchies identified by LLM")
                return canonical_concepts

            # Appliquer hiérarchies
            concept_by_name = {c.canonical_name: c for c in canonical_concepts}

            for hierarchy in hierarchies:
                parent_name = hierarchy.get("parent")
                children_names = hierarchy.get("children", [])

                if parent_name in concept_by_name:
                    parent = concept_by_name[parent_name]
                    parent.hierarchy_children = children_names

                    for child_name in children_names:
                        if child_name in concept_by_name:
                            child = concept_by_name[child_name]
                            child.hierarchy_parent = parent_name

                    logger.debug(
                        f"[OSMOSE] Hierarchy: '{parent_name}' → "
                        f"{children_names}"
                    )

            logger.info(
                f"[OSMOSE] ✅ Built {len(hierarchies)} hierarchies"
            )

            return canonical_concepts

        except Exception as e:
            logger.warning(
                f"[OSMOSE] Failed to build hierarchy: {e}. "
                "Skipping hierarchy construction."
            )
            return canonical_concepts

    async def _extract_relations(
        self,
        canonical_concepts: List[CanonicalConcept]
    ) -> List[CanonicalConcept]:
        """
        Extrait relations sémantiques via embeddings similarity.

        Pour chaque concept:
        - Calculer similarité avec tous autres concepts
        - Prendre top-5 similaires (threshold 0.70)
        - Exclure hiérarchies (déjà gérées)

        Args:
            canonical_concepts: Liste de concepts canoniques

        Returns:
            Concepts avec related_concepts remplis
        """
        if len(canonical_concepts) < 2:
            return canonical_concepts

        # Embeddings
        concept_names = [c.canonical_name for c in canonical_concepts]
        embeddings = self.embedder.encode(concept_names)

        # Similarity matrix
        sim_matrix = cosine_similarity(embeddings)

        # Pour chaque concept, top-5 similaires
        relation_threshold = self.indexing_config.deduplication_threshold - 0.20  # 0.70

        for i, concept in enumerate(canonical_concepts):
            similarities = sim_matrix[i].copy()

            # Exclure soi-même
            similarities[i] = -1

            # Exclure parent/children (déjà dans hiérarchie)
            hierarchical_names = set()
            if concept.hierarchy_parent:
                hierarchical_names.add(concept.hierarchy_parent)
            hierarchical_names.update(concept.hierarchy_children)

            for j, other_concept in enumerate(canonical_concepts):
                if other_concept.canonical_name in hierarchical_names:
                    similarities[j] = -1

            # Top-5 similaires
            top_indices = similarities.argsort()[-5:][::-1]
            top_concepts = [
                canonical_concepts[j].canonical_name
                for j in top_indices
                if similarities[j] > relation_threshold
            ]

            concept.related_concepts = top_concepts

            if top_concepts:
                logger.debug(
                    f"[OSMOSE] Relations for '{concept.canonical_name}': "
                    f"{top_concepts}"
                )

        logger.info(
            f"[OSMOSE] ✅ Extracted relations for {len(canonical_concepts)} concepts"
        )

        return canonical_concepts

    def calculate_quality_score(
        self,
        canonical_concept: CanonicalConcept
    ) -> float:
        """
        Calcule score de qualité pour gatekeeper Proto-KG.

        Critères:
        - Support (nombre sources): +0.3
        - Cross-lingual (multi-langues): +0.2
        - Définition présente: +0.2
        - Hiérarchie (parent ou children): +0.15
        - Relations: +0.15

        Score max: 1.0

        Args:
            canonical_concept: Concept canonique

        Returns:
            Score de qualité [0.0, 1.0]
        """
        score = 0.0

        # Support
        if canonical_concept.support >= 5:
            score += 0.3
        elif canonical_concept.support >= 3:
            score += 0.2
        elif canonical_concept.support >= 2:
            score += 0.1

        # Cross-lingual
        if len(canonical_concept.languages) >= 3:
            score += 0.2
        elif len(canonical_concept.languages) >= 2:
            score += 0.15

        # Définition
        if canonical_concept.definition:
            score += 0.2

        # Hiérarchie
        if canonical_concept.hierarchy_parent or canonical_concept.hierarchy_children:
            score += 0.15

        # Relations
        if canonical_concept.related_concepts:
            score += 0.15

        return min(score, 1.0)
