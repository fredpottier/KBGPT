"""
🌊 OSMOSE Semantic Intelligence - Narrative Thread Detector

NarrativeThreadDetector : Détecte les fils narratifs cross-documents

🎯 COMPOSANT CRITIQUE - USP KILLER de KnowWhere
"""

from typing import List, Dict, Optional, Tuple
import logging
import re
import json
from datetime import datetime
from .models import NarrativeThread
from .config import get_semantic_config
from knowbase.common.llm_router import LLMRouter, TaskType

logger = logging.getLogger(__name__)


class NarrativeThreadDetector:
    """
    Détecte les fils narratifs qui traversent les documents.

    Responsabilités:
    - Identifier les séquences causales
    - Détecter les marqueurs temporels (revised, updated, etc.)
    - Construire des timelines d'évolution conceptuelle
    - Identifier les contradictions entre versions

    🔥 KILLER FEATURE: "CRR Evolution Tracker"
    Exemple: Détecte que "Customer Retention Rate" évolue sur 3 versions
    avec des liens causaux et temporels explicites.

    Phase 1 - Semaines 5-6
    """

    def __init__(self):
        """Initialise le détecteur avec la configuration"""
        self.config = get_semantic_config()
        self.narrative_config = self.config.narrative_detection
        self.llm_router = LLMRouter()
        logger.info("[OSMOSE] NarrativeThreadDetector initialisé")

    async def detect_narrative_threads(
        self,
        document_id: str,
        text_content: str,
        existing_threads: Optional[List[NarrativeThread]] = None
    ) -> List[NarrativeThread]:
        """
        Détecte les fils narratifs dans un document.

        Args:
            document_id: ID du document
            text_content: Contenu textuel
            existing_threads: Fils narratifs existants (cross-doc)

        Returns:
            List[NarrativeThread]: Fils narratifs détectés
        """
        logger.info(f"[OSMOSE] Détection narrative threads: {document_id}")

        threads = []

        # 1. Identifier séquences causales
        causal_sequences = self._identify_causal_sequences(text_content)
        logger.info(f"[OSMOSE] Causal sequences found: {len(causal_sequences)}")

        # 2. Détecter marqueurs temporels et construire temporal sequences
        temporal_sequences = self._detect_temporal_sequences(text_content)
        logger.info(f"[OSMOSE] Temporal sequences found: {len(temporal_sequences)}")

        # 3. Construire threads à partir des séquences
        for seq in causal_sequences:
            thread = NarrativeThread(
                description=seq["description"],
                start_position=seq["start_pos"],
                end_position=seq["end_pos"],
                confidence=seq["confidence"],
                keywords=seq["keywords"],
                causal_links=seq["causal_links"],
                temporal_markers=[]
            )
            threads.append(thread)

        for seq in temporal_sequences:
            thread = NarrativeThread(
                description=seq["description"],
                start_position=seq["start_pos"],
                end_position=seq["end_pos"],
                confidence=seq["confidence"],
                keywords=seq["keywords"],
                causal_links=[],
                temporal_markers=seq["temporal_markers"]
            )
            threads.append(thread)

        # 4. Enrichir avec analyse LLM pour les threads complexes
        if len(threads) > 0:
            threads = await self._enrich_threads_with_llm(text_content, threads)

        # 5. Cross-document linking (si threads existants fournis)
        if existing_threads:
            threads = self._build_cross_document_links(threads, existing_threads)

        logger.info(f"[OSMOSE] ✅ {len(threads)} narrative threads detected")
        return threads

    def _identify_causal_sequences(self, text: str) -> List[Dict]:
        """
        Identifie les séquences causales (because, therefore, etc.)

        Returns:
            List de dicts avec: description, positions, confidence, keywords, causal_links
        """
        logger.info("[OSMOSE] Identifying causal sequences...")

        sequences = []
        causal_connectors = self.narrative_config.causal_connectors

        # Pattern regex pour chaque connecteur
        for connector in causal_connectors:
            pattern = rf'([^.!?]*)\b{re.escape(connector)}\b([^.!?]*[.!?])'
            matches = list(re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE))

            if len(matches) >= 2:  # Au moins 2 occurrences pour former une séquence
                # Analyser le contexte autour des connecteurs
                contexts = []
                for match in matches:
                    before_text = match.group(1).strip()
                    after_text = match.group(2).strip()
                    contexts.append({
                        "before": before_text,
                        "connector": connector,
                        "after": after_text,
                        "position": match.start()
                    })

                # Créer une séquence causale
                first_pos = matches[0].start()
                last_pos = matches[-1].end()

                # Extraire les concepts clés
                keywords = self._extract_keywords_from_contexts(contexts)

                sequence = {
                    "description": f"Causal narrative with '{connector}' ({len(matches)} occurrences)",
                    "start_pos": first_pos,
                    "end_pos": last_pos,
                    "confidence": min(0.6 + (len(matches) * 0.1), 0.95),  # Plus d'occurrences = plus confiance
                    "keywords": keywords,
                    "causal_links": [connector]
                }
                sequences.append(sequence)

        return sequences

    def _detect_temporal_sequences(self, text: str) -> List[Dict]:
        """
        Détecte les séquences temporelles (revised, updated, superseded, etc.)

        Returns:
            List de dicts avec: description, positions, confidence, keywords, temporal_markers
        """
        logger.info("[OSMOSE] Detecting temporal sequences...")

        sequences = []
        temporal_markers = self.narrative_config.temporal_markers

        # Rechercher tous les marqueurs temporels
        found_markers = []
        for marker in temporal_markers:
            pattern = rf'\b{re.escape(marker)}\b'
            matches = list(re.finditer(pattern, text, re.IGNORECASE))

            for match in matches:
                # Extraire contexte (50 chars avant/après)
                start_ctx = max(0, match.start() - 50)
                end_ctx = min(len(text), match.end() + 50)
                context = text[start_ctx:end_ctx]

                found_markers.append({
                    "marker": marker,
                    "position": match.start(),
                    "context": context
                })

        if len(found_markers) >= 2:
            # Grouper par proximité temporelle/positionnelle
            # Pour simplifier, on crée une séquence globale si plusieurs markers
            unique_markers = list(set(m["marker"] for m in found_markers))

            # Extraire concepts évoluant (versions, dates, noms)
            keywords = self._extract_evolving_concepts(text, found_markers)

            sequence = {
                "description": f"Temporal evolution with {len(unique_markers)} markers",
                "start_pos": min(m["position"] for m in found_markers),
                "end_pos": max(m["position"] for m in found_markers) + 50,
                "confidence": min(0.65 + (len(found_markers) * 0.05), 0.95),
                "keywords": keywords,
                "temporal_markers": unique_markers
            }
            sequences.append(sequence)

        return sequences

    def _extract_keywords_from_contexts(self, contexts: List[Dict]) -> List[str]:
        """Extrait les mots-clés des contextes causaux"""
        keywords = set()

        for ctx in contexts:
            # Extraire noms propres et concepts capitalisés
            words = ctx["before"].split() + ctx["after"].split()
            for word in words:
                # Garder mots capitalisés ou acronymes
                if word and (word[0].isupper() or word.isupper()):
                    keywords.add(word.strip('.,;:!?'))

        return list(keywords)[:10]  # Limiter à 10 mots-clés

    def _extract_evolving_concepts(self, text: str, markers: List[Dict]) -> List[str]:
        """Extrait les concepts qui évoluent (versions, métriques, etc.)"""
        keywords = set()

        # Pattern pour versions (v1.0, v2.0, version 3, etc.)
        version_pattern = r'\b(?:v|version|V)\s*[\d.]+\b'
        versions = re.findall(version_pattern, text, re.IGNORECASE)
        keywords.update(versions)

        # Pattern pour dates/années
        year_pattern = r'\b(?:20\d{2}|19\d{2})\b'
        years = re.findall(year_pattern, text)
        keywords.update(years)

        # Extraire noms propres autour des marqueurs
        for marker_info in markers:
            context = marker_info["context"]
            words = context.split()
            for word in words:
                if word and word[0].isupper():
                    keywords.add(word.strip('.,;:!?'))

        return list(keywords)[:15]  # Limiter à 15

    async def _enrich_threads_with_llm(
        self,
        text: str,
        threads: List[NarrativeThread]
    ) -> List[NarrativeThread]:
        """
        Enrichit les threads avec analyse LLM pour améliorer descriptions et confidence.

        Utilise LLM uniquement pour les threads les plus prometteurs.
        """
        logger.info("[OSMOSE] Enriching threads with LLM analysis...")

        # Prendre les 3 threads les plus confiants pour analyse LLM
        top_threads = sorted(threads, key=lambda t: t.confidence, reverse=True)[:3]

        for thread in top_threads:
            try:
                # Extraire le contexte du thread
                context = text[thread.start_position:thread.end_position]
                if len(context) > 1500:
                    context = context[:1500] + "..."

                prompt = f"""Analyze this narrative sequence and provide:
1. A concise description of what is evolving/changing
2. The main concept or entity being tracked
3. A confidence score (0.0-1.0) for how clear the narrative is

Context:
\"\"\"
{context}
\"\"\"

Causal links found: {thread.causal_links}
Temporal markers found: {thread.temporal_markers}

Return JSON:
{{
  "description": "<concise description>",
  "main_concept": "<e.g., Customer Retention Rate, Methodology, Formula>",
  "confidence": <float 0.0-1.0>
}}

JSON:"""

                response = self.llm_router.complete(
                    task_type=TaskType.METADATA_EXTRACTION,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=300
                )

                # Parser réponse
                response_clean = response.strip()
                if response_clean.startswith("```json"):
                    response_clean = response_clean[7:]
                if response_clean.startswith("```"):
                    response_clean = response_clean[3:]
                if response_clean.endswith("```"):
                    response_clean = response_clean[:-3]
                response_clean = response_clean.strip()

                data = json.loads(response_clean)

                # Enrichir le thread
                thread.description = data.get("description", thread.description)
                llm_confidence = float(data.get("confidence", thread.confidence))
                # Combiner confidence initiale + LLM
                thread.confidence = (thread.confidence + llm_confidence) / 2

                # Ajouter concept principal aux keywords
                main_concept = data.get("main_concept")
                if main_concept and main_concept not in thread.keywords:
                    thread.keywords.insert(0, main_concept)

                logger.info(f"[OSMOSE] Thread enriched: {thread.description} (conf: {thread.confidence:.2f})")

            except Exception as e:
                logger.warning(f"[OSMOSE] Failed to enrich thread with LLM: {e}")
                # Continue avec le thread non enrichi

        return threads

    def _build_cross_document_links(
        self,
        current_threads: List[NarrativeThread],
        existing_threads: List[NarrativeThread]
    ) -> List[NarrativeThread]:
        """
        Construit les liens entre fils narratifs de différents documents.

        Identifie les threads qui parlent du même concept/évolution.
        """
        logger.info("[OSMOSE] Building cross-document links...")

        # Pour chaque thread courant, chercher des threads similaires existants
        for current_thread in current_threads:
            current_keywords = set(kw.lower() for kw in current_thread.keywords)

            for existing_thread in existing_threads:
                existing_keywords = set(kw.lower() for kw in existing_thread.keywords)

                # Calculer similarité Jaccard des keywords
                intersection = len(current_keywords & existing_keywords)
                union = len(current_keywords | existing_keywords)

                if union > 0:
                    similarity = intersection / union

                    # Si similarité significative, augmenter la confidence
                    if similarity > 0.3:
                        current_thread.confidence = min(current_thread.confidence + 0.1, 1.0)
                        logger.info(f"[OSMOSE] Cross-doc link found (similarity: {similarity:.2f})")

        return current_threads

    def build_timeline(
        self,
        threads: List[NarrativeThread],
        documents_metadata: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Construit une timeline d'évolution à partir des threads narratifs.

        Args:
            threads: Fils narratifs détectés
            documents_metadata: Métadonnées des documents (dates, versions, etc.)

        Returns:
            Dict représentant la timeline
        """
        logger.info("[OSMOSE] Building narrative timeline...")

        timeline_events = []

        # Extraire événements des threads
        for thread in threads:
            # Chercher dates/versions dans les keywords
            dates = []
            versions = []

            for keyword in thread.keywords:
                # Pattern date/année
                if re.match(r'^\d{4}$', keyword):
                    dates.append(keyword)
                # Pattern version
                if re.match(r'^v[\d.]+$', keyword.lower()) or 'version' in keyword.lower():
                    versions.append(keyword)

            event = {
                "description": thread.description,
                "confidence": thread.confidence,
                "dates": dates,
                "versions": versions,
                "causal_links": thread.causal_links,
                "temporal_markers": thread.temporal_markers
            }
            timeline_events.append(event)

        # Trier par dates/versions si disponibles
        timeline_events_sorted = sorted(
            timeline_events,
            key=lambda e: (e["dates"][0] if e["dates"] else "9999", e["versions"][0] if e["versions"] else "")
        )

        timeline = {
            "events": timeline_events_sorted,
            "total_events": len(timeline_events_sorted),
            "has_temporal_evolution": any(e["temporal_markers"] for e in timeline_events),
            "has_causal_chains": any(e["causal_links"] for e in timeline_events)
        }

        logger.info(f"[OSMOSE] Timeline built: {timeline['total_events']} events")
        return timeline
