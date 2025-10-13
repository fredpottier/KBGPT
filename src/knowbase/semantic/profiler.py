"""
🌊 OSMOSE Semantic Intelligence - Document Profiler

SemanticDocumentProfiler : Analyse l'intelligence sémantique d'un document
"""

from typing import List, Optional, Tuple
import logging
import json
import re
from .models import SemanticProfile, ComplexityZone, NarrativeThread
from .config import get_semantic_config
from knowbase.common.llm_router import LLMRouter, TaskType

logger = logging.getLogger(__name__)


class SemanticDocumentProfiler:
    """
    Analyse l'intelligence sémantique d'un document.

    Responsabilités:
    - Analyse de complexité (zones simple/medium/complex)
    - Détection préliminaire de fils narratifs
    - Classification domaine métier
    - Calcul budget token optimal

    Phase 1 - Semaines 3-4
    """

    def __init__(self):
        """Initialise le profiler avec la configuration"""
        self.config = get_semantic_config()
        self.profiler_config = self.config.profiler
        self.narrative_config = self.config.narrative_detection
        self.llm_router = LLMRouter()
        logger.info("[OSMOSE] SemanticDocumentProfiler initialisé")

    async def profile_document(
        self,
        document_id: str,
        document_path: str,
        tenant_id: str,
        text_content: str
    ) -> SemanticProfile:
        """
        Analyse le profil sémantique d'un document.

        Args:
            document_id: ID unique du document
            document_path: Chemin source du document
            tenant_id: ID du tenant
            text_content: Contenu textuel du document

        Returns:
            SemanticProfile: Profil sémantique complet
        """
        logger.info(f"[OSMOSE] Profiling document: {document_id}")

        # 1. Analyse de complexité
        overall_complexity, complexity_zones = self._analyze_complexity(text_content)
        logger.info(f"[OSMOSE] Complexity: {overall_complexity:.2f} ({len(complexity_zones)} zones)")

        # 2. Classification domaine
        domain, domain_confidence = self._classify_domain(text_content)
        logger.info(f"[OSMOSE] Domain: {domain} (confidence: {domain_confidence:.2f})")

        # 3. Détection fils narratifs préliminaire
        narrative_threads = self._detect_preliminary_narratives(text_content)
        logger.info(f"[OSMOSE] Narrative threads: {len(narrative_threads)} detected")

        # Construire le profil sémantique
        profile = SemanticProfile(
            document_id=document_id,
            document_path=document_path,
            tenant_id=tenant_id,
            overall_complexity=overall_complexity,
            domain=domain,
            domain_confidence=domain_confidence,
            complexity_zones=complexity_zones,
            narrative_threads=narrative_threads,
        )

        logger.info(f"[OSMOSE] ✅ Profile complete: {document_id}")
        return profile

    def _analyze_complexity(self, text: str) -> Tuple[float, List[ComplexityZone]]:
        """
        Analyse la complexité du texte par zones.

        Utilise LLM (gpt-4o-mini) pour analyser la densité conceptuelle,
        les interconnexions, et la profondeur du raisonnement.

        Returns:
            Tuple[overall_complexity, zones]
        """
        logger.info("[OSMOSE] Analyzing complexity...")

        # Si texte trop court, complexité faible
        if len(text) < 100:
            return 0.2, []

        # Diviser en segments (pour documents longs)
        max_chunk_length = 3000
        chunks = self._split_text_into_chunks(text, max_chunk_length)

        zones = []
        complexity_scores = []

        for i, chunk in enumerate(chunks):
            start_pos = i * max_chunk_length
            end_pos = start_pos + len(chunk)

            # Appel LLM pour analyser la complexité
            complexity_score, reasoning, key_concepts = self._analyze_chunk_complexity(chunk)

            # Déterminer le niveau
            level = self._complexity_score_to_level(complexity_score)

            zone = ComplexityZone(
                start_position=start_pos,
                end_position=end_pos,
                complexity_score=complexity_score,
                complexity_level=level,
                reasoning=reasoning,
                key_concepts=key_concepts
            )

            zones.append(zone)
            complexity_scores.append(complexity_score)

        # Complexité globale = moyenne pondérée
        overall_complexity = sum(complexity_scores) / len(complexity_scores) if complexity_scores else 0.5

        logger.info(f"[OSMOSE] Analyzed {len(zones)} complexity zones")
        return overall_complexity, zones

    def _split_text_into_chunks(self, text: str, max_length: int) -> List[str]:
        """Découpe le texte en chunks pour l'analyse"""
        if len(text) <= max_length:
            return [text]

        chunks = []
        current_pos = 0

        while current_pos < len(text):
            chunk = text[current_pos:current_pos + max_length]

            # Essayer de couper à une phrase complète
            if current_pos + max_length < len(text):
                last_period = chunk.rfind('.')
                last_newline = chunk.rfind('\n')
                cut_point = max(last_period, last_newline)

                if cut_point > max_length * 0.7:  # Au moins 70% du chunk
                    chunk = chunk[:cut_point + 1]

            chunks.append(chunk)
            current_pos += len(chunk)

        return chunks

    def _analyze_chunk_complexity(self, chunk: str) -> Tuple[float, str, List[str]]:
        """
        Analyse la complexité d'un chunk de texte via LLM.

        Returns:
            Tuple[score, reasoning, key_concepts]
        """
        prompt = f"""Analyze the semantic complexity of the following text segment.

Text segment:
\"\"\"
{chunk[:2000]}
\"\"\"

Evaluate the complexity on a scale from 0.0 to 1.0 based on:
- Conceptual density (number of distinct concepts)
- Interconnections between concepts
- Depth of reasoning required
- Technical terminology

Return a JSON object with:
{{
  "complexity_score": <float 0.0 to 1.0>,
  "reasoning": "<brief explanation>",
  "key_concepts": ["<concept1>", "<concept2>", ...]
}}

Complexity scale:
- 0.0-0.3: Simple, direct text
- 0.3-0.6: Medium complexity, some interconnected concepts
- 0.6-1.0: High complexity, dense technical content

JSON:"""

        try:
            response = self.llm_router.complete(
                task_type=TaskType.METADATA_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500
            )

            # Parser la réponse JSON
            response_clean = response.strip()
            if response_clean.startswith("```json"):
                response_clean = response_clean[7:]
            if response_clean.startswith("```"):
                response_clean = response_clean[3:]
            if response_clean.endswith("```"):
                response_clean = response_clean[:-3]
            response_clean = response_clean.strip()

            data = json.loads(response_clean)

            complexity_score = float(data.get("complexity_score", 0.5))
            reasoning = data.get("reasoning", "")
            key_concepts = data.get("key_concepts", [])

            return complexity_score, reasoning, key_concepts

        except Exception as e:
            logger.warning(f"[OSMOSE] Complexity analysis failed: {e}, using fallback")
            # Fallback : estimation simple
            word_count = len(chunk.split())
            complexity_score = min(0.3 + (word_count / 1000) * 0.4, 0.9)
            return complexity_score, "Automatic estimation", []

    def _complexity_score_to_level(self, score: float) -> str:
        """Convertit un score en niveau de complexité"""
        thresholds = self.profiler_config.complexity_thresholds

        if score < thresholds["simple"]:
            return "simple"
        elif score < thresholds["medium"]:
            return "medium"
        else:
            return "complex"

    def _detect_preliminary_narratives(self, text: str) -> List[NarrativeThread]:
        """
        Détection préliminaire de fils narratifs.

        Utilise des patterns simples (regex) pour détecter:
        - Causal connectors (because, therefore, etc.)
        - Temporal markers (revised, updated, etc.)
        - Cross-references

        Returns:
            List[NarrativeThread]: Fils narratifs détectés
        """
        logger.info("[OSMOSE] Detecting preliminary narratives...")

        threads = []

        # Patterns à détecter
        causal_connectors = self.narrative_config.causal_connectors
        temporal_markers = self.narrative_config.temporal_markers

        # Recherche de causal connectors
        for connector in causal_connectors:
            pattern = rf'\b{re.escape(connector)}\b'
            matches = list(re.finditer(pattern, text, re.IGNORECASE))

            if len(matches) >= 2:  # Au moins 2 occurrences
                # Créer un thread narratif basique
                first_match = matches[0]
                last_match = matches[-1]

                thread = NarrativeThread(
                    description=f"Causal narrative with '{connector}' ({len(matches)} occurrences)",
                    start_position=first_match.start(),
                    end_position=last_match.end(),
                    confidence=0.6,  # Confiance basse pour détection préliminaire
                    keywords=[connector],
                    causal_links=[connector],
                    temporal_markers=[]
                )
                threads.append(thread)

        # Recherche de temporal markers
        temporal_found = []
        for marker in temporal_markers:
            pattern = rf'\b{re.escape(marker)}\b'
            if re.search(pattern, text, re.IGNORECASE):
                temporal_found.append(marker)

        if len(temporal_found) >= 2:
            # Créer un thread temporel
            thread = NarrativeThread(
                description=f"Temporal narrative ({len(temporal_found)} markers)",
                start_position=0,
                end_position=len(text),
                confidence=0.65,
                keywords=temporal_found,
                causal_links=[],
                temporal_markers=temporal_found
            )
            threads.append(thread)

        logger.info(f"[OSMOSE] Detected {len(threads)} preliminary narrative threads")
        return threads

    def _classify_domain(self, text: str) -> Tuple[str, float]:
        """
        Classifie le domaine métier du document.

        Domaines supportés: finance, pharma, consulting, general

        Returns:
            Tuple[domain, confidence]
        """
        logger.info("[OSMOSE] Classifying domain...")

        # Extraire un échantillon représentatif
        sample = text[:2000] if len(text) > 2000 else text

        prompt = f"""Classify the following text into one of these business domains:
- finance (financial documents, accounting, banking, investments)
- pharma (pharmaceutical, medical, healthcare, clinical)
- consulting (strategy, management consulting, advisory)
- general (any other domain)

Text sample:
\"\"\"
{sample}
\"\"\"

Return a JSON object with:
{{
  "domain": "<finance|pharma|consulting|general>",
  "confidence": <float 0.0 to 1.0>,
  "reasoning": "<brief explanation>"
}}

JSON:"""

        try:
            response = self.llm_router.complete(
                task_type=TaskType.FAST_CLASSIFICATION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200
            )

            # Parser la réponse JSON
            response_clean = response.strip()
            if response_clean.startswith("```json"):
                response_clean = response_clean[7:]
            if response_clean.startswith("```"):
                response_clean = response_clean[3:]
            if response_clean.endswith("```"):
                response_clean = response_clean[:-3]
            response_clean = response_clean.strip()

            data = json.loads(response_clean)

            domain = data.get("domain", "general")
            confidence = float(data.get("confidence", 0.5))

            # Valider le domaine
            valid_domains = ["finance", "pharma", "consulting", "general"]
            if domain not in valid_domains:
                domain = "general"
                confidence = 0.3

            logger.info(f"[OSMOSE] Domain: {domain} (confidence: {confidence:.2f})")
            return domain, confidence

        except Exception as e:
            logger.warning(f"[OSMOSE] Domain classification failed: {e}, using fallback")
            return "general", 0.0
