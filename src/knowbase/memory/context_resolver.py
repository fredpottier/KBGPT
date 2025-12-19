"""
ContextResolver - Résolution des références implicites dans les conversations.

Phase 2.5 - Memory Layer

Responsabilités:
- Identifier les références implicites ("il", "ça", "ce document", etc.)
- Résoudre ces références vers les entités/documents du contexte
- Enrichir les queries avant envoi au RAG/KG
"""

from __future__ import annotations

import re
import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from knowbase.memory.session_manager import SessionManager, get_session_manager

logger = logging.getLogger(__name__)


@dataclass
class ResolvedReference:
    """Référence implicite résolue."""
    original_text: str  # Texte original ("il", "ce document")
    resolved_text: str  # Texte résolu ("SAP S/4HANA", "le document CRR.pptx")
    reference_type: str  # entity | document | topic | unknown
    confidence: float  # Score de confiance 0.0-1.0
    source: str  # d'où vient la résolution (recent_message, context_metadata, etc.)


@dataclass
class ContextState:
    """État du contexte conversationnel."""
    # Entités récemment mentionnées (ordonnées par récence)
    recent_entities: List[Dict[str, Any]] = field(default_factory=list)

    # Documents récemment référencés
    recent_documents: List[Dict[str, Any]] = field(default_factory=list)

    # Sujets actifs de la conversation
    active_topics: List[str] = field(default_factory=list)

    # Dernière question posée (pour "oui"/"non" contextuels)
    last_question: Optional[str] = None

    # Dernier résultat de recherche (pour "le premier", "le deuxième")
    last_search_results: List[Dict[str, Any]] = field(default_factory=list)


class ContextResolver:
    """
    Résout les références implicites dans les messages utilisateur.

    Patterns supportés:
    - Pronoms: "il", "elle", "ils", "elles", "ça", "ceci", "cela"
    - Références documentaires: "ce document", "le fichier", "cette présentation"
    - Références d'entités: "cette solution", "ce produit", "cette technologie"
    - Références ordinales: "le premier", "le deuxième", "ce dernier"
    - Références temporelles: "le précédent", "celui-ci"

    Usage:
        resolver = ContextResolver(session_id="session-123")
        resolved_query, references = resolver.resolve("Quels sont ses avantages?")
        # resolved_query = "Quels sont les avantages de SAP S/4HANA?"
    """

    # Patterns de références implicites (français)
    PRONOUN_PATTERNS = [
        (r'\b(il|elle)\b', 'entity_singular'),
        (r'\b(ils|elles)\b', 'entity_plural'),
        (r'\b(ça|ceci|cela)\b', 'generic'),
        (r'\b(celui-ci|celle-ci)\b', 'recent_singular'),
        (r'\b(ceux-ci|celles-ci)\b', 'recent_plural'),
        (r'\b(le même|la même)\b', 'same'),
    ]

    DOCUMENT_PATTERNS = [
        (r'\b(ce document|le document|this document)\b', 'document'),
        (r'\b(cette présentation|la présentation)\b', 'presentation'),
        (r'\b(ce fichier|le fichier)\b', 'file'),
        (r'\b(cette slide|la slide|ces slides|les slides)\b', 'slide'),
    ]

    ENTITY_PATTERNS = [
        (r'\b(cette solution|la solution)\b', 'solution'),
        (r'\b(ce produit|le produit)\b', 'product'),
        (r'\b(cette technologie|la technologie)\b', 'technology'),
        (r'\b(cette entreprise|l\'entreprise|la société)\b', 'company'),
    ]

    ORDINAL_PATTERNS = [
        (r'\b(le premier|la première)\b', 0),
        (r'\b(le deuxième|la deuxième|le second|la seconde)\b', 1),
        (r'\b(le troisième|la troisième)\b', 2),
        (r'\b(le dernier|la dernière)\b', -1),
        (r'\b(le précédent|la précédente)\b', -2),
    ]

    def __init__(
        self,
        session_manager: Optional[SessionManager] = None,
        min_confidence: float = 0.5
    ):
        """
        Initialise le ContextResolver.

        Args:
            session_manager: Instance SessionManager (utilise singleton si None)
            min_confidence: Confiance minimale pour accepter une résolution
        """
        self.session_manager = session_manager or get_session_manager()
        self.min_confidence = min_confidence

        # Cache local du contexte par session
        self._context_cache: Dict[str, ContextState] = {}

    def resolve(
        self,
        query: str,
        session_id: str
    ) -> Tuple[str, List[ResolvedReference]]:
        """
        Résout les références implicites dans une query.

        Args:
            query: Query utilisateur originale
            session_id: ID de la session pour contexte

        Returns:
            Tuple (query résolue, liste des références résolues)
        """
        resolved_query = query
        references: List[ResolvedReference] = []

        # Charger le contexte de la session
        context = self._load_context(session_id)

        # 1. Résoudre les références ordinales (le premier, le deuxième...)
        resolved_query, ordinal_refs = self._resolve_ordinals(resolved_query, context)
        references.extend(ordinal_refs)

        # 2. Résoudre les références documentaires
        resolved_query, doc_refs = self._resolve_document_references(resolved_query, context)
        references.extend(doc_refs)

        # 3. Résoudre les références d'entités
        resolved_query, entity_refs = self._resolve_entity_references(resolved_query, context)
        references.extend(entity_refs)

        # 4. Résoudre les pronoms
        resolved_query, pronoun_refs = self._resolve_pronouns(resolved_query, context)
        references.extend(pronoun_refs)

        if references:
            logger.info(f"[ContextResolver] Resolved {len(references)} references in query")
            logger.debug(f"[ContextResolver] Original: '{query}'")
            logger.debug(f"[ContextResolver] Resolved: '{resolved_query}'")

        return resolved_query, references

    def _load_context(self, session_id: str) -> ContextState:
        """
        Charge le contexte conversationnel depuis la session.

        Args:
            session_id: ID de la session

        Returns:
            ContextState avec les données pertinentes
        """
        # Vérifier le cache
        if session_id in self._context_cache:
            return self._context_cache[session_id]

        # Charger depuis SessionManager
        context_data = self.session_manager.get_context_metadata(session_id)
        conversation = self.session_manager.get_conversation_context(
            session_id,
            recent_messages_count=5
        )

        state = ContextState()

        if context_data:
            state.recent_entities = context_data.get("recent_entities", [])
            state.recent_documents = context_data.get("recent_documents", [])
            state.active_topics = context_data.get("active_topics", [])
            state.last_search_results = context_data.get("last_search_results", [])

        # Extraire entités des messages récents
        if conversation and "messages" in conversation:
            for msg in conversation["messages"]:
                if msg.get("entities"):
                    for entity in msg["entities"]:
                        if entity not in [e.get("name") for e in state.recent_entities]:
                            state.recent_entities.insert(0, {"name": entity, "source": "message"})

                if msg.get("documents"):
                    for doc in msg["documents"]:
                        if doc not in [d.get("name") for d in state.recent_documents]:
                            state.recent_documents.insert(0, {"name": doc, "source": "message"})

        # Cacher le contexte
        self._context_cache[session_id] = state
        return state

    def _resolve_pronouns(
        self,
        query: str,
        context: ContextState
    ) -> Tuple[str, List[ResolvedReference]]:
        """Résout les pronoms vers les entités récentes."""
        resolved = query
        references = []

        for pattern, ref_type in self.PRONOUN_PATTERNS:
            matches = list(re.finditer(pattern, resolved, re.IGNORECASE))

            for match in matches:
                original = match.group(0)

                # Trouver l'entité la plus récente appropriée
                if ref_type == 'entity_singular' and context.recent_entities:
                    entity = context.recent_entities[0]
                    resolved_text = entity.get("name", original)
                    confidence = 0.7

                    ref = ResolvedReference(
                        original_text=original,
                        resolved_text=resolved_text,
                        reference_type="entity",
                        confidence=confidence,
                        source="recent_entities"
                    )

                    if confidence >= self.min_confidence:
                        resolved = resolved.replace(original, resolved_text, 1)
                        references.append(ref)

                elif ref_type == 'generic' and context.recent_entities:
                    # "ça", "ceci", "cela" → entité ou sujet le plus récent
                    entity = context.recent_entities[0]
                    resolved_text = entity.get("name", original)
                    confidence = 0.6

                    ref = ResolvedReference(
                        original_text=original,
                        resolved_text=resolved_text,
                        reference_type="entity",
                        confidence=confidence,
                        source="recent_entities"
                    )

                    if confidence >= self.min_confidence:
                        resolved = resolved.replace(original, resolved_text, 1)
                        references.append(ref)

        return resolved, references

    def _resolve_document_references(
        self,
        query: str,
        context: ContextState
    ) -> Tuple[str, List[ResolvedReference]]:
        """Résout les références documentaires."""
        resolved = query
        references = []

        for pattern, doc_type in self.DOCUMENT_PATTERNS:
            matches = list(re.finditer(pattern, resolved, re.IGNORECASE))

            for match in matches:
                original = match.group(0)

                if context.recent_documents:
                    doc = context.recent_documents[0]
                    doc_name = doc.get("name", doc.get("filename", ""))

                    if doc_name:
                        resolved_text = f"le document '{doc_name}'"
                        confidence = 0.8

                        ref = ResolvedReference(
                            original_text=original,
                            resolved_text=resolved_text,
                            reference_type="document",
                            confidence=confidence,
                            source="recent_documents"
                        )

                        if confidence >= self.min_confidence:
                            resolved = resolved.replace(original, resolved_text, 1)
                            references.append(ref)

        return resolved, references

    def _resolve_entity_references(
        self,
        query: str,
        context: ContextState
    ) -> Tuple[str, List[ResolvedReference]]:
        """Résout les références d'entités typées."""
        resolved = query
        references = []

        for pattern, entity_type in self.ENTITY_PATTERNS:
            matches = list(re.finditer(pattern, resolved, re.IGNORECASE))

            for match in matches:
                original = match.group(0)

                # Chercher une entité du type correspondant
                for entity in context.recent_entities:
                    ent_type = entity.get("type", "").lower()

                    # Match approximatif du type
                    if entity_type in ent_type or ent_type in entity_type:
                        resolved_text = entity.get("name", original)
                        confidence = 0.75

                        ref = ResolvedReference(
                            original_text=original,
                            resolved_text=resolved_text,
                            reference_type="entity",
                            confidence=confidence,
                            source="recent_entities_typed"
                        )

                        if confidence >= self.min_confidence:
                            resolved = resolved.replace(original, resolved_text, 1)
                            references.append(ref)
                            break

        return resolved, references

    def _resolve_ordinals(
        self,
        query: str,
        context: ContextState
    ) -> Tuple[str, List[ResolvedReference]]:
        """Résout les références ordinales (le premier, le deuxième...)."""
        resolved = query
        references = []

        if not context.last_search_results:
            return resolved, references

        for pattern, index in self.ORDINAL_PATTERNS:
            matches = list(re.finditer(pattern, resolved, re.IGNORECASE))

            for match in matches:
                original = match.group(0)

                try:
                    result = context.last_search_results[index]
                    result_name = result.get("title", result.get("name", ""))

                    if result_name:
                        resolved_text = f"'{result_name}'"
                        confidence = 0.85

                        ref = ResolvedReference(
                            original_text=original,
                            resolved_text=resolved_text,
                            reference_type="search_result",
                            confidence=confidence,
                            source="last_search_results"
                        )

                        if confidence >= self.min_confidence:
                            resolved = resolved.replace(original, resolved_text, 1)
                            references.append(ref)

                except (IndexError, KeyError):
                    pass

        return resolved, references

    def update_context(
        self,
        session_id: str,
        entities: Optional[List[Dict[str, Any]]] = None,
        documents: Optional[List[Dict[str, Any]]] = None,
        search_results: Optional[List[Dict[str, Any]]] = None,
        topics: Optional[List[str]] = None
    ) -> None:
        """
        Met à jour le contexte avec de nouvelles informations.

        Appelé après chaque réponse pour maintenir le contexte à jour.

        Args:
            session_id: ID de la session
            entities: Entités mentionnées dans la réponse
            documents: Documents référencés
            search_results: Résultats de recherche retournés
            topics: Sujets discutés
        """
        # Charger contexte existant
        context = self._load_context(session_id)

        # Mettre à jour avec nouvelles données (les plus récentes en premier)
        if entities:
            for entity in reversed(entities):
                context.recent_entities.insert(0, entity)
            # Garder max 20 entités
            context.recent_entities = context.recent_entities[:20]

        if documents:
            for doc in reversed(documents):
                context.recent_documents.insert(0, doc)
            context.recent_documents = context.recent_documents[:10]

        if search_results:
            context.last_search_results = search_results

        if topics:
            context.active_topics = topics

        # Persister dans SessionManager
        metadata = {
            "recent_entities": context.recent_entities,
            "recent_documents": context.recent_documents,
            "last_search_results": context.last_search_results,
            "active_topics": context.active_topics
        }
        self.session_manager.update_context_metadata(session_id, metadata)

        # Mettre à jour le cache
        self._context_cache[session_id] = context

        logger.debug(f"[ContextResolver] Updated context for session {session_id}")

    def clear_context(self, session_id: str) -> None:
        """
        Efface le contexte d'une session.

        Args:
            session_id: ID de la session
        """
        if session_id in self._context_cache:
            del self._context_cache[session_id]

        self.session_manager.update_context_metadata(session_id, {
            "recent_entities": [],
            "recent_documents": [],
            "last_search_results": [],
            "active_topics": []
        })

        logger.info(f"[ContextResolver] Cleared context for session {session_id}")


# Singleton
_context_resolver: Optional[ContextResolver] = None


def get_context_resolver() -> ContextResolver:
    """
    Factory pour obtenir l'instance ContextResolver singleton.

    Usage:
        from knowbase.memory import get_context_resolver

        resolver = get_context_resolver()
        resolved_query, refs = resolver.resolve("Quels sont ses avantages?", session_id)
    """
    global _context_resolver
    if _context_resolver is None:
        _context_resolver = ContextResolver()
    return _context_resolver
