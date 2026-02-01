"""
OSMOSE Pipeline V2 - Theme Lint Checker
=======================================
Ref: doc/ongoing/PLAN_FIX_CONCEPT_ASPIRATEUR.md

Module C: Lint THEME_BUG_SUSPECTED

Détecte les thèmes suspectement vides après import.
Un thème est "suspect" si:
- Il a 0 information liée
- Mais des informations pertinentes (contenant ses keywords) existent ailleurs

Utilise les `lexical_triggers` des concepts du thème pour éviter
les faux positifs avec des mots génériques ("security", "management"...).
"""

import re
import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class ThemeLintIssue:
    """Résultat d'une vérification de thème."""
    theme_name: str
    theme_id: str
    status: str  # "THEME_BUG_SUSPECTED", "OK"
    infos_elsewhere: int
    keywords_matched: List[str]
    recommendation: str


class ThemeLintChecker:
    """
    Post-import governance pour détecter les thèmes suspectement vides.

    Usage:
        checker = ThemeLintChecker(neo4j_client)
        issues = checker.check_theme_coverage(tenant_id)
        for issue in issues:
            if issue.status == "THEME_BUG_SUSPECTED":
                logger.warning(f"Theme '{issue.theme_name}' needs review")
    """

    def __init__(self, neo4j_client=None):
        """
        Args:
            neo4j_client: Client Neo4j avec méthode run(query, **params)
                          Si None, utilise un mode "dry run" pour tests
        """
        self.neo4j = neo4j_client

    def check_theme_coverage(
        self,
        tenant_id: str,
        themes: Optional[List[Dict]] = None,
        concepts: Optional[List[Dict]] = None,
        informations: Optional[List[Dict]] = None,
    ) -> List[ThemeLintIssue]:
        """
        Détecte les thèmes à 0 info mais avec contenu pertinent ailleurs.

        Peut fonctionner en deux modes:
        1. Mode Neo4j: récupère les données depuis la base (neo4j_client requis)
        2. Mode in-memory: utilise les données fournies en paramètres

        Args:
            tenant_id: Identifiant du tenant
            themes: Liste des thèmes (mode in-memory)
            concepts: Liste des concepts (mode in-memory)
            informations: Liste des informations (mode in-memory)

        Returns:
            Liste de ThemeLintIssue pour les thèmes suspects
        """
        if self.neo4j:
            return self._check_via_neo4j(tenant_id)
        elif themes is not None and concepts is not None:
            return self._check_in_memory(themes, concepts, informations or [])
        else:
            logger.warning("[OSMOSE:ThemeLint] Ni Neo4j ni données in-memory, skip")
            return []

    def _check_via_neo4j(self, tenant_id: str) -> List[ThemeLintIssue]:
        """Vérification via requêtes Neo4j."""
        # Étape 1: Récupérer les thèmes vides avec TOUS leurs triggers
        themes_query = """
        MATCH (t:Theme)-[:HAS_CONCEPT]->(c:Concept)
        WHERE t.tenant_id = $tenant_id
        WITH t, c, size((c)-[:HAS_INFORMATION]->()) AS concept_infos
        WITH t, sum(concept_infos) AS total_infos,
             collect({
                 role: c.role,
                 triggers: c.lexical_triggers,
                 name: c.name
             }) AS concepts_data
        WHERE total_infos = 0
        RETURN t.name AS theme,
               t.theme_id AS theme_id,
               concepts_data
        """

        try:
            themes = self.neo4j.run(themes_query, tenant_id=tenant_id)
        except Exception as e:
            logger.error(f"[OSMOSE:ThemeLint] Erreur Neo4j query themes: {e}")
            return []

        issues = []

        for theme_row in themes:
            theme_name = theme_row["theme"]
            theme_id = theme_row["theme_id"]
            concepts_data = theme_row["concepts_data"] or []

            # Sélection intelligente des keywords
            keywords = self._select_best_keywords(concepts_data, theme_name)

            if not keywords:
                continue  # Pas de keywords exploitables

            # Étape 2: Chercher ces keywords dans les infos liées ailleurs
            infos_elsewhere = self._count_infos_with_keywords_neo4j(tenant_id, keywords)

            if infos_elsewhere >= 3:
                issues.append(ThemeLintIssue(
                    theme_name=theme_name,
                    theme_id=theme_id,
                    status="THEME_BUG_SUSPECTED",
                    infos_elsewhere=infos_elsewhere,
                    keywords_matched=keywords[:5],
                    recommendation=f"Vérifier linking - {infos_elsewhere} infos contiennent {keywords[:3]}"
                ))
                logger.warning(
                    f"[OSMOSE:ThemeLint] THEME_BUG_SUSPECTED: '{theme_name}' "
                    f"a 0 info mais {infos_elsewhere} infos contiennent {keywords[:3]}"
                )

        return issues

    def _check_in_memory(
        self,
        themes: List[Dict],
        concepts: List[Dict],
        informations: List[Dict]
    ) -> List[ThemeLintIssue]:
        """
        Vérification in-memory (sans Neo4j).

        Utile pour tests ou quand les données sont déjà en mémoire.
        """
        # Construire les mappings
        concepts_by_theme: Dict[str, List[Dict]] = {}
        for c in concepts:
            theme_id = c.get("theme_id", "")
            if theme_id not in concepts_by_theme:
                concepts_by_theme[theme_id] = []
            concepts_by_theme[theme_id].append(c)

        infos_by_concept: Dict[str, List[Dict]] = {}
        for info in informations:
            concept_id = info.get("concept_id", "")
            if concept_id not in infos_by_concept:
                infos_by_concept[concept_id] = []
            infos_by_concept[concept_id].append(info)

        issues = []

        for theme in themes:
            theme_id = theme.get("theme_id", "")
            theme_name = theme.get("name", "")
            theme_concepts = concepts_by_theme.get(theme_id, [])

            # Compter les infos du thème
            total_infos = sum(
                len(infos_by_concept.get(c.get("concept_id", ""), []))
                for c in theme_concepts
            )

            if total_infos > 0:
                continue  # Thème non vide, OK

            # Thème vide - chercher les keywords
            concepts_data = [
                {
                    "role": c.get("role", "STANDARD"),
                    "triggers": c.get("lexical_triggers", []),
                    "name": c.get("name", "")
                }
                for c in theme_concepts
            ]
            keywords = self._select_best_keywords(concepts_data, theme_name)

            if not keywords:
                continue

            # Chercher les infos ailleurs avec ces keywords
            infos_elsewhere = self._count_infos_with_keywords_memory(informations, keywords)

            if infos_elsewhere >= 3:
                issues.append(ThemeLintIssue(
                    theme_name=theme_name,
                    theme_id=theme_id,
                    status="THEME_BUG_SUSPECTED",
                    infos_elsewhere=infos_elsewhere,
                    keywords_matched=keywords[:5],
                    recommendation=f"Vérifier linking - {infos_elsewhere} infos contiennent {keywords[:3]}"
                ))
                logger.warning(
                    f"[OSMOSE:ThemeLint] THEME_BUG_SUSPECTED: '{theme_name}' "
                    f"a 0 info mais {infos_elsewhere} infos contiennent {keywords[:3]}"
                )

        return issues

    def _select_best_keywords(self, concepts_data: List[Dict], theme_name: str) -> List[str]:
        """
        Sélection intelligente des keywords pour un thème.

        MICRO-AJUSTEMENT 4: Priorité CENTRAL triggers > autres triggers > nom extraction

        Args:
            concepts_data: Liste de {role, triggers, name} pour chaque concept du thème
            theme_name: Nom du thème (fallback)

        Returns:
            Liste de keywords triés par spécificité (plus longs en premier)
        """
        all_triggers = []
        central_triggers = []

        for concept in concepts_data:
            triggers = concept.get("triggers") or []
            role = concept.get("role", "")

            # Filtrer les triggers valides (>= 4 chars)
            valid_triggers = [t for t in triggers if t and len(t) >= 4]

            if role == "CENTRAL":
                central_triggers.extend(valid_triggers)
            all_triggers.extend(valid_triggers)

        # Priorité CENTRAL
        if central_triggers:
            keywords = list(set(central_triggers))
        elif all_triggers:
            keywords = list(set(all_triggers))
        else:
            # Fallback: extraction depuis nom du thème
            keywords = self._extract_keywords_from_name(theme_name)

        # Trier par longueur décroissante (plus spécifiques d'abord)
        keywords.sort(key=lambda x: -len(x))

        return keywords[:10]  # Max 10 keywords

    def _extract_keywords_from_name(self, name: str) -> List[str]:
        """
        Extrait les mots significatifs (>= 5 chars, non stopwords) du nom.

        Args:
            name: Nom du thème ou concept

        Returns:
            Liste de mots significatifs
        """
        # Stopwords à ignorer (trop génériques)
        stopwords = {
            'management', 'security', 'service', 'services', 'system',
            'process', 'control', 'controls', 'model', 'models',
            'general', 'other', 'based', 'related',
        }
        tokens = re.findall(r'\b[a-zA-Z]{5,}\b', name.lower())
        return [t for t in tokens if t not in stopwords][:5]

    def _count_infos_with_keywords_neo4j(self, tenant_id: str, keywords: List[str]) -> int:
        """
        Compte les infos contenant au moins un keyword (via Neo4j).

        Utilise regex word boundary pour match précis.
        """
        # Construire regex pattern pour Neo4j
        # Note: Neo4j supporte regex avec =~
        patterns = [f"(?i)\\\\b{re.escape(kw)}\\\\b" for kw in keywords]

        query = """
        MATCH (i:Information)
        WHERE i.tenant_id = $tenant_id
        AND any(pattern IN $patterns WHERE i.text =~ pattern)
        RETURN count(DISTINCT i) AS cnt
        """
        try:
            result = self.neo4j.run(query, tenant_id=tenant_id, patterns=patterns)
            return result[0]["cnt"] if result else 0
        except Exception as e:
            logger.error(f"[OSMOSE:ThemeLint] Erreur Neo4j count infos: {e}")
            return 0

    def _count_infos_with_keywords_memory(
        self,
        informations: List[Dict],
        keywords: List[str]
    ) -> int:
        """
        Compte les infos contenant au moins un keyword (in-memory).

        Args:
            informations: Liste des informations
            keywords: Keywords à chercher

        Returns:
            Nombre d'infos matchant au moins un keyword
        """
        count = 0
        for info in informations:
            text = info.get("text", "").lower()
            for kw in keywords:
                # Word boundary match
                if re.search(rf'\b{re.escape(kw.lower())}\b', text):
                    count += 1
                    break  # Compter chaque info une seule fois

        return count
