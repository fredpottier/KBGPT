"""
Router API pour la gestion des sessions de conversation.

Phase 2.5 - Memory Layer

Endpoints:
- CRUD Sessions
- Messages
- Contexte conversationnel
- Feedback
- Résolution de références
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from knowbase.api.schemas.sessions import (
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    SessionListResponse,
    MessageCreate,
    MessageResponse,
    MessageListResponse,
    ConversationContext,
    ContextUpdate,
    FeedbackCreate,
    FeedbackResponse,
    ResolveRequest,
    ResolveResponse,
    ResolvedReferenceSchema,
    SummaryRequest,
    SummaryResponse,
    KeyPointSchema
)
from knowbase.api.dependencies import get_current_user
from knowbase.memory import (
    get_session_manager,
    get_context_resolver,
    get_intelligent_summarizer,
    MessageData,
    SessionManager,
    ContextResolver,
    IntelligentSummarizer,
    SummaryFormat
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


# ============================================================================
# Dependencies
# ============================================================================


def get_manager() -> SessionManager:
    """Dependency pour obtenir le SessionManager."""
    return get_session_manager()


def get_resolver() -> ContextResolver:
    """Dependency pour obtenir le ContextResolver."""
    return get_context_resolver()


def get_summarizer() -> IntelligentSummarizer:
    """Dependency pour obtenir l'IntelligentSummarizer."""
    return get_intelligent_summarizer()


# ============================================================================
# Session CRUD Endpoints
# ============================================================================


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une nouvelle session",
    description="Crée une nouvelle session de conversation pour l'utilisateur authentifié."
)
async def create_session(
    data: SessionCreate,
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager)
):
    """Crée une nouvelle session de conversation."""
    session = manager.create_session(
        user_id=current_user["sub"],
        title=data.title,
        tenant_id=current_user["tenant_id"]
    )

    logger.info(f"[API] Created session {session.id} for user {current_user['email']}")
    return session


@router.get(
    "",
    response_model=SessionListResponse,
    summary="Lister les sessions",
    description="Liste les sessions de conversation de l'utilisateur authentifié."
)
async def list_sessions(
    active_only: bool = Query(True, description="Filtrer uniquement les sessions actives"),
    limit: int = Query(20, ge=1, le=100, description="Nombre max de sessions"),
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager)
):
    """Liste les sessions de l'utilisateur."""
    sessions = manager.get_user_sessions(
        user_id=current_user["sub"],
        tenant_id=current_user["tenant_id"],
        active_only=active_only,
        limit=limit
    )

    return SessionListResponse(
        sessions=[SessionResponse.model_validate(s) for s in sessions],
        total=len(sessions)
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Détails d'une session",
    description="Récupère les détails d'une session spécifique."
)
async def get_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager)
):
    """Récupère une session par ID."""
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    # Vérifier ownership
    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    return session


@router.patch(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Mettre à jour une session",
    description="Met à jour le titre ou l'état d'une session."
)
async def update_session(
    session_id: str,
    data: SessionUpdate,
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager)
):
    """Met à jour une session."""
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    if data.title is not None:
        manager.update_session_title(session_id, data.title)

    if data.is_active is False:
        manager.archive_session(session_id)

    # Recharger la session
    return manager.get_session(session_id)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une session",
    description="Supprime définitivement une session et tous ses messages."
)
async def delete_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager)
):
    """Supprime une session."""
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    success = manager.delete_session(session_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la suppression"
        )

    logger.info(f"[API] Deleted session {session_id}")


# ============================================================================
# Message Endpoints
# ============================================================================


@router.post(
    "/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un message",
    description="Ajoute un nouveau message à une session."
)
async def add_message(
    session_id: str,
    data: MessageCreate,
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager)
):
    """Ajoute un message à une session."""
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    message_data = MessageData(
        role=data.role,
        content=data.content,
        entities_mentioned=data.entities_mentioned,
        documents_referenced=data.documents_referenced,
        model_used=data.model_used,
        tokens_input=data.tokens_input,
        tokens_output=data.tokens_output,
        latency_ms=data.latency_ms
    )

    message = manager.add_message(session_id, message_data)

    if not message:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de l'ajout du message"
        )

    # Convertir JSON strings en listes pour la réponse
    response_data = {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "entities_mentioned": json.loads(message.entities_mentioned) if message.entities_mentioned else None,
        "documents_referenced": json.loads(message.documents_referenced) if message.documents_referenced else None,
        "model_used": message.model_used,
        "tokens_input": message.tokens_input,
        "tokens_output": message.tokens_output,
        "latency_ms": message.latency_ms,
        "feedback_rating": message.feedback_rating,
        "feedback_comment": message.feedback_comment,
        "created_at": message.created_at
    }

    return MessageResponse(**response_data)


@router.get(
    "/{session_id}/messages",
    response_model=MessageListResponse,
    summary="Lister les messages",
    description="Liste les messages d'une session."
)
async def list_messages(
    session_id: str,
    limit: Optional[int] = Query(None, ge=1, le=100, description="Nombre max de messages"),
    offset: int = Query(0, ge=0, description="Offset pour pagination"),
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager)
):
    """Liste les messages d'une session."""
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    messages = manager.get_messages(session_id, limit=limit, offset=offset)

    # Convertir JSON strings en listes pour la réponse
    message_responses = []
    for msg in messages:
        response_data = {
            "id": msg.id,
            "session_id": msg.session_id,
            "role": msg.role,
            "content": msg.content,
            "entities_mentioned": json.loads(msg.entities_mentioned) if msg.entities_mentioned else None,
            "documents_referenced": json.loads(msg.documents_referenced) if msg.documents_referenced else None,
            "model_used": msg.model_used,
            "tokens_input": msg.tokens_input,
            "tokens_output": msg.tokens_output,
            "latency_ms": msg.latency_ms,
            "feedback_rating": msg.feedback_rating,
            "feedback_comment": msg.feedback_comment,
            "created_at": msg.created_at
        }
        message_responses.append(MessageResponse(**response_data))

    return MessageListResponse(
        messages=message_responses,
        total=len(message_responses),
        session_id=session_id
    )


# ============================================================================
# Context Endpoints
# ============================================================================


@router.get(
    "/{session_id}/context",
    response_model=ConversationContext,
    summary="Obtenir le contexte",
    description="Obtient le contexte de conversation pour le LLM."
)
async def get_context(
    session_id: str,
    include_summary: bool = Query(True, description="Inclure le résumé auto-généré"),
    recent_count: int = Query(10, ge=1, le=50, description="Nombre de messages récents"),
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager)
):
    """Obtient le contexte conversationnel."""
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    context = manager.get_conversation_context(
        session_id,
        include_summary=include_summary,
        recent_messages_count=recent_count
    )

    return ConversationContext(**context)


@router.put(
    "/{session_id}/context",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mettre à jour le contexte",
    description="Met à jour les métadonnées de contexte d'une session."
)
async def update_context(
    session_id: str,
    data: ContextUpdate,
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager),
    resolver: ContextResolver = Depends(get_resolver)
):
    """Met à jour le contexte conversationnel."""
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    resolver.update_context(
        session_id,
        entities=data.entities,
        documents=data.documents,
        search_results=data.search_results,
        topics=data.topics
    )


# ============================================================================
# Feedback Endpoint
# ============================================================================


@router.post(
    "/{session_id}/messages/{message_id}/feedback",
    response_model=FeedbackResponse,
    summary="Ajouter un feedback",
    description="Ajoute un feedback utilisateur (thumbs up/down) sur un message."
)
async def add_feedback(
    session_id: str,
    message_id: str,
    data: FeedbackCreate,
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager)
):
    """Ajoute un feedback sur un message."""
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    success = manager.add_feedback(
        message_id=message_id,
        rating=data.rating,
        comment=data.comment
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message non trouvé"
        )

    return FeedbackResponse(
        message_id=message_id,
        rating=data.rating,
        comment=data.comment,
        success=True
    )


# ============================================================================
# Reference Resolution Endpoint
# ============================================================================


@router.post(
    "/resolve",
    response_model=ResolveResponse,
    summary="Résoudre les références",
    description="Résout les références implicites dans une query (il, ça, ce document...)."
)
async def resolve_references(
    data: ResolveRequest,
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager),
    resolver: ContextResolver = Depends(get_resolver)
):
    """Résout les références implicites dans une query."""
    session = manager.get_session(data.session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    resolved_query, references = resolver.resolve(data.query, data.session_id)

    return ResolveResponse(
        original_query=data.query,
        resolved_query=resolved_query,
        references=[
            ResolvedReferenceSchema(
                original_text=ref.original_text,
                resolved_text=ref.resolved_text,
                reference_type=ref.reference_type,
                confidence=ref.confidence,
                source=ref.source
            )
            for ref in references
        ],
        has_changes=resolved_query != data.query
    )


# ============================================================================
# Title Generation Endpoint
# ============================================================================


@router.post(
    "/{session_id}/generate-title",
    response_model=SessionResponse,
    summary="Générer un titre",
    description="Génère automatiquement un titre basé sur le contenu de la conversation."
)
async def generate_title(
    session_id: str,
    force: bool = Query(False, description="Forcer la regénération"),
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager)
):
    """Génère un titre pour la session."""
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    title = await manager.generate_session_title(session_id, force=force)

    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de générer un titre (pas assez de messages)"
        )

    # Recharger la session avec le nouveau titre
    return manager.get_session(session_id)


# ============================================================================
# Summary Endpoints
# ============================================================================


@router.post(
    "/{session_id}/summary",
    response_model=SummaryResponse,
    summary="Générer un résumé intelligent",
    description="Génère un compte-rendu métier structuré de la session de conversation."
)
async def generate_summary(
    session_id: str,
    data: SummaryRequest = SummaryRequest(),
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager),
    summarizer: IntelligentSummarizer = Depends(get_summarizer)
):
    """
    Génère un résumé intelligent de la session.

    Formats disponibles:
    - **business**: Orienté décideur, points clés et actions (défaut)
    - **technical**: Détails techniques, références précises
    - **executive**: Ultra-concis, 3-5 bullet points

    Le résumé inclut:
    - Contexte/objectif de recherche identifié
    - Points clés avec sources documentaires
    - Actions recommandées
    - Zones non explorées suggérées
    """
    # Vérifier que la session existe
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    # Vérifier l'accès
    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    # Récupérer les messages
    messages = manager.get_messages(session_id)

    if not messages or len(messages) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pas assez de messages pour générer un résumé (minimum 2 messages requis)"
        )

    # Mapper le format
    format_map = {
        "business": SummaryFormat.BUSINESS,
        "technical": SummaryFormat.TECHNICAL,
        "executive": SummaryFormat.EXECUTIVE
    }
    summary_format = format_map.get(data.format.lower(), SummaryFormat.BUSINESS)

    # Générer le résumé
    try:
        summary = summarizer.generate_summary(
            session=session,
            messages=messages,
            format=summary_format
        )

        # Convertir en réponse API
        return SummaryResponse(
            session_id=summary.session_id,
            title=summary.title,
            generated_at=summary.generated_at,
            format=summary.format.value,
            context=summary.context,
            key_points=[
                KeyPointSchema(point=kp["point"], source=kp.get("source"))
                for kp in summary.key_points
            ],
            actions=summary.actions,
            unexplored_areas=summary.unexplored_areas,
            question_count=summary.question_count,
            sources_count=summary.sources_count,
            duration_minutes=summary.duration_minutes,
            concepts_explored=summary.concepts_explored,
            full_text=summary.full_text
        )

    except Exception as e:
        logger.error(f"[SUMMARY] Generation failed for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la génération du résumé: {str(e)}"
        )


@router.get(
    "/{session_id}/summary",
    response_model=SummaryResponse,
    summary="Obtenir le dernier résumé",
    description="Récupère le dernier résumé généré pour la session (si disponible)."
)
async def get_summary(
    session_id: str,
    format: str = Query("business", description="Format souhaité si régénération"),
    regenerate: bool = Query(False, description="Forcer la régénération"),
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_manager),
    summarizer: IntelligentSummarizer = Depends(get_summarizer)
):
    """
    Récupère le résumé de la session.

    Si `regenerate=true`, génère un nouveau résumé.
    Sinon, retourne le résumé mis en cache (si disponible).
    """
    # Vérifier que la session existe
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvée"
        )

    # Vérifier l'accès
    if session.user_id != current_user["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à cette session"
        )

    # Pour l'instant, toujours régénérer (pas de cache implémenté)
    # TODO: Ajouter cache dans Session model (summary_json, summary_generated_at)
    messages = manager.get_messages(session_id)

    if not messages or len(messages) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pas assez de messages pour générer un résumé"
        )

    format_map = {
        "business": SummaryFormat.BUSINESS,
        "technical": SummaryFormat.TECHNICAL,
        "executive": SummaryFormat.EXECUTIVE
    }
    summary_format = format_map.get(format.lower(), SummaryFormat.BUSINESS)

    try:
        summary = summarizer.generate_summary(
            session=session,
            messages=messages,
            format=summary_format
        )

        return SummaryResponse(
            session_id=summary.session_id,
            title=summary.title,
            generated_at=summary.generated_at,
            format=summary.format.value,
            context=summary.context,
            key_points=[
                KeyPointSchema(point=kp["point"], source=kp.get("source"))
                for kp in summary.key_points
            ],
            actions=summary.actions,
            unexplored_areas=summary.unexplored_areas,
            question_count=summary.question_count,
            sources_count=summary.sources_count,
            duration_minutes=summary.duration_minutes,
            concepts_explored=summary.concepts_explored,
            full_text=summary.full_text
        )

    except Exception as e:
        logger.error(f"[SUMMARY] Generation failed for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la génération du résumé: {str(e)}"
        )
