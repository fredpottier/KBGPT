"""
🧠 OSMOSE Phase 2.5 - Intelligent Summarizer

Génère des comptes-rendus métier structurés à partir de sessions de conversation.
Pas une simple transcription, mais une synthèse exploitable pour décideurs.

Features:
- Extraction automatique des topics principaux
- Identification des points clés avec sources
- Détection des actions mentionnées
- Génération via LLM avec format configurable
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from knowbase.common.llm_router import TaskType, get_llm_router
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings
from knowbase.db.models import Session, SessionMessage

settings = get_settings()
logger = setup_logging(settings.logs_dir, "intelligent_summarizer.log")


class SummaryFormat(str, Enum):
    """Format de sortie du résumé."""
    BUSINESS = "business"      # Orienté décideur, points clés et actions
    TECHNICAL = "technical"    # Détails techniques, références précises
    EXECUTIVE = "executive"    # Ultra-concis, 3-5 bullet points


@dataclass
class ExtractedData:
    """Données extraites de la session avant génération du résumé."""
    topics: List[str] = field(default_factory=list)
    key_concepts: List[str] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    actions_mentioned: List[str] = field(default_factory=list)
    questions_asked: List[str] = field(default_factory=list)
    documents_referenced: List[str] = field(default_factory=list)
    question_count: int = 0
    answer_count: int = 0


@dataclass
class SessionSummary:
    """Résumé structuré d'une session."""
    session_id: str
    title: str
    generated_at: datetime
    format: SummaryFormat

    # Sections du résumé
    context: str                          # Objectif/contexte de recherche identifié
    key_points: List[Dict[str, Any]]      # Points clés avec sources
    actions: List[str]                    # Actions identifiées
    unexplored_areas: List[str]           # Zones non explorées suggérées

    # Métadonnées
    question_count: int
    sources_count: int
    duration_minutes: Optional[int] = None
    concepts_explored: List[str] = field(default_factory=list)

    # Résumé texte complet
    full_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "generated_at": self.generated_at.isoformat(),
            "format": self.format.value,
            "context": self.context,
            "key_points": self.key_points,
            "actions": self.actions,
            "unexplored_areas": self.unexplored_areas,
            "question_count": self.question_count,
            "sources_count": self.sources_count,
            "duration_minutes": self.duration_minutes,
            "concepts_explored": self.concepts_explored,
            "full_text": self.full_text
        }


# Prompts par format
SUMMARY_PROMPTS = {
    SummaryFormat.BUSINESS: """Tu es un assistant qui génère des synthèses professionnelles de sessions de recherche documentaire.

CONTEXTE DE LA SESSION:
- Titre: {title}
- Date: {session_date}
- Nombre de questions: {question_count}
- Documents consultés: {sources_count}

CONVERSATION:
{conversation_transcript}

CONSIGNES:
1. Génère une synthèse MÉTIER, pas une transcription
2. Structure en sections claires avec des titres markdown ##:

   ## Contexte
   Objectif de recherche identifié en 1-2 phrases.

   ## Points Clés
   - 3-5 insights principaux, chacun avec sa source entre parenthèses

   ## Actions Recommandées
   - Actions concrètes identifiées ou suggérées (si pertinent)

   ## Zones à Explorer
   - Sujets pertinents non abordés qui mériteraient investigation

3. Cite les sources entre parenthèses (Source: nom_document)
4. Utilise un ton professionnel et factuel
5. Maximum 400 mots

Génère la synthèse:""",

    SummaryFormat.TECHNICAL: """Tu es un assistant technique qui génère des rapports détaillés de sessions de recherche.

CONTEXTE:
- Session: {title}
- Date: {session_date}
- Questions: {question_count}
- Sources: {sources_count}

CONVERSATION:
{conversation_transcript}

CONSIGNES:
1. Génère un rapport TECHNIQUE détaillé
2. Structure:

   ## Périmètre de Recherche
   Contexte technique et objectifs.

   ## Résultats Détaillés
   Pour chaque question posée, résume la réponse avec références exactes.

   ## Sources Utilisées
   Liste exhaustive des documents cités.

   ## Points d'Attention Techniques
   Problèmes ou limitations identifiés.

   ## Recommandations
   Prochaines étapes techniques suggérées.

3. Sois précis sur les références (document, slide/page si disponible)
4. Maximum 600 mots

Génère le rapport:""",

    SummaryFormat.EXECUTIVE: """Tu es un assistant qui génère des synthèses exécutives ultra-concises.

SESSION: {title}
DATE: {session_date}
QUESTIONS: {question_count}

CONVERSATION:
{conversation_transcript}

CONSIGNES:
1. Génère une synthèse EXECUTIVE en 5 bullet points maximum
2. Format:

   ## Synthèse
   • Point 1 (une phrase)
   • Point 2 (une phrase)
   • Point 3 (une phrase)

   ## Action Prioritaire
   Une seule action clé si identifiée.

3. Chaque point = 1 phrase impactante
4. Maximum 150 mots

Génère la synthèse:"""
}


class IntelligentSummarizer:
    """Génère des résumés intelligents de sessions de conversation."""

    def __init__(self):
        self.router = get_llm_router()

        # Patterns pour extraction
        self._action_patterns = [
            r"il (faut|faudrait|faudra)\s+(.+?)(?:\.|$)",
            r"on (doit|devra|devrait)\s+(.+?)(?:\.|$)",
            r"à faire\s*:\s*(.+?)(?:\.|$)",
            r"action[s]?\s*:\s*(.+?)(?:\.|$)",
            r"recommand[ée]?[s]?\s*:\s*(.+?)(?:\.|$)",
            r"prévoir de\s+(.+?)(?:\.|$)",
            r"pensez à\s+(.+?)(?:\.|$)",
            r"n'oubliez pas de\s+(.+?)(?:\.|$)",
        ]

        logger.info("[IntelligentSummarizer] Initialized")

    def generate_summary(
        self,
        session: Session,
        messages: List[SessionMessage],
        format: SummaryFormat = SummaryFormat.BUSINESS
    ) -> SessionSummary:
        """
        Génère un résumé intelligent d'une session.

        Args:
            session: Session à résumer
            messages: Messages de la session
            format: Format de sortie souhaité

        Returns:
            SessionSummary structuré
        """
        logger.info(
            f"[SUMMARIZER] Generating {format.value} summary for session {session.id}"
        )

        # 1. Extraire les données structurées
        extracted = self._extract_session_data(session, messages)

        # 2. Construire le transcript formaté
        transcript = self._format_conversation_transcript(messages)

        # 3. Calculer la durée si possible
        duration = None
        if messages:
            first_msg = messages[0]
            last_msg = messages[-1]
            if first_msg.created_at and last_msg.created_at:
                delta = last_msg.created_at - first_msg.created_at
                duration = int(delta.total_seconds() / 60)

        # 4. Générer via LLM
        summary_text = self._generate_with_llm(
            session=session,
            extracted=extracted,
            transcript=transcript,
            format=format
        )

        # 5. Parser et structurer
        summary = self._parse_summary(
            session_id=str(session.id),
            title=session.title or "Session sans titre",
            raw_text=summary_text,
            extracted=extracted,
            format=format,
            duration=duration
        )

        logger.info(
            f"[SUMMARIZER] Generated summary: {len(summary.key_points)} key points, "
            f"{len(summary.actions)} actions"
        )

        return summary

    def _extract_session_data(
        self,
        session: Session,
        messages: List[SessionMessage]
    ) -> ExtractedData:
        """Extrait les données structurées de la session."""

        extracted = ExtractedData()

        sources = set()
        questions = []

        for msg in messages:
            if msg.role == "user":
                questions.append(msg.content)
                extracted.question_count += 1
            else:
                extracted.answer_count += 1

                # Extraire les sources mentionnées
                if msg.documents_referenced:
                    for doc in msg.documents_referenced:
                        if doc:
                            sources.add(doc)

                # Extraire les actions via patterns
                for pattern in self._action_patterns:
                    matches = re.findall(pattern, msg.content, re.IGNORECASE)
                    for match in matches:
                        if isinstance(match, tuple):
                            action_text = match[-1].strip()
                        else:
                            action_text = match.strip()
                        if len(action_text) > 10:  # Filtrer les trop courts
                            extracted.actions_mentioned.append(action_text)

        extracted.questions_asked = questions
        extracted.sources_used = list(sources)

        # Extraire topics via analyse simple des questions
        extracted.topics = self._identify_topics(questions)

        return extracted

    def _identify_topics(self, questions: List[str]) -> List[str]:
        """Identifie les topics principaux des questions."""
        topics = set()

        # Mots-clés indicateurs de topics
        topic_keywords = {
            "migration": ["migration", "migrer", "upgrade", "mise à jour"],
            "sécurité": ["sécurité", "security", "authentification", "autorisation", "rbac"],
            "performance": ["performance", "optimisation", "lent", "rapide"],
            "intégration": ["intégration", "api", "connecteur", "interface"],
            "formation": ["formation", "apprendre", "documentation", "guide"],
            "coût": ["coût", "prix", "licence", "budget", "roi"],
            "architecture": ["architecture", "infrastructure", "déploiement"],
            "données": ["données", "data", "base de données", "stockage"],
        }

        all_text = " ".join(questions).lower()

        for topic, keywords in topic_keywords.items():
            if any(kw in all_text for kw in keywords):
                topics.add(topic)

        return list(topics)[:5]  # Max 5 topics

    def _format_conversation_transcript(
        self,
        messages: List[SessionMessage]
    ) -> str:
        """Formate la conversation pour le prompt LLM."""
        lines = []

        for msg in messages:
            role_label = "UTILISATEUR" if msg.role == "user" else "ASSISTANT"

            # Tronquer les messages très longs
            content = msg.content
            if len(content) > 800:
                content = content[:800] + "... [tronqué]"

            lines.append(f"**{role_label}:** {content}")

        return "\n\n".join(lines)

    def _generate_with_llm(
        self,
        session: Session,
        extracted: ExtractedData,
        transcript: str,
        format: SummaryFormat
    ) -> str:
        """Génère le résumé via LLM."""

        prompt_template = SUMMARY_PROMPTS.get(format, SUMMARY_PROMPTS[SummaryFormat.BUSINESS])

        # Formater la date
        session_date = "Non spécifiée"
        if session.created_at:
            session_date = session.created_at.strftime("%d/%m/%Y à %H:%M")

        prompt = prompt_template.format(
            title=session.title or "Session de recherche",
            session_date=session_date,
            question_count=extracted.question_count,
            sources_count=len(extracted.sources_used),
            conversation_transcript=transcript
        )

        messages = [
            {
                "role": "system",
                "content": "Tu es un assistant expert en synthèse documentaire. "
                          "Tu génères des résumés clairs, structurés et exploitables."
            },
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.router.complete(
                task_type=TaskType.LONG_TEXT_SUMMARY,
                messages=messages,
                temperature=0.3,
                max_tokens=1500
            )
            return response.strip()

        except Exception as e:
            logger.error(f"[SUMMARIZER] LLM generation failed: {e}")
            return self._generate_fallback_summary(extracted)

    def _generate_fallback_summary(self, extracted: ExtractedData) -> str:
        """Génère un résumé de secours sans LLM."""
        lines = ["## Contexte", "Session de recherche documentaire.", ""]

        lines.append("## Points Clés")
        if extracted.questions_asked:
            for i, q in enumerate(extracted.questions_asked[:5], 1):
                lines.append(f"- Question {i}: {q[:100]}...")
        else:
            lines.append("- Aucune question identifiée")
        lines.append("")

        if extracted.sources_used:
            lines.append("## Sources Consultées")
            for src in extracted.sources_used[:5]:
                lines.append(f"- {src}")

        return "\n".join(lines)

    def _parse_summary(
        self,
        session_id: str,
        title: str,
        raw_text: str,
        extracted: ExtractedData,
        format: SummaryFormat,
        duration: Optional[int]
    ) -> SessionSummary:
        """Parse le texte LLM en structure SessionSummary."""

        # Extraire les sections du markdown
        context = self._extract_section(raw_text, ["Contexte", "Périmètre", "Context"])
        key_points_text = self._extract_section(
            raw_text,
            ["Points Clés", "Points clés", "Résultats", "Key Points", "Synthèse"]
        )
        actions_text = self._extract_section(
            raw_text,
            ["Actions", "Recommandations", "Action Prioritaire", "Prochaines étapes"]
        )
        unexplored_text = self._extract_section(
            raw_text,
            ["Zones à Explorer", "Non explorées", "Points d'Attention", "À investiguer"]
        )

        # Parser les bullet points
        key_points = self._parse_bullet_points(key_points_text)
        actions = self._parse_bullet_list(actions_text)
        unexplored = self._parse_bullet_list(unexplored_text)

        # Combiner avec les actions extraites automatiquement
        all_actions = list(set(actions + extracted.actions_mentioned[:3]))

        return SessionSummary(
            session_id=session_id,
            title=title,
            generated_at=datetime.utcnow(),
            format=format,
            context=context or "Session de recherche documentaire.",
            key_points=key_points,
            actions=all_actions[:5],  # Max 5 actions
            unexplored_areas=unexplored[:3],  # Max 3 zones
            question_count=extracted.question_count,
            sources_count=len(extracted.sources_used),
            duration_minutes=duration,
            concepts_explored=extracted.topics,
            full_text=raw_text
        )

    def _extract_section(self, text: str, headers: List[str]) -> str:
        """Extrait le contenu d'une section markdown."""
        for header in headers:
            # Pattern pour trouver la section
            pattern = rf"##\s*{re.escape(header)}[^\n]*\n(.*?)(?=##|\Z)"
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
        return ""

    def _parse_bullet_points(self, text: str) -> List[Dict[str, Any]]:
        """Parse des bullet points en liste structurée avec sources."""
        points = []

        # Pattern pour bullet points (-, *, •)
        lines = re.findall(r"[-*•]\s*(.+?)(?:\n|$)", text)

        for line in lines:
            line = line.strip()
            if len(line) < 10:
                continue

            # Extraire la source si présente
            source = None
            source_match = re.search(r"\((?:Source\s*:\s*)?([^)]+)\)$", line)
            if source_match:
                source = source_match.group(1).strip()
                line = line[:source_match.start()].strip()

            points.append({
                "point": line,
                "source": source
            })

        return points[:5]  # Max 5 points

    def _parse_bullet_list(self, text: str) -> List[str]:
        """Parse une liste simple de bullet points."""
        items = []

        lines = re.findall(r"[-*•]\s*(.+?)(?:\n|$)", text)

        for line in lines:
            line = line.strip()
            if len(line) > 10:
                items.append(line)

        return items


# Singleton instance
_summarizer: Optional[IntelligentSummarizer] = None


def get_intelligent_summarizer() -> IntelligentSummarizer:
    """Retourne l'instance du summarizer (créée si nécessaire)."""
    global _summarizer
    if _summarizer is None:
        _summarizer = IntelligentSummarizer()
    return _summarizer


__all__ = [
    "IntelligentSummarizer",
    "get_intelligent_summarizer",
    "SessionSummary",
    "SummaryFormat",
    "ExtractedData"
]
