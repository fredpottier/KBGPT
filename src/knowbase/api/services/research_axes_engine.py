"""
🌊 OSMOSE Research Axes Engine - Phase 3.5

Service qui génère des axes de recherche structurés et contextuels
en utilisant les signaux de découverte existants (InferenceEngine).

Contrairement à l'ExplorationIntelligenceService qui génère des suggestions
isolées, ce service produit des "axes de recherche" cohérents qui:
1. Sont basés sur des données réelles du KG (pas d'hallucination)
2. Fournissent une justification claire (pourquoi cet axe)
3. Génèrent des questions contextuelles (pas juste un mot clé)
4. Maintiennent le fil de la conversation

Architecture:
- Collecte de signaux depuis InferenceEngine (bridges, weak signals, clusters)
- Analyse de continuité documentaire (slides suivantes/précédentes)
- Mémoire de session (concepts non explorés)
- Synthèse LLM pour formuler les axes
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import logging
import time

logger = logging.getLogger(__name__)


class AxisType(str, Enum):
    """Types d'axes de recherche."""
    BRIDGE_CONNECTION = "bridge"      # Connexion entre domaines
    WEAK_SIGNAL = "weak_signal"       # Concept émergent sous-exploré
    CLUSTER_DEEP_DIVE = "cluster"     # Approfondissement thématique
    DOC_CONTINUITY = "continuity"     # Suite logique document
    UNEXPLORED = "unexplored"         # Concept mentionné non exploré
    TRANSITIVE = "transitive"         # Relation indirecte découverte


@dataclass
class ResearchAxis:
    """Un axe de recherche structuré."""

    axis_id: str
    axis_type: AxisType

    # Contenu principal
    title: str                          # Titre court et accrocheur
    justification: str                  # Pourquoi cet axe est pertinent
    contextual_question: str            # Question complète et contextuelle

    # Méta-données
    concepts_involved: List[str] = field(default_factory=list)
    relevance_score: float = 0.5        # Score de pertinence 0-1
    data_source: str = ""               # D'où vient ce signal

    # Pour l'action
    search_query: str = ""              # Query optimisée pour la recherche

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour l'API."""
        return {
            "axis_id": self.axis_id,
            "axis_type": self.axis_type.value,
            "title": self.title,
            "justification": self.justification,
            "contextual_question": self.contextual_question,
            "concepts_involved": self.concepts_involved,
            "relevance_score": self.relevance_score,
            "data_source": self.data_source,
            "search_query": self.search_query,
        }


@dataclass
class ResearchAxesResult:
    """Résultat complet du Research Axes Engine."""

    axes: List[ResearchAxis] = field(default_factory=list)

    # Contexte utilisé pour générer les axes
    query_context: str = ""
    answer_summary: str = ""

    # Métriques
    processing_time_ms: float = 0.0
    signals_collected: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour l'API."""
        return {
            "axes": [a.to_dict() for a in self.axes],
            "query_context": self.query_context,
            "answer_summary": self.answer_summary,
            "processing_time_ms": self.processing_time_ms,
            "signals_collected": self.signals_collected,
        }


class ResearchAxesEngine:
    """
    🌊 Moteur de génération d'axes de recherche.

    Utilise les signaux de découverte (InferenceEngine) et le contexte
    de la conversation pour générer des axes de recherche pertinents.
    """

    def __init__(
        self,
        inference_engine=None,
        llm_router=None,
        max_axes: int = 3,
    ):
        """
        Initialise le ResearchAxesEngine.

        Args:
            inference_engine: InferenceEngine pour la découverte
            llm_router: LLMRouter pour la synthèse
            max_axes: Nombre max d'axes à retourner
        """
        self._inference_engine = inference_engine
        self._llm_router = llm_router
        self.max_axes = max_axes
        self._axis_counter = 0

        logger.info("[OSMOSE] ResearchAxesEngine initialized")

    @property
    def inference_engine(self):
        """Lazy loading de l'InferenceEngine."""
        if self._inference_engine is None:
            from knowbase.semantic.inference.inference_engine import InferenceEngine
            self._inference_engine = InferenceEngine()
        return self._inference_engine

    @property
    def llm_router(self):
        """Lazy loading du LLMRouter."""
        if self._llm_router is None:
            from knowbase.common.llm_router import get_llm_router
            self._llm_router = get_llm_router()
        return self._llm_router

    def _generate_axis_id(self, axis_type: AxisType) -> str:
        """Génère un ID unique pour un axe."""
        self._axis_counter += 1
        return f"axis_{axis_type.value[:4]}_{self._axis_counter:04d}"

    async def generate_research_axes(
        self,
        query: str,
        synthesis_answer: str,
        query_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
        chunks: List[Dict[str, Any]],
        session_history: Optional[List[Dict[str, Any]]] = None,
        tenant_id: str = "default",
    ) -> ResearchAxesResult:
        """
        Génère des axes de recherche basés sur les signaux disponibles.

        Args:
            query: Question de l'utilisateur
            synthesis_answer: Réponse synthétisée
            query_concepts: Concepts identifiés dans la query
            related_concepts: Concepts liés depuis le KG
            chunks: Chunks utilisés pour la réponse
            session_history: Historique de la session (questions précédentes)
            tenant_id: Tenant ID

        Returns:
            ResearchAxesResult avec les axes générés
        """
        start_time = time.time()
        result = ResearchAxesResult(
            query_context=query,
            answer_summary=synthesis_answer[:200] if synthesis_answer else "",
        )

        # Collecter les signaux depuis différentes sources
        signals = await self._collect_signals(
            query_concepts=query_concepts,
            related_concepts=related_concepts,
            chunks=chunks,
            session_history=session_history,
            tenant_id=tenant_id,
        )

        result.signals_collected = {
            "bridges": len(signals.get("bridges", [])),
            "weak_signals": len(signals.get("weak_signals", [])),
            "clusters": len(signals.get("clusters", [])),
            "doc_continuity": len(signals.get("doc_continuity", [])),
            "unexplored": len(signals.get("unexplored", [])),
        }

        logger.info(f"[OSMOSE] Signals collected: {result.signals_collected}")

        # Générer les axes à partir des signaux
        candidate_axes = await self._generate_axes_from_signals(
            signals=signals,
            query=query,
            synthesis_answer=synthesis_answer,
            query_concepts=query_concepts,
        )

        # Trier par pertinence et limiter
        candidate_axes.sort(key=lambda x: x.relevance_score, reverse=True)
        result.axes = candidate_axes[:self.max_axes]

        # Si pas assez d'axes, générer des fallbacks
        if len(result.axes) < 2:
            fallback_axes = self._generate_fallback_axes(
                query=query,
                synthesis_answer=synthesis_answer,
                query_concepts=query_concepts,
                existing_count=len(result.axes),
            )
            result.axes.extend(fallback_axes)
            result.axes = result.axes[:self.max_axes]

        result.processing_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"[OSMOSE] Generated {len(result.axes)} research axes "
            f"({result.processing_time_ms:.1f}ms)"
        )

        return result

    async def _collect_signals(
        self,
        query_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
        chunks: List[Dict[str, Any]],
        session_history: Optional[List[Dict[str, Any]]],
        tenant_id: str,
    ) -> Dict[str, List[Any]]:
        """
        Collecte les signaux depuis différentes sources.
        """
        signals = {
            "bridges": [],
            "weak_signals": [],
            "clusters": [],
            "doc_continuity": [],
            "unexplored": [],
        }

        try:
            # 1. Concepts ponts (bridges)
            bridges = await self.inference_engine.discover_bridge_concepts(
                tenant_id=tenant_id,
                max_results=5,
            )
            # Filtrer pour garder ceux liés aux concepts de la query
            for bridge in bridges:
                if self._is_relevant_to_concepts(bridge, query_concepts, related_concepts):
                    signals["bridges"].append(bridge)

            # 2. Weak signals
            weak_signals = await self.inference_engine.discover_weak_signals(
                tenant_id=tenant_id,
                max_results=5,
            )
            for ws in weak_signals:
                if self._is_relevant_to_concepts(ws, query_concepts, related_concepts):
                    signals["weak_signals"].append(ws)

            # 3. Clusters thématiques
            clusters = await self.inference_engine.discover_hidden_clusters(
                tenant_id=tenant_id,
                max_results=3,
            )
            for cluster in clusters:
                if self._is_relevant_to_concepts(cluster, query_concepts, related_concepts):
                    signals["clusters"].append(cluster)

        except Exception as e:
            logger.warning(f"[OSMOSE] Error collecting inference signals: {e}")

        # 4. Continuité documentaire (slides suivantes)
        signals["doc_continuity"] = self._extract_doc_continuity(chunks)

        # 5. Concepts mentionnés mais non explorés
        if session_history:
            signals["unexplored"] = self._find_unexplored_concepts(
                session_history=session_history,
                current_concepts=query_concepts,
                related_concepts=related_concepts,
            )

        return signals

    def _is_relevant_to_concepts(
        self,
        insight,
        query_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
    ) -> bool:
        """
        Vérifie si un insight est pertinent par rapport aux concepts actuels.
        """
        # Extraire les noms des concepts liés
        related_names = set()
        for rc in related_concepts:
            if isinstance(rc, dict):
                name = rc.get("concept", rc.get("name", ""))
                if name:
                    related_names.add(name.lower())

        # Vérifier si les concepts de l'insight sont liés
        insight_concepts = insight.concepts_involved if hasattr(insight, 'concepts_involved') else []

        for ic in insight_concepts:
            ic_lower = ic.lower()
            # Match avec concepts de la query
            for qc in query_concepts:
                if qc.lower() in ic_lower or ic_lower in qc.lower():
                    return True
            # Match avec concepts liés
            if ic_lower in related_names:
                return True

        return False

    def _extract_doc_continuity(
        self,
        chunks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Extrait les opportunités de continuité documentaire.
        """
        continuity = []

        seen_docs = {}
        for chunk in chunks:
            source = chunk.get("source_file", "")
            slide_idx = chunk.get("slide_index")

            if source and slide_idx:
                if source not in seen_docs:
                    seen_docs[source] = []
                seen_docs[source].append(slide_idx)

        # Pour chaque document, suggérer la suite
        for source, slides in seen_docs.items():
            max_slide = max(slides) if slides else 0
            doc_name = source.split("/")[-1].replace(".pptx", "").replace(".pdf", "")

            if max_slide > 0:
                continuity.append({
                    "document": doc_name,
                    "source_file": source,
                    "current_slide": max_slide,
                    "suggestion": f"Voir la suite dans {doc_name} (slide {max_slide + 1}+)",
                })

        return continuity

    def _find_unexplored_concepts(
        self,
        session_history: List[Dict[str, Any]],
        current_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Trouve les concepts mentionnés dans les réponses mais jamais recherchés.
        """
        # Concepts déjà recherchés (dans les questions)
        searched = set()
        for entry in session_history:
            if "query" in entry:
                words = entry["query"].lower().split()
                searched.update(words)

        # Concepts actuellement mentionnés
        mentioned = set(c.lower() for c in current_concepts)
        for rc in related_concepts:
            if isinstance(rc, dict):
                name = rc.get("concept", rc.get("name", ""))
                if name:
                    mentioned.add(name.lower())

        # Trouver ceux jamais explorés
        unexplored = []
        for concept in mentioned:
            if concept not in searched and len(concept) > 3:
                unexplored.append({
                    "concept": concept,
                    "reason": "Mentionné dans les résultats mais non exploré",
                })

        return unexplored[:5]

    async def _generate_axes_from_signals(
        self,
        signals: Dict[str, List[Any]],
        query: str,
        synthesis_answer: str,
        query_concepts: List[str],
    ) -> List[ResearchAxis]:
        """
        Génère des axes de recherche à partir des signaux collectés.
        """
        axes = []

        # 1. Axes depuis les bridges
        for bridge in signals.get("bridges", [])[:2]:
            axis = self._create_bridge_axis(bridge, query, query_concepts)
            if axis:
                axes.append(axis)

        # 2. Axes depuis les weak signals
        for ws in signals.get("weak_signals", [])[:2]:
            axis = self._create_weak_signal_axis(ws, query, query_concepts)
            if axis:
                axes.append(axis)

        # 3. Axes depuis les clusters
        for cluster in signals.get("clusters", [])[:1]:
            axis = self._create_cluster_axis(cluster, query, query_concepts)
            if axis:
                axes.append(axis)

        # 4. Axes depuis la continuité documentaire
        for cont in signals.get("doc_continuity", [])[:1]:
            axis = self._create_continuity_axis(cont, query)
            if axis:
                axes.append(axis)

        # 5. Axes depuis les concepts non explorés
        for unexpl in signals.get("unexplored", [])[:1]:
            axis = self._create_unexplored_axis(unexpl, query, synthesis_answer)
            if axis:
                axes.append(axis)

        return axes

    def _create_bridge_axis(
        self,
        bridge,
        query: str,
        query_concepts: List[str],
    ) -> Optional[ResearchAxis]:
        """Crée un axe de recherche depuis un concept pont."""
        concept_name = bridge.concepts_involved[0] if bridge.concepts_involved else ""
        if not concept_name:
            return None

        # Construire une question contextuelle
        context_concept = query_concepts[0] if query_concepts else "ce sujet"

        return ResearchAxis(
            axis_id=self._generate_axis_id(AxisType.BRIDGE_CONNECTION),
            axis_type=AxisType.BRIDGE_CONNECTION,
            title=f"Connexion via {concept_name}",
            justification=f"{concept_name} connecte plusieurs domaines thématiques et pourrait révéler des liens non évidents.",
            contextual_question=f"Comment {concept_name} est-il lié à {context_concept} et quels autres domaines connecte-t-il ?",
            concepts_involved=[concept_name],
            relevance_score=min(bridge.importance * 1.2, 1.0),
            data_source="InferenceEngine.bridge_concepts",
            search_query=f"{concept_name} {context_concept}",
        )

    def _create_weak_signal_axis(
        self,
        weak_signal,
        query: str,
        query_concepts: List[str],
    ) -> Optional[ResearchAxis]:
        """Crée un axe de recherche depuis un weak signal."""
        concept_name = weak_signal.concepts_involved[0] if weak_signal.concepts_involved else ""
        if not concept_name:
            return None

        context_concept = query_concepts[0] if query_concepts else "votre recherche"

        return ResearchAxis(
            axis_id=self._generate_axis_id(AxisType.WEAK_SIGNAL),
            axis_type=AxisType.WEAK_SIGNAL,
            title=f"Signal émergent : {concept_name}",
            justification=f"{concept_name} est peu mentionné mais fortement connecté - un concept potentiellement sous-exploré.",
            contextual_question=f"Quel est le rôle de {concept_name} dans le contexte de {context_concept} ?",
            concepts_involved=[concept_name],
            relevance_score=weak_signal.importance,
            data_source="InferenceEngine.weak_signals",
            search_query=f"{concept_name} {context_concept}",
        )

    def _create_cluster_axis(
        self,
        cluster,
        query: str,
        query_concepts: List[str],
    ) -> Optional[ResearchAxis]:
        """Crée un axe de recherche depuis un cluster thématique."""
        if not cluster.concepts_involved:
            return None

        main_concept = cluster.concepts_involved[0]
        other_concepts = cluster.concepts_involved[1:3]

        return ResearchAxis(
            axis_id=self._generate_axis_id(AxisType.CLUSTER_DEEP_DIVE),
            axis_type=AxisType.CLUSTER_DEEP_DIVE,
            title=f"Groupe thématique : {main_concept}",
            justification=f"Un groupe de concepts fortement liés ({', '.join(other_concepts[:2])}, ...) forme une thématique cohérente.",
            contextual_question=f"Quels sont les aspects clés du domaine autour de {main_concept} ?",
            concepts_involved=cluster.concepts_involved[:5],
            relevance_score=cluster.confidence,
            data_source="InferenceEngine.hidden_clusters",
            search_query=f"{main_concept} {' '.join(other_concepts[:2])}",
        )

    def _create_continuity_axis(
        self,
        continuity: Dict[str, Any],
        query: str,
    ) -> Optional[ResearchAxis]:
        """Crée un axe de recherche depuis la continuité documentaire."""
        doc_name = continuity.get("document", "")
        current_slide = continuity.get("current_slide", 0)

        if not doc_name:
            return None

        return ResearchAxis(
            axis_id=self._generate_axis_id(AxisType.DOC_CONTINUITY),
            axis_type=AxisType.DOC_CONTINUITY,
            title=f"Suite dans {doc_name}",
            justification=f"La réponse utilise des informations de ce document - la suite pourrait contenir des détails complémentaires.",
            contextual_question=f"Quelles informations supplémentaires trouve-t-on après la slide {current_slide} de {doc_name} ?",
            concepts_involved=[doc_name],
            relevance_score=0.7,
            data_source="document_continuity",
            search_query=f"document:{doc_name}",
        )

    def _create_unexplored_axis(
        self,
        unexplored: Dict[str, Any],
        query: str,
        synthesis_answer: str,
    ) -> Optional[ResearchAxis]:
        """Crée un axe de recherche depuis un concept non exploré."""
        concept = unexplored.get("concept", "")
        if not concept:
            return None

        # Extraire un bout de contexte de la réponse
        context_snippet = ""
        if synthesis_answer and concept.lower() in synthesis_answer.lower():
            idx = synthesis_answer.lower().find(concept.lower())
            start = max(0, idx - 30)
            end = min(len(synthesis_answer), idx + len(concept) + 30)
            context_snippet = synthesis_answer[start:end].strip()

        justification = f"'{concept}' a été mentionné dans les résultats mais n'a pas été exploré directement."
        if context_snippet:
            justification = f"'{concept}' apparaît dans le contexte : \"...{context_snippet}...\""

        return ResearchAxis(
            axis_id=self._generate_axis_id(AxisType.UNEXPLORED),
            axis_type=AxisType.UNEXPLORED,
            title=f"À approfondir : {concept}",
            justification=justification,
            contextual_question=f"Pouvez-vous détailler ce qu'est {concept} et son importance dans ce contexte ?",
            concepts_involved=[concept],
            relevance_score=0.6,
            data_source="session_memory",
            search_query=f"{concept} définition rôle",
        )

    def _generate_fallback_axes(
        self,
        query: str,
        synthesis_answer: str,
        query_concepts: List[str],
        existing_count: int,
    ) -> List[ResearchAxis]:
        """
        Génère des axes de fallback quand pas assez de signaux.
        """
        axes = []
        needed = self.max_axes - existing_count

        # Fallback 1: Demander des exemples concrets
        if needed > 0:
            context = query_concepts[0] if query_concepts else "ce sujet"
            axes.append(ResearchAxis(
                axis_id=self._generate_axis_id(AxisType.UNEXPLORED),
                axis_type=AxisType.UNEXPLORED,
                title="Cas pratiques",
                justification="Des exemples concrets permettent de mieux comprendre l'application.",
                contextual_question=f"Pouvez-vous donner des exemples concrets d'utilisation de {context} ?",
                concepts_involved=query_concepts[:2],
                relevance_score=0.5,
                data_source="fallback",
                search_query=f"{context} exemple cas pratique",
            ))
            needed -= 1

        # Fallback 2: Explorer les prérequis
        if needed > 0 and query_concepts:
            concept = query_concepts[0]
            axes.append(ResearchAxis(
                axis_id=self._generate_axis_id(AxisType.TRANSITIVE),
                axis_type=AxisType.TRANSITIVE,
                title=f"Prérequis pour {concept}",
                justification="Comprendre les bases permet d'approfondir plus efficacement.",
                contextual_question=f"Quels sont les prérequis et concepts fondamentaux pour comprendre {concept} ?",
                concepts_involved=[concept],
                relevance_score=0.4,
                data_source="fallback",
                search_query=f"{concept} prérequis fondamentaux bases",
            ))
            needed -= 1

        # Fallback 3: Comparaison avec alternatives
        if needed > 0 and query_concepts:
            concept = query_concepts[0]
            axes.append(ResearchAxis(
                axis_id=self._generate_axis_id(AxisType.BRIDGE_CONNECTION),
                axis_type=AxisType.BRIDGE_CONNECTION,
                title=f"Alternatives à {concept}",
                justification="Comparer avec des solutions similaires aide à faire un choix éclairé.",
                contextual_question=f"Quelles sont les alternatives ou solutions similaires à {concept} ?",
                concepts_involved=[concept],
                relevance_score=0.4,
                data_source="fallback",
                search_query=f"{concept} alternative comparaison vs",
            ))

        return axes


# Singleton
_engine_instance: Optional[ResearchAxesEngine] = None


def get_research_axes_engine() -> ResearchAxesEngine:
    """Retourne l'instance singleton du ResearchAxesEngine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ResearchAxesEngine()
    return _engine_instance


__all__ = [
    "ResearchAxesEngine",
    "ResearchAxesResult",
    "ResearchAxis",
    "AxisType",
    "get_research_axes_engine",
]
