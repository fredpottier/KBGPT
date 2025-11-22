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

from knowbase.semantic.models import Concept, CanonicalConcept
from knowbase.semantic.config import SemanticConfig, IndexingConfig
from knowbase.semantic.utils.embeddings import get_embedder
from knowbase.common.llm_router import LLMRouter

logger = logging.getLogger(__name__)


# Phase 1.8 T1.8.1.7b - LLM-as-a-Judge System Prompt
LLM_JUDGE_SYSTEM_PROMPT = """You are an expert knowledge graph curator specializing in concept validation.

Your role is to determine whether clustered concepts should be merged into a single canonical concept or kept separate.

You must be PRECISE and CONSERVATIVE:
- Only approve merges for TRUE synonyms, translations, or equivalent terms
- Reject merges for related but semantically distinct concepts
- Consider domain-specific nuances (e.g., product names, technical terms)

Always provide clear reasoning for your decision."""


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

        # 3b. Phase 1.8 T1.8.1.7b: Validation LLM-as-a-Judge (optionnelle)
        if self.indexing_config.llm_judge_validation:
            logger.info("[OSMOSE:Phase1.8] 🔍 Validating clusters via LLM-as-a-Judge")
            validated_groups = []
            rejected_count = 0
            validated_count = 0

            for group in canonical_groups:
                # Skip validation for single concepts or small clusters
                if len(group) < self.indexing_config.llm_judge_min_cluster_size:
                    validated_groups.append(group)
                    continue

                # Validate cluster via LLM
                is_valid = await self._validate_cluster_via_llm(
                    group,
                    threshold=self.indexing_config.similarity_threshold
                )

                if is_valid:
                    validated_groups.append(group)
                    validated_count += 1
                else:
                    # Rejected cluster: split into individual concepts
                    for concept in group:
                        validated_groups.append([concept])
                    rejected_count += 1
                    logger.warning(
                        f"[OSMOSE:Phase1.8] ❌ Rejected cluster: "
                        f"{[c.name for c in group]} (split into {len(group)} individual concepts)"
                    )

            canonical_groups = validated_groups
            logger.info(
                f"[OSMOSE:Phase1.8] ✅ LLM-as-a-Judge validation complete: "
                f"{validated_count} clusters approved, {rejected_count} clusters rejected, "
                f"final groups: {len(canonical_groups)}"
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

    async def _validate_cluster_via_llm(
        self,
        concepts: List[Concept],
        threshold: float = 0.85
    ) -> bool:
        """
        Valide un cluster de concepts via LLM-as-a-Judge (Phase 1.8 T1.8.1.7b).

        Inspiration: KGGen Paper Section 3.3 - Iterative Clustering with LLM Validation

        Problème résolu:
        Le clustering par similarité d'embeddings peut créer des faux positifs:
        - "security" et "compliance" (similaires mais pas synonymes)
        - "SAP ERP" et "SAP S/4HANA" (liés mais produits distincts)

        Solution:
        Demander au LLM de valider si les concepts sont vraiment équivalents/synonymes.

        Args:
            concepts: Liste de concepts à valider (déjà clustérisés par similarité)
            threshold: Seuil similarité ayant créé le cluster (pour contexte)

        Returns:
            bool: True si cluster valide (concepts synonymes), False sinon

        Example:
            >>> concepts = [
            ...     Concept(name="authentication", ...),
            ...     Concept(name="authentification", ...)  # FR equivalent
            ... ]
            >>> await indexer._validate_cluster_via_llm(concepts)
            True  # Vraiment synonymes

            >>> concepts = [
            ...     Concept(name="security", ...),
            ...     Concept(name="compliance", ...)  # Proches mais distincts
            ... ]
            >>> await indexer._validate_cluster_via_llm(concepts)
            False  # Pas synonymes, garder séparés
        """
        # Skip validation si cluster trop petit (1 seul concept = pas de fusion)
        if len(concepts) <= 1:
            logger.debug(
                f"[OSMOSE:LLM-Judge] Cluster size=1, validation skipped (no merge needed)"
            )
            return True

        # Extraire noms pour validation
        concept_names = [c.name for c in concepts]

        # Limiter validation aux clusters raisonnables (max 5 concepts)
        if len(concepts) > 5:
            logger.warning(
                f"[OSMOSE:LLM-Judge] Cluster size={len(concepts)} > 5, "
                f"validation may be unreliable. Consider lowering similarity threshold."
            )

        # Construire prompt LLM-as-a-Judge
        prompt = self._build_llm_judge_prompt(concept_names, threshold)

        try:
            from knowbase.common.llm_router import TaskType

            logger.info(
                f"[OSMOSE:LLM-Judge] Validating cluster: {concept_names} "
                f"(similarity > {threshold})"
            )

            # Appel LLM avec temperature basse (déterministe)
            response_text = await self.llm_router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[
                    {
                        "role": "system",
                        "content": LLM_JUDGE_SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.0,  # Déterministe
                response_format={"type": "json_object"},
                max_tokens=500
            )

            # Parser réponse JSON
            result = self._parse_llm_judge_response(response_text)

            if result is None:
                logger.warning(
                    f"[OSMOSE:LLM-Judge] Failed to parse LLM response, "
                    f"defaulting to ACCEPT cluster (conservative)"
                )
                return True  # Conservative: accepter si parsing échoue

            is_valid = result.get("are_synonyms", True)
            reasoning = result.get("reasoning", "N/A")

            logger.info(
                f"[OSMOSE:LLM-Judge] {'✅ ACCEPT' if is_valid else '❌ REJECT'} cluster: "
                f"{concept_names} | Reasoning: {reasoning}"
            )

            return is_valid

        except Exception as e:
            logger.error(
                f"[OSMOSE:LLM-Judge] Validation failed: {e}, "
                f"defaulting to ACCEPT (conservative)",
                exc_info=True
            )
            return True  # Conservative: accepter en cas d'erreur

    def _build_llm_judge_prompt(
        self,
        concept_names: List[str],
        similarity_threshold: float
    ) -> str:
        """
        Construit prompt pour LLM-as-a-Judge validation.

        Args:
            concept_names: Liste de noms de concepts à valider
            similarity_threshold: Seuil similarité ayant créé le cluster

        Returns:
            str: Prompt formaté
        """
        concepts_list = "\n".join([f"- {name}" for name in concept_names])

        prompt = f"""You are validating a cluster of concepts that have high embedding similarity (> {similarity_threshold}).

**Concepts to validate:**
{concepts_list}

**Your task:**
Determine if these concepts are TRUE SYNONYMS or EQUIVALENT TERMS that should be merged into a single canonical concept.

**Guidelines:**
- ✅ MERGE if: concepts are translations, abbreviations, or true synonyms
  - Examples: "authentication" ↔ "authentification" (FR translation)
  - Examples: "CRM" ↔ "Customer Relationship Management" (abbreviation)

- ❌ KEEP SEPARATE if: concepts are related but semantically distinct
  - Examples: "security" ≠ "compliance" (related but different domains)
  - Examples: "SAP ERP" ≠ "SAP S/4HANA" (related products but distinct)
  - Examples: "cloud computing" ≠ "cloud storage" (different concepts)

**Return format (JSON):**
{{
  "are_synonyms": true/false,
  "reasoning": "Brief explanation (1 sentence)"
}}
"""
        return prompt

    def _parse_llm_judge_response(self, response_text: str) -> Optional[Dict]:
        """
        Parse réponse LLM-as-a-Judge.

        Args:
            response_text: Réponse LLM brute

        Returns:
            Dict avec {are_synonyms: bool, reasoning: str} ou None si erreur
        """
        try:
            # Extraire JSON de la réponse
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                logger.warning("[OSMOSE:LLM-Judge] No JSON found in response")
                return None

            data = json.loads(json_match.group(0))

            # Valider structure
            if "are_synonyms" not in data:
                logger.warning("[OSMOSE:LLM-Judge] Missing 'are_synonyms' in response")
                return None

            return {
                "are_synonyms": bool(data["are_synonyms"]),
                "reasoning": data.get("reasoning", "N/A")
            }

        except json.JSONDecodeError as e:
            logger.error(f"[OSMOSE:LLM-Judge] JSON parse error: {e}")
            return None
        except Exception as e:
            logger.error(f"[OSMOSE:LLM-Judge] Parse error: {e}")
            return None

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
    ) -> str:
        """
        Sélectionne le type de concept majoritaire.

        Args:
            concepts: Groupe de concepts

        Returns:
            Type majoritaire (str, normalized lowercase)
        """
        type_counts = Counter(c.type.lower() for c in concepts)
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
