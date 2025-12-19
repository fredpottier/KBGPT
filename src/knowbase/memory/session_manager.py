"""
SessionManager - Wrapper hybride LangChain Memory + Persistence PostgreSQL.

Phase 2.5 - Memory Layer

Architecture:
- Persistence: PostgreSQL via SQLAlchemy (Session, SessionMessage models)
- Memory: LangChain ConversationSummaryBufferMemory pour auto-summarization
- Token Management: Limite configurable avec summarization automatique
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from sqlalchemy.orm import Session as DBSession
from sqlalchemy import desc

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain.memory import ConversationSummaryBufferMemory
from langchain_openai import ChatOpenAI

from knowbase.db.base import SessionLocal
from knowbase.db.models import Session, SessionMessage, User
from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class MessageData:
    """Structure pour un message de conversation."""
    role: str  # user | assistant | system
    content: str
    entities_mentioned: Optional[List[str]] = None
    documents_referenced: Optional[List[str]] = None
    model_used: Optional[str] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    latency_ms: Optional[int] = None


class SessionManager:
    """
    Gestionnaire de sessions de conversation hybride.

    Combine:
    - Persistence PostgreSQL pour durabilité
    - LangChain Memory pour gestion intelligente du contexte

    Usage:
        manager = SessionManager()

        # Créer une session
        session = manager.create_session(user_id="user-123")

        # Ajouter un message
        manager.add_message(session.id, MessageData(role="user", content="Hello"))

        # Obtenir le contexte pour le LLM
        context = manager.get_conversation_context(session.id)
    """

    # Configuration par défaut
    DEFAULT_MAX_TOKEN_LIMIT = 2000  # Tokens max avant summarization
    DEFAULT_SUMMARY_MODEL = "gpt-4o-mini"  # Modèle pour summarization

    def __init__(
        self,
        max_token_limit: int = DEFAULT_MAX_TOKEN_LIMIT,
        summary_model: str = DEFAULT_SUMMARY_MODEL
    ):
        """
        Initialise le SessionManager.

        Args:
            max_token_limit: Limite tokens avant auto-summarization
            summary_model: Modèle LLM pour générer les résumés
        """
        self.max_token_limit = max_token_limit
        self.summary_model = summary_model

        # Cache des LangChain Memory par session (en mémoire)
        self._memory_cache: Dict[str, ConversationSummaryBufferMemory] = {}

        logger.info(f"[SessionManager] Initialized with max_tokens={max_token_limit}")

    # =========================================================================
    # Session CRUD
    # =========================================================================

    def create_session(
        self,
        user_id: str,
        title: Optional[str] = None,
        tenant_id: str = "default"
    ) -> Session:
        """
        Crée une nouvelle session de conversation.

        Args:
            user_id: ID de l'utilisateur propriétaire
            title: Titre optionnel (auto-généré si None)
            tenant_id: ID du tenant pour isolation multi-tenant

        Returns:
            Session créée
        """
        db = SessionLocal()
        try:
            session = Session(
                user_id=user_id,
                title=title or f"Conversation {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                tenant_id=tenant_id,
                is_active=True,
                message_count=0,
                token_count=0
            )
            db.add(session)
            db.commit()
            db.refresh(session)

            logger.info(f"[SessionManager] Created session {session.id} for user {user_id}")
            return session
        finally:
            db.close()

    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Récupère une session par ID.

        Args:
            session_id: UUID de la session

        Returns:
            Session ou None si non trouvée
        """
        db = SessionLocal()
        try:
            return db.query(Session).filter(Session.id == session_id).first()
        finally:
            db.close()

    def get_user_sessions(
        self,
        user_id: str,
        tenant_id: str = "default",
        active_only: bool = True,
        limit: int = 20
    ) -> List[Session]:
        """
        Liste les sessions d'un utilisateur.

        Args:
            user_id: ID de l'utilisateur
            tenant_id: ID du tenant
            active_only: Filtrer uniquement les sessions actives
            limit: Nombre max de sessions à retourner

        Returns:
            Liste des sessions, triées par dernière activité
        """
        db = SessionLocal()
        try:
            query = db.query(Session).filter(
                Session.user_id == user_id,
                Session.tenant_id == tenant_id
            )

            if active_only:
                query = query.filter(Session.is_active == True)

            return query.order_by(desc(Session.updated_at)).limit(limit).all()
        finally:
            db.close()

    def archive_session(self, session_id: str) -> bool:
        """
        Archive une session (soft delete).

        Args:
            session_id: UUID de la session

        Returns:
            True si succès
        """
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session:
                session.is_active = False
                db.commit()

                # Nettoyer le cache mémoire
                if session_id in self._memory_cache:
                    del self._memory_cache[session_id]

                logger.info(f"[SessionManager] Archived session {session_id}")
                return True
            return False
        finally:
            db.close()

    def delete_session(self, session_id: str) -> bool:
        """
        Supprime définitivement une session et ses messages.

        Args:
            session_id: UUID de la session

        Returns:
            True si succès
        """
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session:
                db.delete(session)  # CASCADE delete messages
                db.commit()

                # Nettoyer le cache mémoire
                if session_id in self._memory_cache:
                    del self._memory_cache[session_id]

                logger.info(f"[SessionManager] Deleted session {session_id}")
                return True
            return False
        finally:
            db.close()

    def update_session_title(self, session_id: str, title: str) -> bool:
        """
        Met à jour le titre d'une session.

        Args:
            session_id: UUID de la session
            title: Nouveau titre

        Returns:
            True si succès
        """
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session:
                session.title = title
                db.commit()
                return True
            return False
        finally:
            db.close()

    # =========================================================================
    # Message Management
    # =========================================================================

    def add_message(
        self,
        session_id: str,
        message: MessageData
    ) -> Optional[SessionMessage]:
        """
        Ajoute un message à une session.

        Met à jour automatiquement:
        - Les compteurs de la session
        - Le résumé LangChain si nécessaire
        - Le timestamp last_message_at

        Args:
            session_id: UUID de la session
            message: Données du message

        Returns:
            SessionMessage créé ou None si erreur
        """
        db = SessionLocal()
        try:
            # Vérifier que la session existe
            session = db.query(Session).filter(Session.id == session_id).first()
            if not session:
                logger.error(f"[SessionManager] Session {session_id} not found")
                return None

            # Créer le message
            db_message = SessionMessage(
                session_id=session_id,
                role=message.role,
                content=message.content,
                entities_mentioned=json.dumps(message.entities_mentioned) if message.entities_mentioned else None,
                documents_referenced=json.dumps(message.documents_referenced) if message.documents_referenced else None,
                model_used=message.model_used,
                tokens_input=message.tokens_input,
                tokens_output=message.tokens_output,
                latency_ms=message.latency_ms,
                tenant_id=session.tenant_id
            )
            db.add(db_message)

            # Mettre à jour les compteurs de la session
            session.message_count += 1
            session.last_message_at = datetime.now(timezone.utc)

            if message.tokens_input:
                session.token_count += message.tokens_input
            if message.tokens_output:
                session.token_count += message.tokens_output

            db.commit()
            db.refresh(db_message)

            # Mettre à jour LangChain Memory (avant de fermer la session DB)
            self._update_langchain_memory(session_id, message, db)

            logger.debug(f"[SessionManager] Added message to session {session_id}")

            # Détacher l'objet de la session en le convertissant explicitement
            # pour éviter DetachedInstanceError
            db.expunge(db_message)
            return db_message

        except Exception as e:
            logger.error(f"[SessionManager] Error adding message: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[SessionMessage]:
        """
        Récupère les messages d'une session.

        Args:
            session_id: UUID de la session
            limit: Nombre max de messages
            offset: Offset pour pagination

        Returns:
            Liste des messages, triés par date croissante
        """
        db = SessionLocal()
        try:
            query = db.query(SessionMessage).filter(
                SessionMessage.session_id == session_id
            ).order_by(SessionMessage.created_at)

            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)

            return query.all()
        finally:
            db.close()

    def get_recent_messages(
        self,
        session_id: str,
        count: int = 10
    ) -> List[SessionMessage]:
        """
        Récupère les N derniers messages d'une session.

        Args:
            session_id: UUID de la session
            count: Nombre de messages à récupérer

        Returns:
            Liste des messages récents
        """
        db = SessionLocal()
        try:
            return db.query(SessionMessage).filter(
                SessionMessage.session_id == session_id
            ).order_by(desc(SessionMessage.created_at)).limit(count).all()[::-1]
        finally:
            db.close()

    # =========================================================================
    # LangChain Memory Integration
    # =========================================================================

    def _get_or_create_memory(self, session_id: str, db: DBSession) -> ConversationSummaryBufferMemory:
        """
        Obtient ou crée le LangChain Memory pour une session.

        Args:
            session_id: UUID de la session
            db: Session DB active

        Returns:
            ConversationSummaryBufferMemory configuré
        """
        if session_id not in self._memory_cache:
            # Créer nouveau memory
            llm = ChatOpenAI(
                model=self.summary_model,
                temperature=0
            )

            memory = ConversationSummaryBufferMemory(
                llm=llm,
                max_token_limit=self.max_token_limit,
                return_messages=True
            )

            # Charger l'historique existant depuis DB
            session = db.query(Session).filter(Session.id == session_id).first()
            if session and session.summary:
                # Restaurer le résumé existant
                memory.moving_summary_buffer = session.summary

            # Charger les messages récents (non résumés)
            recent_messages = db.query(SessionMessage).filter(
                SessionMessage.session_id == session_id
            ).order_by(SessionMessage.created_at).limit(50).all()

            for msg in recent_messages:
                if msg.role == "user":
                    memory.chat_memory.add_user_message(msg.content)
                elif msg.role == "assistant":
                    memory.chat_memory.add_ai_message(msg.content)

            self._memory_cache[session_id] = memory
            logger.debug(f"[SessionManager] Created LangChain Memory for session {session_id}")

        return self._memory_cache[session_id]

    def _update_langchain_memory(
        self,
        session_id: str,
        message: MessageData,
        db: DBSession
    ) -> None:
        """
        Met à jour le LangChain Memory avec un nouveau message.

        Args:
            session_id: UUID de la session
            message: Message ajouté
            db: Session DB active
        """
        try:
            memory = self._get_or_create_memory(session_id, db)

            if message.role == "user":
                memory.chat_memory.add_user_message(message.content)
            elif message.role == "assistant":
                memory.chat_memory.add_ai_message(message.content)

            # Persister le résumé mis à jour
            session = db.query(Session).filter(Session.id == session_id).first()
            if session and hasattr(memory, 'moving_summary_buffer'):
                session.summary = memory.moving_summary_buffer
                db.commit()

        except Exception as e:
            logger.error(f"[SessionManager] Error updating LangChain Memory: {e}")

    # =========================================================================
    # Context for LLM
    # =========================================================================

    def get_conversation_context(
        self,
        session_id: str,
        include_summary: bool = True,
        recent_messages_count: int = 10
    ) -> Dict[str, Any]:
        """
        Obtient le contexte de conversation pour le LLM.

        Combine:
        - Résumé des échanges précédents (si long historique)
        - Messages récents complets
        - Métadonnées de session

        Args:
            session_id: UUID de la session
            include_summary: Inclure le résumé auto-généré
            recent_messages_count: Nombre de messages récents à inclure

        Returns:
            Dict avec summary, messages, et metadata
        """
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if not session:
                return {"error": "Session not found"}

            # Récupérer messages récents
            recent_messages = db.query(SessionMessage).filter(
                SessionMessage.session_id == session_id
            ).order_by(desc(SessionMessage.created_at)).limit(recent_messages_count).all()[::-1]

            # Construire le contexte
            context = {
                "session_id": session_id,
                "title": session.title,
                "message_count": session.message_count,
                "summary": session.summary if include_summary else None,
                "messages": [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                        "entities": json.loads(msg.entities_mentioned) if msg.entities_mentioned else None,
                        "documents": json.loads(msg.documents_referenced) if msg.documents_referenced else None
                    }
                    for msg in recent_messages
                ],
                "context_metadata": json.loads(session.context_metadata) if session.context_metadata else None
            }

            return context

        finally:
            db.close()

    def get_langchain_messages(
        self,
        session_id: str
    ) -> List:
        """
        Obtient les messages au format LangChain pour injection directe.

        Args:
            session_id: UUID de la session

        Returns:
            Liste de HumanMessage/AIMessage
        """
        db = SessionLocal()
        try:
            memory = self._get_or_create_memory(session_id, db)
            return memory.chat_memory.messages
        finally:
            db.close()

    # =========================================================================
    # Context Metadata
    # =========================================================================

    def update_context_metadata(
        self,
        session_id: str,
        metadata: Dict[str, Any]
    ) -> bool:
        """
        Met à jour les métadonnées de contexte d'une session.

        Utilisé par le ContextResolver pour stocker:
        - Entités récemment mentionnées
        - Documents référencés
        - Sujets actifs

        Args:
            session_id: UUID de la session
            metadata: Dictionnaire de métadonnées

        Returns:
            True si succès
        """
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session:
                # Merger avec metadata existante
                existing = json.loads(session.context_metadata) if session.context_metadata else {}
                existing.update(metadata)
                session.context_metadata = json.dumps(existing)
                db.commit()
                return True
            return False
        finally:
            db.close()

    def get_context_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les métadonnées de contexte d'une session.

        Args:
            session_id: UUID de la session

        Returns:
            Dictionnaire de métadonnées ou None
        """
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session and session.context_metadata:
                return json.loads(session.context_metadata)
            return None
        finally:
            db.close()

    # =========================================================================
    # Feedback
    # =========================================================================

    def add_feedback(
        self,
        message_id: str,
        rating: int,
        comment: Optional[str] = None
    ) -> bool:
        """
        Ajoute un feedback utilisateur à un message.

        Args:
            message_id: UUID du message
            rating: 1 (thumbs down) ou 2 (thumbs up)
            comment: Commentaire optionnel

        Returns:
            True si succès
        """
        if rating not in [1, 2]:
            logger.warning(f"[SessionManager] Invalid rating: {rating}")
            return False

        db = SessionLocal()
        try:
            message = db.query(SessionMessage).filter(SessionMessage.id == message_id).first()
            if message:
                message.feedback_rating = rating
                message.feedback_comment = comment
                db.commit()
                logger.info(f"[SessionManager] Added feedback to message {message_id}: {rating}")
                return True
            return False
        finally:
            db.close()

    # =========================================================================
    # Auto-title generation
    # =========================================================================

    async def generate_session_title(
        self,
        session_id: str,
        force: bool = False
    ) -> Optional[str]:
        """
        Génère automatiquement un titre pour la session basé sur le contenu.

        Args:
            session_id: UUID de la session
            force: Forcer la regénération même si titre existe

        Returns:
            Titre généré ou None si échec
        """
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if not session:
                return None

            # Ne pas regénérer si titre existe et pas forcé
            if session.title and not session.title.startswith("Conversation ") and not force:
                return session.title

            # Récupérer premiers messages pour contexte
            first_messages = db.query(SessionMessage).filter(
                SessionMessage.session_id == session_id
            ).order_by(SessionMessage.created_at).limit(3).all()

            if not first_messages:
                return None

            # Extraire le contenu pour génération du titre
            content = "\n".join([
                f"{msg.role}: {msg.content[:200]}"
                for msg in first_messages
            ])

            # Générer titre via LLM
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
            response = await llm.ainvoke([
                SystemMessage(content="Génère un titre court (max 50 caractères) pour cette conversation. Réponds uniquement avec le titre, sans guillemets."),
                HumanMessage(content=content)
            ])

            title = response.content.strip()[:100]  # Limite à 100 chars

            # Mettre à jour
            session.title = title
            db.commit()

            logger.info(f"[SessionManager] Generated title for session {session_id}: {title}")
            return title

        except Exception as e:
            logger.error(f"[SessionManager] Error generating title: {e}")
            return None
        finally:
            db.close()


# Singleton pour usage global
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """
    Factory pour obtenir l'instance SessionManager singleton.

    Usage:
        from knowbase.memory import get_session_manager

        manager = get_session_manager()
        session = manager.create_session(user_id="...")
    """
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
