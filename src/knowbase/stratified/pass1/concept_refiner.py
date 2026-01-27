"""
OSMOSE Pipeline V2.1 - Pass 1.2b Concept Refiner
=================================================
Ref: doc/ongoing/PLAN_CAPTATION_V2.md

Raffinement Itératif des Concepts:
- Déclenché quand trop d'assertions sont en NO_CONCEPT_MATCH
- Analyse les assertions non-liées pour identifier les concepts manquants
- Itère jusqu'à saturation (rendement décroissant)

Contraintes ChatGPT Review:
- C2: Critère durci (≥2 assertions dont ≥1 PRESCRIPTIVE ou value-bearing)
- C2b: Obligations sans modal (juridique/contrats)
- C4: Déclencheur stable (no_concept_match_rate > 10% ET count > 20)
"""

import json
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)


# ============================================================================
# SATURATION METRICS
# ============================================================================

@dataclass
class SaturationMetrics:
    """Métriques de saturation conceptuelle."""
    total_assertions: int
    promoted: int
    abstained: int
    rejected: int
    no_concept_match: int
    # C2: Stats pour critère durci
    prescriptive_unlinked: int = 0
    value_bearing_unlinked: int = 0

    @property
    def promotion_rate(self) -> float:
        """Taux de promotion (assertions → Information)."""
        return self.promoted / self.total_assertions if self.total_assertions > 0 else 0

    @property
    def no_concept_match_rate(self) -> float:
        """C4: Ratio NO_CONCEPT_MATCH / TOTAL (plus stable que /abstained)."""
        return self.no_concept_match / self.total_assertions if self.total_assertions > 0 else 0

    @property
    def should_iterate(self) -> bool:
        """C4: Décide si Pass 1.2b est nécessaire."""
        # Condition stable: rate > 10% ET count > 20
        return self.no_concept_match_rate > 0.10 and self.no_concept_match > 20

    @property
    def coverage_rate(self) -> float:
        """Taux de couverture conceptuelle."""
        denominator = self.promoted + self.no_concept_match
        return self.promoted / denominator if denominator > 0 else 0

    @property
    def quality_unlinked_count(self) -> int:
        """C2: Assertions de qualité parmi les non-liées."""
        return self.prescriptive_unlinked + self.value_bearing_unlinked


@dataclass
class IterationResult:
    """Résultat d'une itération Pass 1.2b."""
    iteration: int
    new_concepts: List[Dict]
    assertions_recovered: int
    no_concept_match_before: int
    no_concept_match_after: int
    should_continue: bool


# ============================================================================
# CONCEPT REFINER
# ============================================================================

class ConceptRefinerV2:
    """
    Raffineur de concepts par itération (Pass 1.2b).

    Analyse les assertions NO_CONCEPT_MATCH pour identifier
    les concepts manquants sans relire tout le document.
    """

    # Seuils de saturation
    MIN_NO_CONCEPT_MATCH = 20           # Minimum pour déclencher
    MIN_REDUCTION_RATE = 0.15           # Gain minimum pour continuer
    MAX_ITERATIONS = 3                  # Maximum d'itérations
    MAX_NEW_CONCEPTS_PER_ITER = 10      # Concepts ajoutés par itération
    MAX_TOTAL_CONCEPTS = 50             # Surface max

    # Patterns d'obligations sans modal (C2b)
    OBLIGATION_PATTERNS = [
        re.compile(r'\bis\s+required\s+to\b', re.IGNORECASE),
        re.compile(r'\bis\s+prohibited\b', re.IGNORECASE),
        re.compile(r'\bis\s+mandatory\b', re.IGNORECASE),
        re.compile(r'\bno\s+later\s+than\b', re.IGNORECASE),
        re.compile(r'\bwithin\s+\d+\s*(days?|months?|hours?|weeks?|ans?|mois|jours?)\b', re.IGNORECASE),
        re.compile(r'\bsubject\s+to\b', re.IGNORECASE),
        re.compile(r'\bshall\s+not\b', re.IGNORECASE),
        re.compile(r'\bmay\s+not\b', re.IGNORECASE),
        re.compile(r'\bcannot\b', re.IGNORECASE),
        re.compile(r'\bne\s+(peut|doit)\s+pas\b', re.IGNORECASE),
    ]

    # Patterns de valeurs quantifiables (C2)
    VALUE_PATTERNS = [
        re.compile(r'\d+(\.\d+)+', re.IGNORECASE),                          # Versions: 1.2, 2.0.1
        re.compile(r'\d+\s*%', re.IGNORECASE),                              # Pourcentages
        re.compile(r'\d+\s*(GB|TB|MB|GiB|kg|mg|ml|L)\b', re.IGNORECASE),   # Tailles/poids/volumes
        re.compile(r'\d+\s*°?[CF]', re.IGNORECASE),                         # Températures
        re.compile(r'\d+\s*(ms|s|min|minutes?|h|hours?|days?|ans?|years?|mois|months?|semaines?|weeks?)\b', re.IGNORECASE),  # Durées
        re.compile(r'\d+[:\-]\d+', re.IGNORECASE),                          # Ratios: 1:10, 80-120
        re.compile(r'\d+\s*[KMG]?\s*(EUR|USD|€|\$)', re.IGNORECASE),     # Montants: 500€, 500K€, 5M$
    ]

    def __init__(self, llm_client=None, prompts_path: Optional[Path] = None):
        """
        Args:
            llm_client: Client LLM compatible (generate method)
            prompts_path: Chemin vers prompts YAML
        """
        self.llm_client = llm_client
        self.prompts = self._load_prompts(prompts_path)

    def _load_prompts(self, prompts_path: Optional[Path]) -> Dict:
        """Charge les prompts depuis le fichier YAML."""
        if prompts_path is None:
            prompts_path = Path(__file__).parent.parent / "prompts" / "pass1_prompts.yaml"

        if not prompts_path.exists():
            logger.warning(f"Prompts file not found: {prompts_path}")
            return self._default_prompts()

        with open(prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    def _default_prompts(self) -> Dict:
        """Prompts par défaut si fichier absent."""
        return {
            "concept_refinement": {
                "system": self._default_system_prompt(),
                "user": self._default_user_prompt()
            }
        }

    def calculate_saturation(
        self,
        assertion_log: List[Dict]
    ) -> SaturationMetrics:
        """
        Calcule les métriques de saturation depuis assertion_log.

        Args:
            assertion_log: Liste des entrées du journal d'assertions

        Returns:
            SaturationMetrics avec toutes les métriques
        """
        total = len(assertion_log)
        promoted = sum(1 for a in assertion_log if a.get('status') == 'PROMOTED')
        abstained = sum(1 for a in assertion_log if a.get('status') == 'ABSTAINED')
        rejected = sum(1 for a in assertion_log if a.get('status') == 'REJECTED')
        no_concept_match = sum(
            1 for a in assertion_log
            if a.get('status') == 'ABSTAINED' and a.get('reason') == 'no_concept_match'
        )

        # C2: Compter les assertions de qualité parmi les non-liées
        prescriptive_unlinked = 0
        value_bearing_unlinked = 0

        for a in assertion_log:
            if a.get('status') == 'ABSTAINED' and a.get('reason') == 'no_concept_match':
                if self._is_quality_assertion(a):
                    if a.get('type') == 'PRESCRIPTIVE':
                        prescriptive_unlinked += 1
                    elif self._has_value(a.get('text', '')):
                        value_bearing_unlinked += 1

        return SaturationMetrics(
            total_assertions=total,
            promoted=promoted,
            abstained=abstained,
            rejected=rejected,
            no_concept_match=no_concept_match,
            prescriptive_unlinked=prescriptive_unlinked,
            value_bearing_unlinked=value_bearing_unlinked
        )

    def refine_concepts(
        self,
        unlinked_assertions: List[Dict],
        existing_concepts: List[Dict],
        themes: List[Dict],
        language: str = "en"
    ) -> Tuple[List[Dict], List[str]]:
        """
        Identifie les concepts manquants depuis les assertions non-liées.

        C2: Critère durci - ne considère que les assertions "de qualité"
        (PRESCRIPTIVE ou value-bearing ou obligation implicite).

        Args:
            unlinked_assertions: Assertions avec NO_CONCEPT_MATCH
            existing_concepts: Concepts déjà identifiés
            themes: Thèmes disponibles
            language: Langue du document

        Returns:
            (nouveaux_concepts, raisons_refus)
        """
        if not unlinked_assertions:
            return [], []

        if not self.llm_client:
            logger.warning("[OSMOSE:Pass1.2b] Pas de client LLM, impossible de raffiner")
            return [], ["no_llm_client"]

        # C2: Filtrer pour ne garder que les assertions de qualité
        quality_assertions = [
            a for a in unlinked_assertions
            if self._is_quality_assertion(a)
        ]

        if len(quality_assertions) < 4:
            logger.info(
                f"[OSMOSE:Pass1.2b] Pas assez d'assertions de qualité "
                f"({len(quality_assertions)}) pour justifier de nouveaux concepts"
            )
            return [], ["insufficient_quality_assertions"]

        # Préparer le contexte pour le LLM
        assertions_text = "\n".join([
            f"- [{a.get('type', 'UNKNOWN')}] {a.get('text', '')[:200]}..."
            for a in quality_assertions[:50]  # Max 50 assertions
        ])

        existing_names = [c.get('name', '') for c in existing_concepts]
        themes_names = [t.get('name', '') for t in themes]

        prompt_config = self.prompts.get("concept_refinement", {})
        system_prompt = prompt_config.get("system", self._default_system_prompt())
        user_template = prompt_config.get("user", self._default_user_prompt())

        user_prompt = user_template.format(
            assertions=assertions_text,
            existing_concepts=", ".join(existing_names),
            themes=", ".join(themes_names),
            max_concepts=self.MAX_NEW_CONCEPTS_PER_ITER,
            language=language
        )

        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2000
            )
            new_concepts, refused = self._parse_refinement_response(response, themes)
        except Exception as e:
            logger.error(f"[OSMOSE:Pass1.2b] Erreur LLM: {e}")
            return [], [f"llm_error: {str(e)}"]

        # C2: Valider que chaque nouveau concept a au moins 1 assertion PRESCRIPTIVE ou value
        validated_concepts = []
        for concept in new_concepts:
            if self._validate_concept_quality(concept, quality_assertions):
                validated_concepts.append(concept)
            else:
                refused.append(f"{concept.get('name')}: pas d'assertion PRESCRIPTIVE ou value")

        # === DÉDUPLICATION (2026-01-27) ===
        # 1. Éliminer doublons internes
        # 2. Éliminer concepts déjà existants
        existing_names = {c.get('name', '').lower().strip() for c in existing_concepts}
        seen_names: set = set()
        unique_concepts = []
        duplicates_internal = 0
        duplicates_existing = 0

        for concept in validated_concepts:
            name = concept.get('name', '')
            normalized = name.lower().strip()

            if normalized in existing_names:
                duplicates_existing += 1
                refused.append(f"{name}: doublon d'un concept existant")
                logger.debug(f"[OSMOSE:DEDUP:1.2b] '{name}' existe déjà")
            elif normalized in seen_names:
                duplicates_internal += 1
                refused.append(f"{name}: doublon interne")
                logger.debug(f"[OSMOSE:DEDUP:1.2b] '{name}' doublon interne")
            else:
                seen_names.add(normalized)
                unique_concepts.append(concept)

        if duplicates_internal + duplicates_existing > 0:
            logger.warning(
                f"[OSMOSE:DEDUP:1.2b] {duplicates_internal} doublons internes, "
                f"{duplicates_existing} doublons existants éliminés"
            )
        # === FIN DÉDUPLICATION ===

        logger.info(
            f"[OSMOSE:Pass1.2b] {len(unique_concepts)} nouveaux concepts validés, "
            f"{len(refused)} refusés"
        )

        return unique_concepts, refused

    def _is_quality_assertion(self, assertion: Dict) -> bool:
        """
        C2 + C2b: Vérifie si une assertion est de qualité (digne d'un concept).

        Qualité = PRESCRIPTIVE OU value-bearing OU obligation implicite.
        """
        # Type PRESCRIPTIVE
        if assertion.get('type') == 'PRESCRIPTIVE':
            return True

        text = assertion.get('text', '')

        # C2b: Obligations sans modal (juridique/contrats)
        for pattern in self.OBLIGATION_PATTERNS:
            if pattern.search(text):
                return True

        # Value-bearing: valeur quantifiable (tous domaines)
        if self._has_value(text):
            return True

        return False

    def _has_value(self, text: str) -> bool:
        """Vérifie si le texte contient une valeur quantifiable."""
        for pattern in self.VALUE_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def _validate_concept_quality(
        self,
        concept: Dict,
        assertions: List[Dict]
    ) -> bool:
        """
        C2: Vérifie qu'un concept couvre au moins 1 PRESCRIPTIVE ou value assertion.

        Args:
            concept: Nouveau concept proposé
            assertions: Liste des assertions de qualité

        Returns:
            True si le concept est valide selon C2
        """
        triggers = concept.get('lexical_triggers', [])
        if not triggers:
            return False

        # Trouver les assertions qui matchent les triggers
        matching_assertions = []
        for a in assertions:
            text_lower = a.get('text', '').lower()
            if any(t.lower() in text_lower for t in triggers):
                matching_assertions.append(a)

        # Doit couvrir ≥2 assertions dont ≥1 de qualité
        if len(matching_assertions) < 2:
            return False

        quality_count = sum(1 for a in matching_assertions if self._is_quality_assertion(a))
        return quality_count >= 1

    def _parse_refinement_response(
        self,
        response: str,
        themes: List[Dict]
    ) -> Tuple[List[Dict], List[str]]:
        """Parse la réponse JSON du raffinement."""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            new_concepts = []
            refused = []

            theme_map = {t.get('name', '').lower(): t.get('theme_id', '') for t in themes}

            for c in data.get("new_concepts", []):
                name = c.get("name", "")
                triggers = c.get("lexical_triggers", [])

                if not name or len(triggers) < 2:
                    refused.append(f"{name}: pas assez de triggers")
                    continue

                # Trouver le theme_id
                theme_ref = c.get("theme", "")
                theme_id = theme_map.get(theme_ref.lower(), themes[0].get('theme_id', '') if themes else "")

                new_concepts.append({
                    "name": name,
                    "role": c.get("role", "STANDARD"),
                    "theme_id": theme_id,
                    "lexical_triggers": triggers[:4],  # Max 4
                    "has_prescriptive_or_value": c.get("has_prescriptive_or_value", False)
                })

            # Raisons d'échec
            for u in data.get("uncapturable", []):
                refused.append(u.get("reason", "Non spécifié"))

            return new_concepts, refused

        except json.JSONDecodeError as e:
            logger.warning(f"[OSMOSE:Pass1.2b] JSON parse error: {e}")
            return [], [f"json_error: {str(e)}"]

    def should_continue_iteration(
        self,
        before: SaturationMetrics,
        after: SaturationMetrics,
        iteration: int,
        total_concepts: int
    ) -> bool:
        """
        Décide si une nouvelle itération est justifiée.

        Args:
            before: Métriques avant l'itération
            after: Métriques après l'itération
            iteration: Numéro de l'itération actuelle
            total_concepts: Nombre total de concepts actuellement

        Returns:
            True si on doit continuer, False sinon
        """
        # Critère 1: Max iterations
        if iteration >= self.MAX_ITERATIONS:
            logger.info(f"[OSMOSE:Pass1.2b] Max iterations atteint ({iteration})")
            return False

        # Critère 2: Surface max
        if total_concepts >= self.MAX_TOTAL_CONCEPTS:
            logger.info(f"[OSMOSE:Pass1.2b] Surface max atteinte ({total_concepts} concepts)")
            return False

        # Critère 3: Encore assez de trous
        if after.no_concept_match < self.MIN_NO_CONCEPT_MATCH:
            logger.info(
                f"[OSMOSE:Pass1.2b] Seuil minimum atteint "
                f"({after.no_concept_match} < {self.MIN_NO_CONCEPT_MATCH})"
            )
            return False

        # Critère 4: Gain marginal significatif
        if before.no_concept_match > 0:
            reduction_rate = (
                (before.no_concept_match - after.no_concept_match)
                / before.no_concept_match
            )
            if reduction_rate < self.MIN_REDUCTION_RATE:
                logger.info(
                    f"[OSMOSE:Pass1.2b] Rendement décroissant "
                    f"({reduction_rate:.1%} < {self.MIN_REDUCTION_RATE:.0%})"
                )
                return False

        return True

    def _default_system_prompt(self) -> str:
        """Prompt système par défaut pour le raffinement."""
        return """Tu es un expert en identification de concepts MANQUANTS pour OSMOSE.

CONTEXTE:
On te donne des assertions qui N'ONT PAS PU être liées aux concepts existants.
Ta tâche: identifier les concepts MANQUANTS qui permettraient de les capturer.

RÈGLES CRITIQUES:
- Concepts SPÉCIFIQUES et ACTIONNABLES (pas génériques)
- Ne pas répéter les concepts existants
- Chaque concept doit correspondre à AU MOINS 2 assertions fournies

LEXICAL TRIGGERS:
Chaque nouveau concept DOIT avoir 2-4 lexical_triggers:
- Tokens qui APPARAISSENT dans les assertions fournies
- Pas de paraphrases ou synonymes inventés"""

    def _default_user_prompt(self) -> str:
        """Prompt utilisateur par défaut pour le raffinement."""
        return """Identifie les concepts MANQUANTS depuis ces assertions non-liées.

ASSERTIONS NON LIÉES:
{assertions}

CONCEPTS EXISTANTS (à ne pas répéter):
{existing_concepts}

THÈMES DISPONIBLES:
{themes}

LANGUE: {language}

Maximum {max_concepts} nouveaux concepts.

Réponds avec ce JSON:
```json
{{
  "new_concepts": [
    {{
      "name": "Nom spécifique",
      "role": "STANDARD",
      "theme": "Thème",
      "lexical_triggers": ["token1", "token2"],
      "has_prescriptive_or_value": true
    }}
  ],
  "uncapturable": [
    {{"reason": "Raison"}}
  ]
}}
```"""
