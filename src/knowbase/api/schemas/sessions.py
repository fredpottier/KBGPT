"""
Schemas Pydantic pour l'API Sessions.

Phase 2.5 - Memory Layer
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


# ============================================================================
# Session Schemas
# ============================================================================


class SessionCreate(BaseModel):
    """Création d'une nouvelle session."""
    title: Optional[str] = Field(None, description="Titre de la session (auto-généré si omis)")


class SessionUpdate(BaseModel):
    """Mise à jour d'une session."""
    title: Optional[str] = Field(None, description="Nouveau titre")
    is_active: Optional[bool] = Field(None, description="Archiver/désarchiver")


class SessionResponse(BaseModel):
    """Réponse avec détails d'une session."""
    id: str = Field(..., description="UUID de la session")
    user_id: str = Field(..., description="ID de l'utilisateur propriétaire")
    title: Optional[str] = Field(None, description="Titre de la session")
    summary: Optional[str] = Field(None, description="Résumé auto-généré de la conversation")
    is_active: bool = Field(True, description="Session active ou archivée")
    message_count: int = Field(0, description="Nombre de messages")
    token_count: int = Field(0, description="Tokens consommés")
    created_at: datetime = Field(..., description="Date de création")
    updated_at: datetime = Field(..., description="Dernière mise à jour")
    last_message_at: Optional[datetime] = Field(None, description="Date du dernier message")

    class Config:
        from_attributes = True


class SessionListResponse(BaseModel):
    """Liste de sessions."""
    sessions: List[SessionResponse]
    total: int = Field(..., description="Nombre total de sessions")


# ============================================================================
# Message Schemas
# ============================================================================


class MessageCreate(BaseModel):
    """Création d'un nouveau message."""
    role: str = Field(..., description="Rôle: user | assistant | system")
    content: str = Field(..., description="Contenu du message")
    entities_mentioned: Optional[List[str]] = Field(None, description="Entités mentionnées")
    documents_referenced: Optional[List[str]] = Field(None, description="Documents sources")
    model_used: Optional[str] = Field(None, description="Modèle LLM utilisé")
    tokens_input: Optional[int] = Field(None, description="Tokens input")
    tokens_output: Optional[int] = Field(None, description="Tokens output")
    latency_ms: Optional[int] = Field(None, description="Latence en ms")


class MessageResponse(BaseModel):
    """Réponse avec détails d'un message."""
    id: str = Field(..., description="UUID du message")
    session_id: str = Field(..., description="UUID de la session parente")
    role: str = Field(..., description="Rôle: user | assistant | system")
    content: str = Field(..., description="Contenu du message")
    entities_mentioned: Optional[List[str]] = Field(None, description="Entités mentionnées")
    documents_referenced: Optional[List[str]] = Field(None, description="Documents sources")
    model_used: Optional[str] = Field(None, description="Modèle LLM utilisé")
    tokens_input: Optional[int] = Field(None, description="Tokens input")
    tokens_output: Optional[int] = Field(None, description="Tokens output")
    latency_ms: Optional[int] = Field(None, description="Latence en ms")
    feedback_rating: Optional[int] = Field(None, description="Rating: 1 (down) | 2 (up)")
    feedback_comment: Optional[str] = Field(None, description="Commentaire feedback")
    created_at: datetime = Field(..., description="Date de création")

    class Config:
        from_attributes = True


class MessageListResponse(BaseModel):
    """Liste de messages."""
    messages: List[MessageResponse]
    total: int = Field(..., description="Nombre total de messages")
    session_id: str = Field(..., description="UUID de la session")


# ============================================================================
# Context Schemas
# ============================================================================


class ConversationContext(BaseModel):
    """Contexte de conversation pour le LLM."""
    session_id: str = Field(..., description="UUID de la session")
    title: Optional[str] = Field(None, description="Titre de la session")
    message_count: int = Field(0, description="Nombre total de messages")
    summary: Optional[str] = Field(None, description="Résumé de la conversation")
    messages: List[Dict[str, Any]] = Field(default_factory=list, description="Messages récents")
    context_metadata: Optional[Dict[str, Any]] = Field(None, description="Métadonnées de contexte")


class ContextUpdate(BaseModel):
    """Mise à jour du contexte conversationnel."""
    entities: Optional[List[Dict[str, Any]]] = Field(None, description="Entités à ajouter au contexte")
    documents: Optional[List[Dict[str, Any]]] = Field(None, description="Documents à ajouter")
    search_results: Optional[List[Dict[str, Any]]] = Field(None, description="Résultats de recherche")
    topics: Optional[List[str]] = Field(None, description="Sujets actifs")


# ============================================================================
# Feedback Schemas
# ============================================================================


class FeedbackCreate(BaseModel):
    """Ajout de feedback sur un message."""
    rating: int = Field(..., ge=1, le=2, description="Rating: 1 (thumbs down) | 2 (thumbs up)")
    comment: Optional[str] = Field(None, description="Commentaire optionnel")


class FeedbackResponse(BaseModel):
    """Réponse après ajout de feedback."""
    message_id: str
    rating: int
    comment: Optional[str]
    success: bool


# ============================================================================
# Reference Resolution Schemas
# ============================================================================


class ResolveRequest(BaseModel):
    """Demande de résolution de références."""
    query: str = Field(..., description="Query à résoudre")
    session_id: str = Field(..., description="Session pour le contexte")


class ResolvedReferenceSchema(BaseModel):
    """Référence résolue."""
    original_text: str = Field(..., description="Texte original")
    resolved_text: str = Field(..., description="Texte résolu")
    reference_type: str = Field(..., description="Type: entity | document | topic | unknown")
    confidence: float = Field(..., description="Score de confiance 0.0-1.0")
    source: str = Field(..., description="Source de la résolution")


class ResolveResponse(BaseModel):
    """Réponse de résolution de références."""
    original_query: str = Field(..., description="Query originale")
    resolved_query: str = Field(..., description="Query avec références résolues")
    references: List[ResolvedReferenceSchema] = Field(default_factory=list, description="Références résolues")
    has_changes: bool = Field(..., description="True si des résolutions ont été effectuées")


# ============================================================================
# Summary Schemas
# ============================================================================


class SummaryRequest(BaseModel):
    """Demande de génération de résumé."""
    format: str = Field(
        "business",
        description="Format du résumé: business | technical | executive"
    )


class KeyPointSchema(BaseModel):
    """Point clé avec source optionnelle."""
    point: str = Field(..., description="Contenu du point clé")
    source: Optional[str] = Field(None, description="Source documentaire")


class SummaryResponse(BaseModel):
    """Résumé structuré d'une session."""
    session_id: str = Field(..., description="UUID de la session")
    title: str = Field(..., description="Titre de la session")
    generated_at: datetime = Field(..., description="Date de génération")
    format: str = Field(..., description="Format utilisé")

    # Sections du résumé
    context: str = Field(..., description="Contexte/objectif de recherche identifié")
    key_points: List[KeyPointSchema] = Field(
        default_factory=list,
        description="Points clés avec sources"
    )
    actions: List[str] = Field(
        default_factory=list,
        description="Actions recommandées ou identifiées"
    )
    unexplored_areas: List[str] = Field(
        default_factory=list,
        description="Zones non explorées suggérées"
    )

    # Métadonnées
    question_count: int = Field(..., description="Nombre de questions posées")
    sources_count: int = Field(..., description="Nombre de sources utilisées")
    duration_minutes: Optional[int] = Field(None, description="Durée de la session en minutes")
    concepts_explored: List[str] = Field(
        default_factory=list,
        description="Topics/concepts explorés"
    )

    # Texte complet
    full_text: str = Field("", description="Résumé texte complet au format markdown")
