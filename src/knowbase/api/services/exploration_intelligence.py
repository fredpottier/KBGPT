"""
Service d'Intelligence d'Exploration (Phase 3.5 - Explainable Graph-RAG).

Génère des informations d'exploration intelligente pour enrichir le Knowledge Graph:
- Option A: Explications de raisonnement (pourquoi ce concept est utilisé)
- Option B: Axes de recherche structurés (via ResearchAxesEngine)
- Option C: Questions suggérées pour chaque concept

🌊 OSMOSE Phase 3.5: Intégration du ResearchAxesEngine pour des suggestions
basées sur des signaux réels du KG (bridges, weak signals, clusters).
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
import logging

from knowbase.common.llm_router import TaskType, get_llm_router
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "exploration_intelligence.log")


@dataclass
class ConceptExplanation:
    """Explication du raisonnement pour un concept."""
    concept_id: str
    concept_name: str
    why_used: str  # Pourquoi ce concept est pertinent
    role_in_answer: str  # Quel rôle il joue dans la réponse
    source_documents: List[str] = field(default_factory=list)
    confidence: float = 0.8


@dataclass
class ExplorationSuggestion:
    """Suggestion de piste d'exploration."""
    suggestion_type: str  # "concept", "document", "question"
    title: str
    description: str
    action_label: str  # Texte du bouton d'action
    action_value: str  # Valeur pour l'action (concept_id, question, etc.)
    relevance_score: float = 0.8


@dataclass
class SuggestedQuestion:
    """Question suggérée pour approfondir."""
    question: str
    context: str  # Pourquoi cette question est pertinente
    related_concepts: List[str] = field(default_factory=list)


@dataclass
class ResearchAxisDTO:
    """DTO pour un axe de recherche (depuis ResearchAxesEngine v2)."""
    axis_id: str
    role: str  # "actionnable", "risk", "structure"
    short_label: str
    full_question: str
    source_concept: str
    target_concept: str
    relation_type: str
    relevance_score: float = 0.5
    confidence: float = 0.5
    explainer_trace: str = ""
    search_query: str = ""


@dataclass
class ExplorationIntelligence:
    """Résultat complet de l'intelligence d'exploration."""
    # Option A: Explications par concept
    concept_explanations: Dict[str, ConceptExplanation] = field(default_factory=dict)

    # Option B: Pistes d'exploration (legacy) - sera remplacé par research_axes
    exploration_suggestions: List[ExplorationSuggestion] = field(default_factory=list)

    # Option C: Questions suggérées
    suggested_questions: List[SuggestedQuestion] = field(default_factory=list)

    # 🌊 NOUVEAU: Axes de recherche structurés (Phase 3.5)
    research_axes: List[ResearchAxisDTO] = field(default_factory=list)

    # Métadonnées
    processing_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour l'API."""
        return {
            "concept_explanations": {
                k: asdict(v) for k, v in self.concept_explanations.items()
            },
            "exploration_suggestions": [asdict(s) for s in self.exploration_suggestions],
            "suggested_questions": [asdict(q) for q in self.suggested_questions],
            "research_axes": [asdict(a) for a in self.research_axes],
            "processing_time_ms": self.processing_time_ms,
        }


class ExplorationIntelligenceService:
    """
    Service pour générer l'intelligence d'exploration.

    Utilise le LLM pour générer:
    1. Des explications de raisonnement pour chaque concept utilisé
    2. Des axes de recherche structurés (via ResearchAxesEngine)
    3. Des questions suggérées pour approfondir

    🌊 OSMOSE Phase 3.5: Le ResearchAxesEngine utilise les signaux du KG
    (bridges, weak signals, clusters) pour des suggestions pertinentes.
    """

    def __init__(self):
        self.llm_router = get_llm_router()
        self._research_axes_engine = None

    @property
    def research_axes_engine(self):
        """Lazy loading du ResearchAxesEngine."""
        if self._research_axes_engine is None:
            from knowbase.api.services.research_axes_engine import get_research_axes_engine
            self._research_axes_engine = get_research_axes_engine()
        return self._research_axes_engine

    def generate_exploration_intelligence(
        self,
        query: str,
        synthesis_answer: str,
        graph_context: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        session_history: Optional[List[Dict[str, Any]]] = None,
        tenant_id: str = "default",
    ) -> ExplorationIntelligence:
        """
        Génère l'intelligence d'exploration complète.

        Args:
            query: Question de l'utilisateur
            synthesis_answer: Réponse synthétisée
            graph_context: Contexte du Knowledge Graph
            chunks: Chunks utilisés pour la réponse
            session_history: Historique de session (optionnel)
            tenant_id: Tenant ID

        Returns:
            ExplorationIntelligence avec explications, suggestions, questions et axes
        """
        import time
        import asyncio
        start_time = time.time()

        result = ExplorationIntelligence()

        # Extraire les concepts du graph_context
        query_concepts = graph_context.get("query_concepts", [])
        related_concepts = graph_context.get("related_concepts", [])

        # Extraire les noms de documents uniques
        unique_docs = set()
        for chunk in chunks:
            source_file = chunk.get("source_file", "")
            if source_file:
                doc_name = source_file.split("/")[-1].replace(".pptx", "").replace(".pdf", "")
                unique_docs.add(doc_name)

        # 🌊 Phase 3.5+: Générer les axes de recherche via ResearchAxesEngine v2
        # ✅ RÉACTIVÉ - Le nouveau v2 utilise des requêtes Cypher directes (pas de NetworkX)
        ENABLE_RESEARCH_AXES = True

        if ENABLE_RESEARCH_AXES:
            try:
                # Convertir chunks en format attendu
                chunks_data = [
                    {
                        "source_file": c.get("source_file", ""),
                        "slide_index": c.get("slide_index"),
                        "text": c.get("text", ""),
                    }
                    for c in chunks
                ]

                # Appel async du ResearchAxesEngine v2
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    axes_result = loop.run_until_complete(
                        self.research_axes_engine.generate_research_axes(
                            query=query,
                            synthesis_answer=synthesis_answer,
                            query_concepts=query_concepts,
                            graph_context=graph_context,
                            chunks=chunks_data,
                            tenant_id=tenant_id,
                        )
                    )

                    # Convertir en DTOs (nouvelle structure v2)
                    for axis in axes_result.axes:
                        result.research_axes.append(ResearchAxisDTO(
                            axis_id=axis.axis_id,
                            role=axis.role.value,
                            short_label=axis.short_label,
                            full_question=axis.full_question,
                            source_concept=axis.source_concept,
                            target_concept=axis.target_concept,
                            relation_type=axis.relation_type,
                            relevance_score=axis.relevance_score,
                            confidence=axis.confidence,
                            explainer_trace=axis.explainer_trace,
                            search_query=axis.search_query,
                        ))

                    logger.info(
                        f"[EXPLORATION] ResearchAxesEngine v2: {len(result.research_axes)} axes "
                        f"(roles: {axes_result.roles_distribution}, {axes_result.processing_time_ms:.1f}ms)"
                    )

                finally:
                    loop.close()

            except Exception as e:
                logger.warning(f"[EXPLORATION] ResearchAxesEngine failed: {e}")

        # Décision : si le KG n'a pas trouvé de relations pertinentes,
        # mieux vaut ne pas proposer de questions que des questions non pertinentes
        kg_has_results = len(result.research_axes) > 0

        if not kg_has_results:
            logger.info(
                "[EXPLORATION] KG found no relevant relations - skipping suggested questions "
                "(better no suggestions than irrelevant ones)"
            )

        # Génération LLM pour explications de concepts (toujours utile)
        try:
            exploration_data = self._generate_all_intelligence(
                query=query,
                synthesis_answer=synthesis_answer,
                query_concepts=query_concepts,
                related_concepts=related_concepts,
                documents=list(unique_docs),
            )

            result.concept_explanations = self._parse_concept_explanations(
                exploration_data.get("concept_explanations", {}),
                query_concepts,
                list(unique_docs)
            )

            # Suggestions d'exploration basées sur les concepts liés (pas les questions)
            result.exploration_suggestions = self._parse_exploration_suggestions(
                exploration_data.get("exploration_suggestions", [])
            )

            # Questions suggérées : UNIQUEMENT si le KG a trouvé des relations pertinentes
            if kg_has_results:
                result.suggested_questions = self._parse_suggested_questions(
                    exploration_data.get("suggested_questions", [])
                )
            # Sinon : pas de suggested_questions (liste vide par défaut)

        except Exception as e:
            logger.error(f"[EXPLORATION] Error generating LLM intelligence: {e}", exc_info=True)
            # En cas d'erreur, on utilise le fallback minimal (explications seulement)
            if query_concepts:
                for concept in query_concepts[:3]:
                    result.concept_explanations[concept] = ConceptExplanation(
                        concept_id=concept.lower().replace(" ", "_"),
                        concept_name=concept,
                        why_used="Concept mentionné dans votre question",
                        role_in_answer="central",
                        source_documents=list(unique_docs)[:2],
                        confidence=0.9
                    )

        result.processing_time_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[EXPLORATION] Generated intelligence: "
            f"{len(result.concept_explanations)} explanations, "
            f"{len(result.exploration_suggestions)} suggestions, "
            f"{len(result.suggested_questions)} questions, "
            f"{len(result.research_axes)} research axes "
            f"({result.processing_time_ms:.1f}ms)"
        )

        return result

    def _generate_all_intelligence(
        self,
        query: str,
        synthesis_answer: str,
        query_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
        documents: List[str],
    ) -> Dict[str, Any]:
        """
        Génère toute l'intelligence en un seul appel LLM.
        """
        # Formater les concepts liés
        related_formatted = []
        for rc in related_concepts[:10]:  # Limiter à 10
            if isinstance(rc, dict):
                name = rc.get("concept", rc.get("name", ""))
                rel_type = rc.get("relationship_type", rc.get("relation", ""))
                if name:
                    related_formatted.append(f"- {name} ({rel_type})")

        prompt = f"""Analyse cette recherche et génère des informations d'exploration intelligente.

## Question utilisateur
{query}

## Réponse générée
{synthesis_answer[:1000]}...

## Concepts identifiés dans la question
{', '.join(query_concepts) if query_concepts else 'Aucun concept identifié'}

## Concepts liés dans le Knowledge Graph
{chr(10).join(related_formatted) if related_formatted else 'Aucun concept lié'}

## Documents sources
{', '.join(documents[:5]) if documents else 'Documents non spécifiés'}

---

Génère un JSON avec exactement cette structure:

{{
  "concept_explanations": {{
    "<nom_concept>": {{
      "why_used": "Explication courte de pourquoi ce concept est pertinent pour la question",
      "role_in_answer": "Rôle de ce concept dans la réponse (central/support/contexte)"
    }}
  }},
  "exploration_suggestions": [
    {{
      "type": "concept|document|question",
      "title": "Titre court de la suggestion",
      "description": "Description de ce que l'utilisateur pourrait découvrir",
      "action_label": "Texte du bouton (ex: Explorer, Voir, Rechercher)",
      "action_value": "Valeur pour l'action"
    }}
  ],
  "suggested_questions": [
    {{
      "question": "Question pertinente pour approfondir",
      "context": "Pourquoi cette question est intéressante",
      "related_concepts": ["concept1", "concept2"]
    }}
  ]
}}

Règles:
- Génère 2-4 explications de concepts (les plus importants)
- Génère 2-3 suggestions d'exploration variées
- Génère 2-3 questions pertinentes pour aller plus loin
- Les explications doivent être en français et concises (1-2 phrases)
- Les suggestions doivent être actionnables
- Les questions doivent être différentes de la question originale

Réponds UNIQUEMENT avec le JSON, sans texte avant ou après."""

        messages = [
            {"role": "system", "content": "Tu es un assistant expert qui aide à explorer une base de connaissances. Tu génères des suggestions d'exploration intelligentes."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.llm_router.complete(
                task_type=TaskType.JSON_EXTRACTION,
                messages=messages,
                temperature=0.3,
                max_tokens=1500
            )

            # Parser le JSON
            import json
            import re

            # Nettoyer la réponse (enlever markdown si présent)
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\n?', '', cleaned)
                cleaned = re.sub(r'\n?```$', '', cleaned)

            return json.loads(cleaned)

        except Exception as e:
            logger.warning(f"[EXPLORATION] LLM call failed: {e}")
            return {}

    def _parse_concept_explanations(
        self,
        raw_explanations: Dict[str, Any],
        query_concepts: List[str],
        documents: List[str],
    ) -> Dict[str, ConceptExplanation]:
        """Parse les explications de concepts."""
        result = {}

        for concept_name, data in raw_explanations.items():
            if isinstance(data, dict):
                explanation = ConceptExplanation(
                    concept_id=concept_name.lower().replace(" ", "_"),
                    concept_name=concept_name,
                    why_used=data.get("why_used", "Concept pertinent pour la recherche"),
                    role_in_answer=data.get("role_in_answer", "support"),
                    source_documents=documents[:3],
                    confidence=0.85 if concept_name in query_concepts else 0.7
                )
                result[concept_name] = explanation

        return result

    def _parse_exploration_suggestions(
        self,
        raw_suggestions: List[Dict[str, Any]],
    ) -> List[ExplorationSuggestion]:
        """Parse les suggestions d'exploration."""
        result = []

        for idx, data in enumerate(raw_suggestions[:5]):
            if isinstance(data, dict):
                suggestion = ExplorationSuggestion(
                    suggestion_type=data.get("type", "concept"),
                    title=data.get("title", f"Suggestion {idx+1}"),
                    description=data.get("description", ""),
                    action_label=data.get("action_label", "Explorer"),
                    action_value=data.get("action_value", ""),
                    relevance_score=0.8 - (idx * 0.1)
                )
                result.append(suggestion)

        return result

    def _parse_suggested_questions(
        self,
        raw_questions: List[Dict[str, Any]],
    ) -> List[SuggestedQuestion]:
        """Parse les questions suggérées."""
        result = []

        for data in raw_questions[:5]:
            if isinstance(data, dict):
                question = SuggestedQuestion(
                    question=data.get("question", ""),
                    context=data.get("context", ""),
                    related_concepts=data.get("related_concepts", [])
                )
                if question.question:
                    result.append(question)

        return result

    def _generate_fallback_intelligence(
        self,
        query_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
        documents: List[str],
        query: str = "",
        synthesis_answer: str = "",
    ) -> ExplorationIntelligence:
        """
        Génère une intelligence de fallback sans LLM.
        Utilisé en cas d'erreur du LLM ou quand peu de contexte KG est disponible.
        """
        result = ExplorationIntelligence()

        # Explications basiques pour les concepts de la query
        for concept in query_concepts[:3]:
            result.concept_explanations[concept] = ConceptExplanation(
                concept_id=concept.lower().replace(" ", "_"),
                concept_name=concept,
                why_used="Concept mentionné dans votre question",
                role_in_answer="central",
                source_documents=documents[:2],
                confidence=0.9
            )

        # Suggestions basées sur les concepts liés
        for idx, rc in enumerate(related_concepts[:3]):
            if isinstance(rc, dict):
                name = rc.get("concept", rc.get("name", ""))
                if name:
                    result.exploration_suggestions.append(ExplorationSuggestion(
                        suggestion_type="concept",
                        title=name,
                        description=f"Concept lié qui pourrait enrichir votre recherche",
                        action_label="Explorer",
                        action_value=name,
                        relevance_score=0.7 - (idx * 0.1)
                    ))

        # Questions de suivi basées sur le contexte disponible
        if query_concepts:
            result.suggested_questions.append(SuggestedQuestion(
                question=f"Quels sont les prérequis pour {query_concepts[0]} ?",
                context="Question classique pour approfondir le sujet",
                related_concepts=query_concepts[:2]
            ))

        # Si on a des documents, suggérer d'explorer les sources
        if documents and not result.exploration_suggestions:
            for idx, doc in enumerate(documents[:2]):
                result.exploration_suggestions.append(ExplorationSuggestion(
                    suggestion_type="document",
                    title=f"Explorer {doc}",
                    description="Document source de cette réponse",
                    action_label="Voir le document",
                    action_value=f"documents contenant {doc}",
                    relevance_score=0.6 - (idx * 0.1)
                ))

        # Toujours générer au moins une question suggérée basée sur la réponse
        if not result.suggested_questions and synthesis_answer:
            # Extraire un sujet de la réponse (premiers mots significatifs)
            words = [w for w in synthesis_answer.split()[:20] if len(w) > 4]
            if words:
                topic = " ".join(words[:3])
                result.suggested_questions.append(SuggestedQuestion(
                    question=f"Pouvez-vous approfondir sur {topic} ?",
                    context="Pour explorer plus en détail ce sujet",
                    related_concepts=[]
                ))

        # Question générique si vraiment rien d'autre
        if not result.suggested_questions:
            result.suggested_questions.append(SuggestedQuestion(
                question="Pouvez-vous donner des exemples concrets ?",
                context="Question de suivi standard",
                related_concepts=[]
            ))

        return result


# Singleton pour réutilisation
_service_instance: Optional[ExplorationIntelligenceService] = None


def get_exploration_service() -> ExplorationIntelligenceService:
    """Retourne l'instance singleton du service."""
    global _service_instance
    if _service_instance is None:
        _service_instance = ExplorationIntelligenceService()
    return _service_instance


__all__ = [
    "ExplorationIntelligenceService",
    "ExplorationIntelligence",
    "ConceptExplanation",
    "ExplorationSuggestion",
    "SuggestedQuestion",
    "ResearchAxisDTO",
    "get_exploration_service",
]
