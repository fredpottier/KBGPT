"""
Service Intelligence Automatisée - Phase 3
Fonctionnalités IA pour amélioration de la gouvernance des facts
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from knowbase.api.schemas.facts_governance import (
    FactCreate, FactResponse, ConflictDetail, ConflictType
)
from knowbase.common.llm_router import LLMRouter, TaskType

logger = logging.getLogger(__name__)


class FactsIntelligenceService:
    """Service Intelligence pour gouvernance automatisée des facts"""

    def __init__(self):
        self.llm_router = LLMRouter()
        self._confidence_cache: Dict[str, float] = {}

    async def calculate_confidence_score(
        self,
        fact: FactCreate,
        context_facts: Optional[List[FactResponse]] = None
    ) -> Dict[str, Any]:
        """
        Calcule un score de confidence automatique via LLM

        Args:
            fact: Fait à évaluer
            context_facts: Facts existants similaires pour contexte

        Returns:
            {
                "confidence": float (0-1),
                "reasoning": str,
                "factors": Dict[str, float],
                "recommendations": List[str]
            }
        """
        try:
            # Construire le prompt pour l'analyse LLM
            fact_key = f"{fact.subject}_{fact.predicate}_{fact.object}"

            # Vérifier cache
            if fact_key in self._confidence_cache:
                return {
                    "confidence": self._confidence_cache[fact_key],
                    "reasoning": "Score récupéré du cache",
                    "factors": {},
                    "recommendations": []
                }

            prompt = self._build_confidence_prompt(fact, context_facts)

            # Appel LLM via router (méthode synchrone, on l'exécute dans un thread)
            import asyncio
            from functools import partial

            messages = [
                {"role": "system", "content": "Tu es un expert en évaluation de la fiabilité des faits. Réponds toujours en JSON."},
                {"role": "user", "content": prompt}
            ]

            # Utiliser TaskType.SHORT_ENRICHMENT pour ce type d'analyse
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                partial(
                    self.llm_router.complete,
                    task_type=TaskType.SHORT_ENRICHMENT,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=500
                )
            )

            # Parser la réponse pour extraire le score
            analysis = self._parse_confidence_response(response)

            # Mettre en cache
            self._confidence_cache[fact_key] = analysis["confidence"]

            return analysis

        except Exception as e:
            logger.error(f"Erreur calcul confidence LLM: {e}")
            # Fallback: retourner confidence par défaut
            return {
                "confidence": fact.confidence if hasattr(fact, 'confidence') else 0.5,
                "reasoning": f"Erreur LLM, score par défaut: {str(e)}",
                "factors": {},
                "recommendations": ["Révision manuelle recommandée"]
            }

    def _build_confidence_prompt(
        self,
        fact: FactCreate,
        context_facts: Optional[List[FactResponse]]
    ) -> str:
        """Construit le prompt pour l'évaluation de confidence"""
        prompt = f"""Analyse la fiabilité et la confiance que l'on peut avoir dans ce fait:

Fait à évaluer:
- Sujet: {fact.subject}
- Prédicat: {fact.predicate}
- Objet: {fact.object}
- Source: {fact.source if fact.source else 'Non spécifiée'}

"""

        if context_facts and len(context_facts) > 0:
            prompt += "\nFacts existants similaires:\n"
            for cf in context_facts[:5]:  # Limiter à 5 facts de contexte
                prompt += f"- {cf.subject} {cf.predicate} {cf.object} (confiance: {cf.confidence:.2f})\n"

        prompt += """
Évalue le score de confiance (0.0 à 1.0) en considérant:
1. La clarté et précision du fait
2. La cohérence avec les facts existants
3. La source (si fournie)
4. La spécificité vs généralité

Réponds au format JSON:
{
    "confidence": <score 0.0-1.0>,
    "reasoning": "<explication courte>",
    "factors": {
        "clarity": <score>,
        "consistency": <score>,
        "source_reliability": <score>,
        "specificity": <score>
    },
    "recommendations": ["<recommandation 1>", "<recommandation 2>"]
}
"""
        return prompt

    def _parse_confidence_response(self, llm_response: str) -> Dict[str, Any]:
        """Parse la réponse LLM pour extraire l'analyse de confidence"""
        try:
            import json

            # Chercher JSON dans la réponse
            start_idx = llm_response.find('{')
            end_idx = llm_response.rfind('}') + 1

            if start_idx >= 0 and end_idx > start_idx:
                json_str = llm_response[start_idx:end_idx]
                analysis = json.loads(json_str)

                # Valider le score
                confidence = float(analysis.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))

                return {
                    "confidence": confidence,
                    "reasoning": analysis.get("reasoning", ""),
                    "factors": analysis.get("factors", {}),
                    "recommendations": analysis.get("recommendations", [])
                }
            else:
                raise ValueError("Pas de JSON trouvé dans la réponse")

        except Exception as e:
            logger.warning(f"Erreur parsing réponse LLM: {e}")
            return {
                "confidence": 0.5,
                "reasoning": "Erreur de parsing, score par défaut",
                "factors": {},
                "recommendations": []
            }

    async def suggest_conflict_resolutions(
        self,
        conflict: ConflictDetail
    ) -> List[str]:
        """
        Génère des suggestions IA pour résoudre un conflit

        Args:
            conflict: Détails du conflit à résoudre

        Returns:
            Liste de suggestions de résolution
        """
        try:
            prompt = self._build_conflict_resolution_prompt(conflict)

            # Appel LLM via router
            import asyncio
            from functools import partial

            messages = [
                {"role": "system", "content": "Tu es un expert en résolution de conflits dans les bases de connaissances. Fournis des suggestions concrètes et actionnables."},
                {"role": "user", "content": prompt}
            ]

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                partial(
                    self.llm_router.complete,
                    task_type=TaskType.SHORT_ENRICHMENT,
                    messages=messages,
                    temperature=0.4,
                    max_tokens=800
                )
            )

            suggestions = self._parse_resolution_suggestions(response)
            return suggestions

        except Exception as e:
            logger.error(f"Erreur génération suggestions: {e}")
            return [
                "Vérifier les sources des facts en conflit",
                "Consulter un expert métier",
                "Analyser la temporalité des faits"
            ]

    def _build_conflict_resolution_prompt(self, conflict: ConflictDetail) -> str:
        """Construit le prompt pour suggestions de résolution"""
        prompt = f"""Analyse ce conflit entre plusieurs facts et propose des résolutions:

Type de conflit: {conflict.type}
Sévérité: {conflict.severity}
Description: {conflict.description}

Facts en conflit:
"""
        for i, fact in enumerate(conflict.conflicting_facts, 1):
            prompt += f"\n{i}. {fact['subject']} {fact['predicate']} {fact['object']}"
            prompt += f"\n   - Créé par: {fact['created_by']}"
            prompt += f"\n   - Confiance: {fact['confidence']:.2f}"
            if 'source' in fact and fact['source']:
                prompt += f"\n   - Source: {fact['source']}"

        prompt += """

Propose 3 à 5 suggestions concrètes pour résoudre ce conflit.
Chaque suggestion doit être:
- Actionnable
- Spécifique au conflit
- Basée sur des critères objectifs

Format de réponse: liste de suggestions séparées par des retours à la ligne, chacune commençant par "-"
"""
        return prompt

    def _parse_resolution_suggestions(self, llm_response: str) -> List[str]:
        """Parse les suggestions de résolution depuis la réponse LLM"""
        suggestions = []

        lines = llm_response.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('-') or line.startswith('•') or line.startswith('*'):
                suggestion = line[1:].strip()
                if suggestion and len(suggestion) > 10:  # Filtrer suggestions trop courtes
                    suggestions.append(suggestion)

        # Si pas de suggestions trouvées, essayer de splitter par numéros
        if not suggestions:
            for line in lines:
                line = line.strip()
                if len(line) > 2 and line[0].isdigit() and line[1] in ['.', ')']:
                    suggestion = line[2:].strip()
                    if suggestion and len(suggestion) > 10:
                        suggestions.append(suggestion)

        return suggestions[:5]  # Limiter à 5 suggestions max

    async def detect_patterns_and_anomalies(
        self,
        facts: List[FactResponse],
        detection_type: str = "all"
    ) -> Dict[str, Any]:
        """
        Détecte des patterns et anomalies dans les facts

        Args:
            facts: Liste de facts à analyser
            detection_type: "all", "patterns", ou "anomalies"

        Returns:
            {
                "patterns": List[Dict],
                "anomalies": List[Dict],
                "insights": List[str]
            }
        """
        result = {
            "patterns": [],
            "anomalies": [],
            "insights": []
        }

        if len(facts) < 5:
            result["insights"].append("Pas assez de données pour détecter des patterns significatifs")
            return result

        # Détecter patterns temporels
        if detection_type in ["all", "patterns"]:
            temporal_patterns = self._detect_temporal_patterns(facts)
            result["patterns"].extend(temporal_patterns)

        # Détecter anomalies de confidence
        if detection_type in ["all", "anomalies"]:
            confidence_anomalies = self._detect_confidence_anomalies(facts)
            result["anomalies"].extend(confidence_anomalies)

        # Détecter patterns de sujets/prédicats fréquents
        if detection_type in ["all", "patterns"]:
            entity_patterns = self._detect_entity_patterns(facts)
            result["patterns"].extend(entity_patterns)

        # Générer insights
        result["insights"] = self._generate_insights(result["patterns"], result["anomalies"])

        return result

    def _detect_temporal_patterns(self, facts: List[FactResponse]) -> List[Dict[str, Any]]:
        """Détecte des patterns temporels dans les créations de facts"""
        patterns = []

        # Analyser la distribution temporelle
        fact_dates = [datetime.fromisoformat(f.created_at.replace('Z', '+00:00')) for f in facts]
        fact_dates.sort()

        # Détecter pics d'activité
        if len(fact_dates) > 10:
            # Grouper par jour
            daily_counts: Dict[str, int] = {}
            for dt in fact_dates:
                day_key = dt.date().isoformat()
                daily_counts[day_key] = daily_counts.get(day_key, 0) + 1

            # Trouver les jours avec activité > moyenne + écart-type
            avg_daily = sum(daily_counts.values()) / len(daily_counts)

            high_activity_days = [
                (day, count) for day, count in daily_counts.items()
                if count > avg_daily * 1.5
            ]

            if high_activity_days:
                patterns.append({
                    "type": "temporal_spike",
                    "description": f"Pics d'activité détectés sur {len(high_activity_days)} jour(s)",
                    "details": high_activity_days[:5],  # Top 5
                    "severity": "info"
                })

        return patterns

    def _detect_confidence_anomalies(self, facts: List[FactResponse]) -> List[Dict[str, Any]]:
        """Détecte des anomalies dans les scores de confidence"""
        anomalies = []

        confidences = [f.confidence for f in facts]
        avg_confidence = sum(confidences) / len(confidences)

        # Facts avec confidence très faible (<0.3)
        low_confidence_facts = [f for f in facts if f.confidence < 0.3]
        if low_confidence_facts:
            anomalies.append({
                "type": "low_confidence",
                "description": f"{len(low_confidence_facts)} fact(s) avec confiance très faible (<30%)",
                "facts": [f.uuid for f in low_confidence_facts[:10]],
                "severity": "medium"
            })

        # Facts avec confidence anormalement haute par rapport à la moyenne
        high_outliers = [f for f in facts if f.confidence > avg_confidence + 0.25 and f.confidence > 0.95]
        if high_outliers and len(high_outliers) < len(facts) * 0.1:
            anomalies.append({
                "type": "high_confidence_outliers",
                "description": f"{len(high_outliers)} fact(s) avec confiance inhabituellement haute",
                "facts": [f.uuid for f in high_outliers[:10]],
                "severity": "info"
            })

        return anomalies

    def _detect_entity_patterns(self, facts: List[FactResponse]) -> List[Dict[str, Any]]:
        """Détecte des patterns dans les entités et relations"""
        patterns = []

        # Compter les sujets les plus fréquents
        subject_counts: Dict[str, int] = {}
        predicate_counts: Dict[str, int] = {}

        for fact in facts:
            subject_counts[fact.subject] = subject_counts.get(fact.subject, 0) + 1
            predicate_counts[fact.predicate] = predicate_counts.get(fact.predicate, 0) + 1

        # Top sujets
        top_subjects = sorted(subject_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_subjects and top_subjects[0][1] > len(facts) * 0.1:
            patterns.append({
                "type": "frequent_subjects",
                "description": f"Sujets les plus fréquents: {', '.join([s[0] for s in top_subjects])}",
                "details": dict(top_subjects),
                "severity": "info"
            })

        # Top prédicats
        top_predicates = sorted(predicate_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_predicates:
            patterns.append({
                "type": "frequent_predicates",
                "description": f"Relations les plus utilisées: {', '.join([p[0] for p in top_predicates])}",
                "details": dict(top_predicates),
                "severity": "info"
            })

        return patterns

    def _generate_insights(
        self,
        patterns: List[Dict[str, Any]],
        anomalies: List[Dict[str, Any]]
    ) -> List[str]:
        """Génère des insights actionnables depuis patterns et anomalies"""
        insights = []

        # Insights depuis patterns
        for pattern in patterns:
            if pattern["type"] == "temporal_spike":
                insights.append("Activité de création concentrée sur certains jours - vérifier campagnes d'import")
            elif pattern["type"] == "frequent_subjects":
                insights.append("Certaines entités dominent le graphe - envisager segmentation ou raffinement")

        # Insights depuis anomalies
        for anomaly in anomalies:
            if anomaly["type"] == "low_confidence":
                insights.append("Nombreux facts à faible confiance - révision par experts recommandée")
            elif anomaly["type"] == "high_confidence_outliers":
                insights.append("Quelques facts à confiance maximale - vérifier sources et validité")

        # Insight général
        if len(patterns) > 5 or len(anomalies) > 3:
            insights.append("Activité importante détectée - surveillance rapprochée recommandée")

        return insights[:10]  # Limiter à 10 insights max

    async def calculate_governance_metrics(
        self,
        facts: List[FactResponse],
        time_window_days: int = 30
    ) -> Dict[str, Any]:
        """
        Calcule des métriques avancées de gouvernance

        Returns:
            {
                "coverage": float,
                "velocity": float,
                "quality_score": float,
                "approval_rate": float,
                "avg_time_to_approval": float (hours),
                "top_contributors": List[Dict],
                "trend": str ("improving", "stable", "declining")
            }
        """
        if not facts:
            return {
                "coverage": 0.0,
                "velocity": 0.0,
                "quality_score": 0.0,
                "approval_rate": 0.0,
                "avg_time_to_approval": 0.0,
                "top_contributors": [],
                "trend": "stable"
            }

        # Coverage: proportion de facts approuvés
        approved_facts = [f for f in facts if f.status == "approved"]
        coverage = len(approved_facts) / len(facts) if facts else 0.0

        # Velocity: facts créés par jour (fenêtre récente)
        cutoff_date = datetime.utcnow() - timedelta(days=time_window_days)
        recent_facts = [
            f for f in facts
            if datetime.fromisoformat(f.created_at.replace('Z', '+00:00')) > cutoff_date
        ]
        velocity = len(recent_facts) / time_window_days if time_window_days > 0 else 0.0

        # Quality score: moyenne des confidences des facts approuvés
        approved_confidences = [f.confidence for f in approved_facts]
        quality_score = sum(approved_confidences) / len(approved_confidences) if approved_confidences else 0.0

        # Approval rate
        total_processed = len([f for f in facts if f.status in ["approved", "rejected"]])
        approval_rate = len(approved_facts) / total_processed if total_processed > 0 else 0.0

        # Temps moyen d'approbation
        approval_times = []
        for fact in approved_facts:
            if fact.approved_at and fact.created_at:
                created = datetime.fromisoformat(fact.created_at.replace('Z', '+00:00'))
                approved = datetime.fromisoformat(fact.approved_at.replace('Z', '+00:00'))
                hours_diff = (approved - created).total_seconds() / 3600
                approval_times.append(hours_diff)

        avg_time_to_approval = sum(approval_times) / len(approval_times) if approval_times else 0.0

        # Top contributeurs
        contributor_counts: Dict[str, int] = {}
        for fact in facts:
            if fact.created_by:
                contributor_counts[fact.created_by] = contributor_counts.get(fact.created_by, 0) + 1

        top_contributors = [
            {"user_id": user, "facts_count": count}
            for user, count in sorted(contributor_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        # Trend: comparer première et deuxième moitié de la période
        mid_date = datetime.utcnow() - timedelta(days=time_window_days // 2)
        first_half = [f for f in recent_facts if datetime.fromisoformat(f.created_at.replace('Z', '+00:00')) < mid_date]
        second_half = [f for f in recent_facts if datetime.fromisoformat(f.created_at.replace('Z', '+00:00')) >= mid_date]

        trend = "stable"
        if len(second_half) > len(first_half) * 1.2:
            trend = "improving"
        elif len(second_half) < len(first_half) * 0.8:
            trend = "declining"

        return {
            "coverage": round(coverage, 3),
            "velocity": round(velocity, 2),
            "quality_score": round(quality_score, 3),
            "approval_rate": round(approval_rate, 3),
            "avg_time_to_approval": round(avg_time_to_approval, 2),
            "top_contributors": top_contributors,
            "trend": trend
        }