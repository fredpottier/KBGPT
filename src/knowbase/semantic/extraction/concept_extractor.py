"""
🌊 OSMOSE Semantic Intelligence V2.1 - Concept Extractor

Extraction multilingue de concepts via triple méthode (NER + Clustering + LLM)
"""

from typing import List, Dict, Optional, Tuple
import numpy as np
from collections import Counter
import logging
import json
import re

from sklearn.metrics.pairwise import cosine_distances
from hdbscan import HDBSCAN

from ..models import Concept, Topic, ConceptType
from ..utils.embeddings import get_embedder
from ..utils.ner_manager import get_ner_manager
from ..utils.language_detector import get_language_detector
from .concept_density_detector import ConceptDensityDetector, ExtractionMethod

logger = logging.getLogger(__name__)


class MultilingualConceptExtractor:
    """
    Extracteur de concepts multilingue via triple méthode.

    Pipeline:
    1. NER Multilingue (rapide, haute précision)
    2. Semantic Clustering (grouping sémantique via embeddings)
    3. LLM Structured Extraction (contexte, haute recall)
    4. Fusion + Déduplication
    5. Typage automatique (ENTITY, PRACTICE, STANDARD, TOOL, ROLE)

    ⚠️ COMPOSANT CRITIQUE Phase 1 V2.1

    Phase 1 V2.1 - Semaines 5-7
    """

    def __init__(self, llm_router, config):
        """
        Initialise l'extracteur de concepts.

        Args:
            llm_router: LLMRouter pour extraction LLM
            config: Configuration SemanticConfig
        """
        self.llm_router = llm_router
        self.config = config
        self.extraction_config = config.extraction

        # Composants utils
        self.ner = get_ner_manager(config)
        self.embedder = get_embedder(config)
        self.language_detector = get_language_detector(config)

        # V2.2: Density Detector pour optimisation méthode extraction
        self.density_detector = ConceptDensityDetector(ner_manager=self.ner)

        logger.info(
            f"[OSMOSE] MultilingualConceptExtractor initialisé "
            f"(methods={self.extraction_config.methods}, density_detection=enabled)"
        )

    async def extract_concepts(
        self,
        topic: Topic,
        enable_llm: bool = True
    ) -> List[Concept]:
        """
        Extrait concepts d'un topic via méthode optimisée (V2.2 Density-Aware).

        Pipeline V2.2:
        0. Analyse densité conceptuelle → Sélection méthode optimale
        1. NER Multilingue (si recommandé)
        2. Semantic Clustering (si recommandé)
        3. LLM (si insuffisant OU texte dense)
        4. Fusion + Déduplication
        5. Typage automatique

        Args:
            topic: Topic à analyser
            enable_llm: Activer extraction LLM (default: True)

        Returns:
            List[Concept]: Concepts extraits et dédupliqués
        """
        logger.info(f"[OSMOSE] Extracting concepts from topic: {topic.topic_id}")

        concepts = []

        # Détection langue topic
        topic_text = " ".join([w.text for w in topic.windows])
        topic_language = self.language_detector.detect(topic_text[:2000])
        logger.debug(f"[OSMOSE] Topic language: {topic_language}")

        # V2.2: Analyse densité conceptuelle pour optimisation
        density_profile = self.density_detector.analyze_density(
            text=topic_text,
            sample_size=min(len(topic_text), 2000),
            language=topic_language
        )

        logger.info(
            f"[OSMOSE] Density Analysis: {density_profile.recommended_method.value} "
            f"(score={density_profile.density_score:.2f}, confidence={density_profile.confidence:.2f})"
        )

        # Stratégie selon densité détectée
        if density_profile.recommended_method == ExtractionMethod.LLM_FIRST:
            # Texte dense → LLM d'emblée (skip NER inefficace)
            logger.info("[OSMOSE] Dense text detected → LLM-first strategy")
            if enable_llm and "LLM" in self.extraction_config.methods:
                concepts_llm = await self._extract_via_llm(topic, topic_language)
                concepts.extend(concepts_llm)
                logger.info(f"[OSMOSE] LLM: {len(concepts_llm)} concepts")
            else:
                logger.warning("[OSMOSE] LLM disabled but recommended for dense text, falling back to NER")
                # Fallback NER si LLM désactivé
                if "NER" in self.extraction_config.methods:
                    concepts_ner = await self._extract_via_ner(topic, topic_language)
                    concepts.extend(concepts_ner)

        elif density_profile.recommended_method == ExtractionMethod.NER_ONLY:
            # Texte simple → NER suffit
            logger.info("[OSMOSE] Simple text detected → NER-only strategy")
            if "NER" in self.extraction_config.methods:
                concepts_ner = await self._extract_via_ner(topic, topic_language)
                concepts.extend(concepts_ner)
                logger.info(f"[OSMOSE] NER: {len(concepts_ner)} concepts")

        else:  # NER_LLM_HYBRID (standard flow)
            # Pipeline standard: NER + Clustering + LLM si insuffisant
            logger.info("[OSMOSE] Standard text → Hybrid NER+LLM strategy")

            # Méthode 1: NER Multilingue
            if "NER" in self.extraction_config.methods:
                concepts_ner = await self._extract_via_ner(topic, topic_language)
                concepts.extend(concepts_ner)
                logger.info(f"[OSMOSE] NER: {len(concepts_ner)} concepts")

            # Méthode 2: Semantic Clustering
            if "CLUSTERING" in self.extraction_config.methods:
                concepts_clustering = await self._extract_via_clustering(topic, topic_language)
                concepts.extend(concepts_clustering)
                logger.info(f"[OSMOSE] Clustering: {len(concepts_clustering)} concepts")

            # Méthode 3: LLM (si insuffisant)
            if enable_llm and "LLM" in self.extraction_config.methods:
                if len(concepts) < self.extraction_config.min_concepts_per_topic:
                    concepts_llm = await self._extract_via_llm(topic, topic_language)
                    concepts.extend(concepts_llm)
                    logger.info(f"[OSMOSE] LLM: {len(concepts_llm)} concepts")
                else:
                    logger.debug("[OSMOSE] LLM skipped (enough concepts from NER+Clustering)")

        # Fusion + Déduplication
        concepts_deduplicated = self._deduplicate_concepts(concepts)
        logger.info(
            f"[OSMOSE] ✅ Extracted {len(concepts_deduplicated)} concepts "
            f"(from {len(concepts)} raw)"
        )

        # Limiter au max configuré
        if len(concepts_deduplicated) > self.extraction_config.max_concepts_per_topic:
            # Trier par confiance et garder top-k
            concepts_deduplicated.sort(key=lambda c: c.confidence, reverse=True)
            concepts_deduplicated = concepts_deduplicated[:self.extraction_config.max_concepts_per_topic]
            logger.debug(
                f"[OSMOSE] Limited to {self.extraction_config.max_concepts_per_topic} concepts"
            )

        return concepts_deduplicated

    async def _extract_via_ner(
        self,
        topic: Topic,
        language: str
    ) -> List[Concept]:
        """
        Extraction via NER multilingue (spaCy).

        Args:
            topic: Topic à analyser
            language: Langue détectée

        Returns:
            List[Concept]: Concepts extraits via NER
        """
        topic_text = " ".join([w.text for w in topic.windows])

        # NER extraction
        entities = self.ner.extract_entities(topic_text, language=language)

        if not entities:
            logger.debug("[OSMOSE] NER: No entities found")
            return []

        concepts = []
        for ent in entities:
            # Mapper label NER → ConceptType
            concept_type = self._map_ner_label_to_concept_type(ent["label"])

            # Contexte (100 chars avant/après)
            context_start = max(0, ent["start"] - 100)
            context_end = min(len(topic_text), ent["end"] + 100)
            context = topic_text[context_start:context_end]

            concept = Concept(
                name=ent["text"],
                type=concept_type,
                definition="",  # Enrichi plus tard si besoin
                context=context,
                language=language,
                confidence=0.85,  # NER haute confiance
                source_topic_id=topic.topic_id,
                extraction_method="NER",
                related_concepts=[]
            )
            concepts.append(concept)

        return concepts

    async def _extract_via_clustering(
        self,
        topic: Topic,
        language: str
    ) -> List[Concept]:
        """
        Extraction via clustering sémantique (embeddings).

        Extrait noun phrases → embeddings → HDBSCAN clustering → concepts

        Args:
            topic: Topic à analyser
            language: Langue détectée

        Returns:
            List[Concept]: Concepts extraits via clustering
        """
        # Extraire noun phrases candidates
        noun_phrases = self._extract_noun_phrases(topic, language)

        if len(noun_phrases) < 3:
            logger.debug("[OSMOSE] Clustering: Not enough noun phrases (<3)")
            return []

        # Embeddings
        embeddings = self.embedder.encode(noun_phrases)

        # Clustering HDBSCAN (euclidean sur embeddings normalisés = cosine distance)
        try:
            clusterer = HDBSCAN(
                min_cluster_size=max(2, len(noun_phrases) // 10),
                metric='euclidean',
                cluster_selection_method='eom',
                min_samples=1
            )
            cluster_labels = clusterer.fit_predict(embeddings)

            unique_labels = set(cluster_labels)
            if -1 in unique_labels:
                unique_labels.remove(-1)  # Ignorer noise

            if len(unique_labels) == 0:
                logger.debug("[OSMOSE] Clustering: No clusters found")
                return []

        except Exception as e:
            logger.warning(f"[OSMOSE] Clustering failed: {e}")
            return []

        # Pour chaque cluster → créer concept
        concepts = []
        for cluster_id in unique_labels:
            # Phrases du cluster
            cluster_mask = cluster_labels == cluster_id
            cluster_phrases = [noun_phrases[i] for i, mask in enumerate(cluster_mask) if mask]
            cluster_embeddings = embeddings[cluster_mask]

            if len(cluster_phrases) == 0:
                continue

            # Phrase centrale = canonical name (plus proche du centroid)
            centroid = cluster_embeddings.mean(axis=0)
            distances = cosine_distances(cluster_embeddings, [centroid]).flatten()
            most_central_idx = distances.argmin()
            canonical_name = cluster_phrases[most_central_idx]

            # Type concept (heuristique basique)
            concept_type = self._infer_concept_type_heuristic(canonical_name, cluster_phrases)

            # Contexte
            topic_text = " ".join([w.text for w in topic.windows])
            context = topic_text[:200]

            concept = Concept(
                name=canonical_name,
                type=concept_type,
                definition="",
                context=context,
                language=language,
                confidence=0.75,  # Clustering confidence moyenne
                source_topic_id=topic.topic_id,
                extraction_method="CLUSTERING",
                related_concepts=cluster_phrases[:5]  # Top 5 related
            )
            concepts.append(concept)

        return concepts

    async def _extract_via_llm(
        self,
        topic: Topic,
        language: str
    ) -> List[Concept]:
        """
        Extraction via LLM avec prompt structuré multilingue.

        Args:
            topic: Topic à analyser
            language: Langue détectée

        Returns:
            List[Concept]: Concepts extraits via LLM
        """
        if not self.llm_router:
            logger.warning("[OSMOSE] LLM extraction disabled (no llm_router)")
            return []

        topic_text = " ".join([w.text for w in topic.windows])

        # Limiter longueur pour LLM (max 2000 chars)
        if len(topic_text) > 2000:
            topic_text = topic_text[:2000] + "..."

        # Prompt selon langue
        prompt = self._get_llm_extraction_prompt(topic_text, language)

        try:
            # Appel LLM
            from knowbase.common.llm_router import TaskType

            response_text = self.llm_router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.extraction_config.llm["temperature"],
                max_tokens=self.extraction_config.llm["max_tokens"]
            )

            # Parser JSON response
            concepts_data = self._parse_llm_response(response_text)

            if not concepts_data:
                logger.warning("[OSMOSE] LLM: Failed to parse response")
                return []

            # Créer objets Concept
            concepts = []
            for concept_dict in concepts_data:
                try:
                    concept_type = ConceptType(concept_dict.get("type", "entity").lower())
                except ValueError:
                    concept_type = ConceptType.ENTITY

                concept = Concept(
                    name=concept_dict["name"],
                    type=concept_type,
                    definition=concept_dict.get("definition", ""),
                    context=topic_text[:200],
                    language=language,
                    confidence=0.80,  # LLM confidence
                    source_topic_id=topic.topic_id,
                    extraction_method="LLM",
                    related_concepts=concept_dict.get("relationships", [])
                )
                concepts.append(concept)

            return concepts

        except Exception as e:
            logger.error(f"[OSMOSE] LLM extraction failed: {e}")
            return []

    def _deduplicate_concepts(self, concepts: List[Concept]) -> List[Concept]:
        """
        Déduplique concepts similaires.

        Stratégie:
        1. Grouper par nom exact (case-insensitive)
        2. Grouper par similarité embeddings (threshold 0.90)
        3. Garder concept avec confiance maximale

        Args:
            concepts: Liste concepts bruts

        Returns:
            List[Concept]: Concepts dédupliqués
        """
        if not concepts:
            return []

        # Étape 1: Déduplication par nom exact (case-insensitive)
        seen_names = {}
        for concept in concepts:
            name_lower = concept.name.lower().strip()

            if name_lower in seen_names:
                # Garder concept avec confiance max
                if concept.confidence > seen_names[name_lower].confidence:
                    seen_names[name_lower] = concept
            else:
                seen_names[name_lower] = concept

        concepts_dedup_exact = list(seen_names.values())

        # Étape 2: Déduplication par similarité embeddings
        if len(concepts_dedup_exact) < 2:
            return concepts_dedup_exact

        # Embeddings
        names = [c.name for c in concepts_dedup_exact]
        embeddings = self.embedder.encode(names)

        # Matrice similarité
        from sklearn.metrics.pairwise import cosine_similarity
        sim_matrix = cosine_similarity(embeddings)

        # Grouper concepts similaires (threshold 0.90)
        threshold = 0.90
        grouped = []
        visited = set()

        for i in range(len(concepts_dedup_exact)):
            if i in visited:
                continue

            group = [i]
            for j in range(i + 1, len(concepts_dedup_exact)):
                if j in visited:
                    continue

                if sim_matrix[i][j] >= threshold:
                    group.append(j)
                    visited.add(j)

            grouped.append(group)
            visited.add(i)

        # Pour chaque groupe, garder concept avec confiance max
        deduplicated = []
        for group in grouped:
            group_concepts = [concepts_dedup_exact[i] for i in group]
            best_concept = max(group_concepts, key=lambda c: c.confidence)
            deduplicated.append(best_concept)

        logger.debug(
            f"[OSMOSE] Deduplication: {len(concepts)} → "
            f"{len(concepts_dedup_exact)} (exact) → "
            f"{len(deduplicated)} (similarity)"
        )

        return deduplicated

    def _extract_noun_phrases(
        self,
        topic: Topic,
        language: str
    ) -> List[str]:
        """
        Extrait noun phrases candidates pour clustering.

        Utilise NER + patterns simples.

        Args:
            topic: Topic à analyser
            language: Langue

        Returns:
            List[str]: Noun phrases
        """
        topic_text = " ".join([w.text for w in topic.windows])

        # Méthode 1: Via NER (toujours des noun phrases)
        entities = self.ner.extract_entities(topic_text, language=language)
        noun_phrases = [ent["text"] for ent in entities]

        # Méthode 2: Patterns simples (capitalized words, 2-4 mots)
        # Pattern: Capitalized Word(s) de 2-4 tokens
        pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b'
        matches = re.findall(pattern, topic_text)
        noun_phrases.extend(matches)

        # Dédupliquer
        noun_phrases = list(set(noun_phrases))

        # Filtrer longueur (2-50 chars)
        noun_phrases = [
            np for np in noun_phrases
            if 2 <= len(np) <= 50
        ]

        return noun_phrases

    def _map_ner_label_to_concept_type(self, ner_label: str) -> ConceptType:
        """
        Mappe label NER spaCy → ConceptType.

        Args:
            ner_label: Label NER (ORG, PRODUCT, LAW, etc.)

        Returns:
            ConceptType: Type concept mappé
        """
        mapping = {
            "ORG": ConceptType.ENTITY,
            "PRODUCT": ConceptType.TOOL,
            "LAW": ConceptType.STANDARD,
            "TECH": ConceptType.TOOL,
            "MISC": ConceptType.ENTITY,
        }

        return mapping.get(ner_label, ConceptType.ENTITY)

    def _infer_concept_type_heuristic(
        self,
        canonical_name: str,
        related_phrases: List[str]
    ) -> ConceptType:
        """
        Infère type concept via heuristique basique.

        Args:
            canonical_name: Nom canonique
            related_phrases: Phrases liées

        Returns:
            ConceptType: Type inféré
        """
        name_lower = canonical_name.lower()

        # Keywords par type
        tool_keywords = ["tool", "system", "platform", "software", "solution"]
        standard_keywords = ["standard", "norm", "iso", "regulation", "framework", "gdpr", "compliance"]
        practice_keywords = ["process", "methodology", "approach", "practice", "method"]
        role_keywords = ["manager", "officer", "architect", "analyst", "engineer", "champion"]

        # Check keywords
        if any(kw in name_lower for kw in tool_keywords):
            return ConceptType.TOOL
        elif any(kw in name_lower for kw in standard_keywords):
            return ConceptType.STANDARD
        elif any(kw in name_lower for kw in practice_keywords):
            return ConceptType.PRACTICE
        elif any(kw in name_lower for kw in role_keywords):
            return ConceptType.ROLE

        # Default: ENTITY
        return ConceptType.ENTITY

    def _get_llm_extraction_prompt(self, text: str, language: str) -> str:
        """
        Génère prompt LLM extraction selon langue.

        Args:
            text: Texte à analyser
            language: Langue (en, fr, de, etc.)

        Returns:
            str: Prompt formaté
        """
        prompts = {
            "en": """Extract key concepts from the following text.

For each concept, identify:
- name: the concept name (2-50 characters)
- type: one of [ENTITY, PRACTICE, STANDARD, TOOL, ROLE]
- definition: a brief definition (1 sentence)
- relationships: list of related concept names (max 3)

Text:
{text}

Return a JSON object with this exact structure:
{{"concepts": [{{"name": "...", "type": "...", "definition": "...", "relationships": [...]}}]}}

Extract 3-10 concepts maximum. Focus on the most important ones.""",

            "fr": """Extrait les concepts clés du texte suivant.

Pour chaque concept, identifie :
- name : le nom du concept (2-50 caractères)
- type : un parmi [ENTITY, PRACTICE, STANDARD, TOOL, ROLE]
- definition : une brève définition (1 phrase)
- relationships : liste de noms de concepts liés (max 3)

Texte :
{text}

Retourne un objet JSON avec cette structure exacte:
{{"concepts": [{{"name": "...", "type": "...", "definition": "...", "relationships": [...]}}]}}

Extrait 3-10 concepts maximum. Focus sur les plus importants.""",

            "de": """Extrahiere die Schlüsselkonzepte aus folgendem Text.

Für jedes Konzept identifiziere:
- name: der Konzeptname (2-50 Zeichen)
- type: eines von [ENTITY, PRACTICE, STANDARD, TOOL, ROLE]
- definition: eine kurze Definition (1 Satz)
- relationships: Liste verwandter Konzeptnamen (max 3)

Text:
{text}

Gib ein JSON-Objekt mit dieser exakten Struktur zurück:
{{"concepts": [{{"name": "...", "type": "...", "definition": "...", "relationships": [...]}}]}}

Extrahiere maximal 3-10 Konzepte. Fokus auf die wichtigsten."""
        }

        # Fallback anglais si langue non supportée
        template = prompts.get(language, prompts["en"])
        return template.format(text=text)

    def _parse_llm_response(self, response_text: str) -> List[Dict]:
        """
        Parse réponse LLM JSON.

        Args:
            response_text: Réponse LLM brute

        Returns:
            List[Dict]: Concepts parsés, ou [] si erreur
        """
        try:
            # Chercher JSON dans la réponse (peut avoir du texte avant/après)
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                logger.warning("[OSMOSE] No JSON found in LLM response")
                return []

            json_str = json_match.group(0)
            data = json.loads(json_str)

            if "concepts" not in data:
                logger.warning("[OSMOSE] No 'concepts' key in LLM response")
                return []

            concepts = data["concepts"]

            # Valider structure
            valid_concepts = []
            for concept in concepts:
                if "name" in concept and "type" in concept:
                    valid_concepts.append(concept)

            return valid_concepts

        except json.JSONDecodeError as e:
            logger.error(f"[OSMOSE] Failed to parse LLM JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"[OSMOSE] Error parsing LLM response: {e}")
            return []


# ===================================
# FACTORY PATTERN
# ===================================

_extractor_instance: Optional[MultilingualConceptExtractor] = None


def get_concept_extractor(config, llm_router=None) -> MultilingualConceptExtractor:
    """
    Récupère l'instance singleton de l'extracteur.

    Args:
        config: Configuration SemanticConfig
        llm_router: LLMRouter (optionnel)

    Returns:
        MultilingualConceptExtractor: Instance unique
    """
    global _extractor_instance

    if _extractor_instance is None:
        _extractor_instance = MultilingualConceptExtractor(config, llm_router)

    return _extractor_instance
