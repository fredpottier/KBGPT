"""
OSMOSE Pipeline V2 - Phase 1.2 Concept Identifier
==================================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Identification des concepts avec surface conceptuelle élargie:
- Maximum 30 concepts par document (V2.1 - augmenté depuis 15)
- Rôle: CENTRAL, STANDARD, CONTEXTUAL
- Rattachement aux thèmes
- Lexical triggers obligatoires (C1)

Adapté du POC: poc/extractors/concept_identifier.py
"""

import asyncio
import json
import re
import logging
import math
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path
import yaml

from knowbase.stratified.models import (
    Concept,
    ConceptRole,
    Theme,
)

logger = logging.getLogger(__name__)

# Patterns valeur (autorisés même si < 3 chars) - C1b
VALUE_PATTERN = re.compile(r'^\d+(\.\d+)*[%°]?[CFc]?$|^\d+[:\-]\d+$')

# Patterns produit SAP (whitelist - toujours discriminants) - C1 two-tier
SAP_PRODUCT_PATTERNS = re.compile(
    r'\b(SAP|RISE|S/4HANA|S4HANA|BTP|HANA|Datasphere|Ariba|SuccessFactors|'
    r'Concur|Fieldglass|Signavio|SAProuter|SolMan|ECC|ERP|CRM|SRM|SCM|GRC|'
    r'Fiori|ABAP|RFC|IDoc|BAPI|OData)\b',
    re.IGNORECASE
)

# Stopwords linguistiques (EN/FR) - distincts des tokens métier fréquents
LINGUISTIC_STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'which', 'will',
    'are', 'was', 'were', 'been', 'being', 'have', 'has', 'had', 'does',
    'did', 'can', 'could', 'should', 'would', 'may', 'might', 'must',
    'shall', 'into', 'through', 'during', 'before', 'after', 'above',
    'below', 'between', 'under', 'over', 'such', 'other', 'each', 'only',
    'also', 'both', 'than', 'then', 'more', 'most', 'some', 'any', 'all',
    'les', 'des', 'une', 'pour', 'avec', 'dans', 'sur', 'par', 'aux',
    'est', 'sont', 'être', 'avoir', 'fait', 'peut', 'doit', 'cette', 'ces',
}

# Termes génériques métier (toujours non-discriminants seuls)
GENERIC_DOMAIN_TERMS = {
    'solution', 'service', 'system', 'model', 'environment', 'operations',
    'management', 'process', 'method', 'approach', 'framework', 'platform',
    'application', 'component', 'module', 'feature', 'function', 'capability',
    'resource', 'asset', 'element', 'item', 'object', 'entity', 'instance',
}


# ============================================================================
# BUDGET ADAPTATIF (2026-01-28)
# ============================================================================
# Formule: MAX_CONCEPTS = clamp(MIN, MAX, 15 + sqrt(sections) * 3)
# - Croissance sub-linéaire: 4x sections → ~2x concepts
# - Plancher 20: assez pour petits documents
# - Plafond 60: permet une bonne couverture des gros documents

CONCEPT_BUDGET_MIN = 20      # Minimum concepts (petits documents)
CONCEPT_BUDGET_MAX = 60      # Maximum concepts (gros documents)
CONCEPT_BUDGET_BASE = 15     # Base fixe
CONCEPT_BUDGET_FACTOR = 3    # Facteur multiplicateur de sqrt(sections)


def compute_concept_budget(n_sections: int, is_hostile: bool = False) -> int:
    """
    Calcule le budget de concepts adaptatif basé sur la structure du document.

    Formule: clamp(20, 60, 15 + sqrt(sections) * 3)

    ADR HOSTILE v2: HOSTILE est un signal diagnostique, pas une pénalité.
    La densité documentaire (beaucoup de thèmes cohérents) est une qualité,
    pas un risque. La pénalité budget//2 est supprimée.
    Le flag is_hostile est conservé pour logging/monitoring uniquement.

    Args:
        n_sections: Nombre de sections dans le document
        is_hostile: Signal diagnostique (pas de pénalité budget)

    Returns:
        Nombre maximum de concepts à identifier

    Examples:
        - 20 sections → 28 concepts
        - 50 sections → 36 concepts
        - 200 sections → 57 concepts
        - 431 sections → 60 concepts (cap)
    """
    if n_sections <= 0:
        return CONCEPT_BUDGET_MIN

    raw_budget = CONCEPT_BUDGET_BASE + math.sqrt(n_sections) * CONCEPT_BUDGET_FACTOR
    budget = max(CONCEPT_BUDGET_MIN, min(CONCEPT_BUDGET_MAX, round(raw_budget)))

    if is_hostile:
        # ADR HOSTILE v2: log seulement, pas de pénalité
        logger.info(
            f"[OSMOSE:Pass1:1.2] Document HOSTILE — budget maintenu à {budget} "
            f"(densité ≠ incohérence)"
        )

    return budget


class ConceptIdentifierV2:
    """
    Identificateur de concepts pour Pipeline V2.

    BUDGET ADAPTATIF (V2.2 - 2026-01-27):
    - Budget calculé selon: clamp(25, 80, 15 + sqrt(sections) * 3)
    - Croissance sub-linéaire: 4x sections → ~2x concepts
    - Lexical triggers obligatoires (C1)
    - Validation anti-triggers triviaux (C1b)

    IMPORTANT: Pas de fallback silencieux - erreur explicite si LLM absent.
    """

    # Fallback si nombre de sections non fourni (legacy)
    MAX_CONCEPTS_FALLBACK = 30      # Documents normaux sans info sections
    MAX_CONCEPTS_HOSTILE = 30       # ADR HOSTILE v2: même budget, HOSTILE = signal pas pénalité

    def __init__(
        self,
        llm_client=None,
        prompts_path: Optional[Path] = None,
        allow_fallback: bool = False
    ):
        """
        Args:
            llm_client: Client LLM compatible (generate method)
            prompts_path: Chemin vers prompts YAML
            allow_fallback: Si True, autorise le fallback heuristique (test only)
        """
        self.llm_client = llm_client
        self.prompts = self._load_prompts(prompts_path)
        self.allow_fallback = allow_fallback

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
            "concept_identification": {
                "system": self._default_system_prompt(),
                "user": self._default_user_prompt()
            }
        }

    def identify(
        self,
        doc_id: str,
        subject_text: str,
        structure: str,
        themes: List[Theme],
        content: str,
        is_hostile: bool = False,
        language: str = "fr",
        n_sections: Optional[int] = None
    ) -> Tuple[List[Concept], List[Dict]]:
        """
        Identifie les concepts situés du document.

        Args:
            doc_id: Identifiant du document
            subject_text: Texte du sujet (de Phase 1.1)
            structure: Structure (CENTRAL, TRANSVERSAL, CONTEXTUAL)
            themes: Thèmes identifiés (de Phase 1.1)
            content: Contenu textuel complet
            is_hostile: True si document HOSTILE (réduit budget de moitié)
            language: Langue du document
            n_sections: Nombre de sections (pour budget adaptatif)
                        Si None, utilise le fallback fixe

        Returns:
            Tuple[List[Concept], List[Dict]]
            - concepts: Liste des concepts identifiés
            - refused_terms: Termes refusés avec raisons
        """
        # Budget adaptatif basé sur la structure du document
        if n_sections is not None and n_sections > 0:
            max_concepts = compute_concept_budget(n_sections, is_hostile)
            logger.info(
                f"[OSMOSE:Pass1:1.2] Budget adaptatif: {n_sections} sections → "
                f"{max_concepts} concepts max"
            )
        else:
            # Fallback si pas d'info sections
            max_concepts = self.MAX_CONCEPTS_HOSTILE if is_hostile else self.MAX_CONCEPTS_FALLBACK
            logger.debug(f"[OSMOSE:Pass1:1.2] Budget fallback: {max_concepts} concepts max")

        # =====================================================================
        # DISPATCH VERS MODE BATCH PAR THÈME (2026-01-28)
        # =====================================================================
        # Si plusieurs thèmes ET budget élevé → extraction par batch thématique
        # Évite la troncature JSON en limitant ~10-15 concepts par appel LLM
        # Note: les documents HOSTILE (>15 thèmes) bénéficient aussi du batch mode
        # car l'appel unique risque la troncature JSON avec beaucoup de refusés
        use_batch_mode = (
            len(themes) >= 3 and
            max_concepts >= 15 and
            self.llm_client is not None
        )

        if use_batch_mode:
            logger.info(
                f"[OSMOSE:Pass1:1.2] Mode batch par thème activé: "
                f"{len(themes)} thèmes, budget {max_concepts} concepts"
            )
            # Appeler la version async depuis contexte sync
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # Pas de loop en cours, en créer une
                loop = None

            if loop is not None:
                # Déjà dans un contexte async
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.identify_by_theme(
                            doc_id, subject_text, themes, content, language
                        )
                    )
                    concepts, refused = future.result()
            else:
                # Contexte sync, utiliser asyncio.run()
                concepts, refused = asyncio.run(
                    self.identify_by_theme(
                        doc_id, subject_text, themes, content, language
                    )
                )

            # Appliquer limite frugalité (sécurité)
            if len(concepts) > max_concepts:
                logger.warning(
                    f"[OSMOSE:Pass1:1.2] Frugalité batch: {len(concepts)} → {max_concepts}"
                )
                concepts = self._apply_frugality(concepts, max_concepts)

            return concepts, refused

        # =====================================================================
        # MODE STANDARD (appel unique pour petits documents)
        # =====================================================================
        # Construire le prompt
        prompt_config = self.prompts.get("concept_identification", {})
        system_prompt = prompt_config.get("system", self._default_system_prompt())
        user_template = prompt_config.get("user", self._default_user_prompt())

        themes_str = self._format_themes(themes)

        user_prompt = user_template.format(
            subject=subject_text,
            structure=structure,
            themes=themes_str,
            content=content[:10000],  # Contexte augmenté (vLLM 16K)
            language=language,
            max_concepts=max_concepts
        )

        # Appeler le LLM
        if self.llm_client:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=6000  # vLLM 16K: input ~3-4K + output 6K = ~10K < 16384
            )
            # V2.1: Passer le contenu pour validation des lexical_triggers
            concepts, refused = self._parse_response(response, doc_id, themes, content)
        elif self.allow_fallback:
            logger.warning("[OSMOSE:Pass1:1.2] Mode fallback activé - résultats non fiables")
            concepts, refused = self._fallback_identification(doc_id, subject_text, themes, content)
        else:
            raise RuntimeError(
                "LLM non disponible et fallback non autorisé. "
                "Utilisez allow_fallback=True uniquement pour les tests."
            )

        # GARDE-FOU: Appliquer limite frugalité
        if len(concepts) > max_concepts:
            logger.warning(
                f"[OSMOSE:Pass1:1.2] Frugalité: {len(concepts)} concepts → {max_concepts}"
            )
            # Garder les CENTRAL d'abord, puis STANDARD, puis CONTEXTUAL
            concepts = self._apply_frugality(concepts, max_concepts)

        logger.info(
            f"[OSMOSE:Pass1:1.2] {len(concepts)} concepts identifiés, "
            f"{len(refused)} termes refusés"
        )

        return concepts, refused

    # =========================================================================
    # EXTRACTION PAR BATCH THÉMATIQUE (2026-01-28)
    # =========================================================================
    # Évite la troncature JSON en extrayant ~10 concepts par thème
    # au lieu de 50+ concepts en un seul appel.

    async def identify_by_theme(
        self,
        doc_id: str,
        subject_text: str,
        themes: List[Theme],
        content: str,
        language: str = "fr"
    ) -> Tuple[List[Concept], List[Dict]]:
        """
        Identifie les concepts en parallèle par thème.

        Chaque thème = 1 appel LLM avec quota limité (~10 concepts).
        Merge + déduplication à la fin.

        Args:
            doc_id: Identifiant du document
            subject_text: Résumé du sujet (de Phase 1.1)
            themes: Liste des thèmes identifiés
            content: Contenu textuel complet
            language: Langue du document

        Returns:
            Tuple[List[Concept], List[Dict]]
        """
        if not self.llm_client:
            raise RuntimeError(
                "LLM client requis pour extraction par thème. "
                "Utilisez identify() avec allow_fallback=True pour le mode heuristique."
            )

        # Calculer le budget par thème
        total_budget = compute_concept_budget(len(themes) * 10)  # Approximation sections
        concepts_per_theme = max(8, min(15, total_budget // len(themes)))

        logger.info(
            f"[OSMOSE:Pass1:1.2] Mode batch par thème activé ({len(themes)} thèmes)"
        )
        logger.info(
            f"[OSMOSE:Pass1:1.2] Extraction par thème: {len(themes)} thèmes, "
            f"{concepts_per_theme} concepts/thème max"
        )

        # === C1 TWO-TIER: Calculer les forbidden_triggers (top-50) ===
        # Ces tokens fréquents seront passés au LLM pour qu'il les évite
        forbidden_triggers = self._get_top_frequent_tokens(content, n=50)
        logger.info(
            f"[OSMOSE:Pass1:1.2:C1] {len(forbidden_triggers)} forbidden triggers calculés"
        )

        # Préparer les tâches parallèles
        tasks = []
        for theme in themes:
            # Extraire le contenu pertinent pour ce thème
            theme_content = self._extract_theme_content(content, theme)

            task = self._extract_concepts_for_theme(
                doc_id=doc_id,
                subject_text=subject_text,
                theme=theme,
                theme_content=theme_content,
                language=language,
                max_concepts=concepts_per_theme,
                forbidden_triggers=forbidden_triggers  # Pass to LLM prompt
            )
            tasks.append((theme, task))

        # Exécuter en parallèle
        coroutines = [t[1] for t in tasks]
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        # Merge et déduplication
        all_concepts: List[Concept] = []
        all_refused: List[Dict] = []
        failed_themes: List[str] = []

        for i, result in enumerate(results):
            theme = themes[i]
            if isinstance(result, Exception):
                logger.error(
                    f"[OSMOSE:Pass1:1.2] Échec thème '{theme.name}': {result}"
                )
                failed_themes.append(theme.name)
                # Retry une fois
                try:
                    theme_content = self._extract_theme_content(content, theme)
                    retry_result = await self._extract_concepts_for_theme(
                        doc_id=doc_id,
                        subject_text=subject_text,
                        theme=theme,
                        theme_content=theme_content,
                        language=language,
                        max_concepts=concepts_per_theme,
                        forbidden_triggers=forbidden_triggers
                    )
                    concepts, refused = retry_result
                    all_concepts.extend(concepts)
                    all_refused.extend(refused)
                    logger.info(f"[OSMOSE:Pass1:1.2] Retry réussi pour thème '{theme.name}'")
                except Exception as retry_err:
                    logger.error(f"[OSMOSE:Pass1:1.2] Retry échoué '{theme.name}': {retry_err}")
            else:
                concepts, refused = result
                all_concepts.extend(concepts)
                all_refused.extend(refused)
                logger.debug(
                    f"[OSMOSE:Pass1:1.2] Thème '{theme.name}': {len(concepts)} concepts"
                )

        # Déduplication globale
        unique_concepts = self._deduplicate_concepts(all_concepts, doc_id)

        logger.info(
            f"[OSMOSE:Pass1:1.2] Total: {len(unique_concepts)} concepts uniques "
            f"(avant dédup: {len(all_concepts)})"
        )

        if failed_themes:
            logger.warning(
                f"[OSMOSE:Pass1:1.2] Thèmes en échec: {failed_themes}"
            )

        return unique_concepts, all_refused

    async def _extract_concepts_for_theme(
        self,
        doc_id: str,
        subject_text: str,
        theme: Theme,
        theme_content: str,
        language: str,
        max_concepts: int,
        forbidden_triggers: Set[str] = None
    ) -> Tuple[List[Concept], List[Dict]]:
        """
        Extrait les concepts pour UN thème spécifique.

        Appel LLM avec quota limité = pas de troncature.
        V2.3: Passe les forbidden_triggers au LLM pour éviter rejets C1.

        Args:
            doc_id: Identifiant du document
            subject_text: Résumé du sujet
            theme: Le thème à traiter
            theme_content: Contenu filtré pour ce thème
            language: Langue du document
            max_concepts: Nombre max de concepts pour ce thème
            forbidden_triggers: Set des tokens interdits (top-K + mots du thème)

        Returns:
            Tuple[List[Concept], List[Dict]]
        """
        prompt_config = self.prompts.get("concept_identification_by_theme", {})
        system_prompt = prompt_config.get("system", "")
        user_template = prompt_config.get("user", "")

        if not system_prompt or not user_template:
            logger.warning(
                "[OSMOSE:Pass1:1.2] Prompt 'concept_identification_by_theme' non trouvé, "
                "utilisation du prompt standard"
            )
            # Fallback vers le prompt standard
            prompt_config = self.prompts.get("concept_identification", {})
            system_prompt = prompt_config.get("system", self._default_system_prompt())
            user_template = prompt_config.get("user", self._default_user_prompt())

        # Construire la liste des forbidden triggers pour le prompt
        # Inclut: top-K tokens fréquents + mots du thème + stopwords linguistiques
        if forbidden_triggers is None:
            forbidden_triggers = set()

        # Ajouter les mots du thème (trop génériques)
        theme_words = {
            w.lower() for w in re.findall(r'\b\w+\b', theme.name)
            if len(w) >= 3
        }
        all_forbidden = forbidden_triggers | theme_words | LINGUISTIC_STOPWORDS

        # Formater pour le prompt (limiter à 50 pour ne pas surcharger)
        forbidden_list = sorted(all_forbidden)[:50]
        forbidden_str = ', '.join(forbidden_list) if forbidden_list else "(none)"

        # Remplacer {theme_name} dans le system prompt aussi
        system_prompt_formatted = system_prompt.replace("{theme_name}", theme.name)

        user_prompt = user_template.format(
            subject=subject_text,
            theme_name=theme.name,
            language=language,
            max_concepts_per_theme=max_concepts,
            theme_content=theme_content[:4000],  # Limite par thème (contexte réduit)
            forbidden_triggers=forbidden_str
        )

        # Appeler le LLM
        # Note: generate_async si disponible, sinon run_in_executor
        if hasattr(self.llm_client, 'generate_async'):
            response = await self.llm_client.generate_async(
                system_prompt=system_prompt_formatted,
                user_prompt=user_prompt,
                max_tokens=2500  # Suffisant pour 10-15 concepts
            )
        else:
            # Fallback sync avec executor
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.llm_client.generate(
                    system_prompt=system_prompt_formatted,
                    user_prompt=user_prompt,
                    max_tokens=2500
                )
            )

        # Parser le JSON (petit donc pas de troncature)
        # batch_mode=True active C1 two-tier (plus permissif pour triggers fréquents)
        concepts, refused = self._parse_response(
            response, doc_id, [theme], theme_content, batch_mode=True
        )

        # Assigner le theme_id à chaque concept
        for concept in concepts:
            concept.theme_id = theme.theme_id

        return concepts, refused

    def _extract_theme_content(self, full_content: str, theme: Theme) -> str:
        """
        Extrait les portions du contenu pertinentes pour un thème.

        Utilise les mots-clés du thème pour filtrer les paragraphes.

        Args:
            full_content: Contenu complet du document
            theme: Le thème à filtrer

        Returns:
            Contenu filtré pour ce thème (max ~4000 chars)
        """
        # Découper en paragraphes
        paragraphs = re.split(r'\n\n+', full_content)

        # Extraire les mots-clés du nom du thème (min 3 chars)
        theme_keywords = [
            word.lower()
            for word in re.findall(r'\b\w+\b', theme.name)
            if len(word) >= 3
        ]

        if not theme_keywords:
            # Fallback si thème trop court
            return full_content[:4000]

        # Scorer chaque paragraphe
        scored = []
        for para in paragraphs:
            para_stripped = para.strip()
            if len(para_stripped) < 50:
                continue  # Ignorer les paragraphes trop courts

            para_lower = para_stripped.lower()
            score = sum(1 for kw in theme_keywords if kw in para_lower)

            if score > 0:
                scored.append((score, para_stripped))

        # Trier par score décroissant
        scored.sort(key=lambda x: -x[0])

        # Garder les paragraphes les plus pertinents (max 4000 chars)
        result = []
        total_chars = 0
        max_chars = 4000

        for score, para in scored:
            if total_chars + len(para) > max_chars:
                # Tronquer le dernier paragraphe si nécessaire
                remaining = max_chars - total_chars
                if remaining > 100:
                    result.append(para[:remaining] + "...")
                break
            result.append(para)
            total_chars += len(para) + 2  # +2 pour \n\n

        if result:
            return '\n\n'.join(result)
        else:
            # Aucun paragraphe pertinent trouvé, fallback
            logger.debug(
                f"[OSMOSE:Pass1:1.2] Aucun contenu pertinent pour thème '{theme.name}', "
                "utilisation du début du document"
            )
            return full_content[:4000]

    def _deduplicate_concepts(
        self,
        concepts: List[Concept],
        doc_id: str
    ) -> List[Concept]:
        """
        Déduplique les concepts par nom normalisé.

        Garde la première occurrence, réassigne les IDs après déduplication.

        Args:
            concepts: Liste de concepts potentiellement dupliqués
            doc_id: Identifiant du document (pour les IDs)

        Returns:
            Liste de concepts uniques avec IDs réassignés
        """
        seen_names: Set[str] = set()
        unique: List[Concept] = []

        for concept in concepts:
            normalized = concept.name.lower().strip()
            if normalized not in seen_names:
                seen_names.add(normalized)
                unique.append(concept)

        # Réassigner les IDs séquentiellement
        for i, concept in enumerate(unique):
            concept.concept_id = f"concept_{doc_id}_{i}"

        return unique

    def _format_themes(self, themes: List[Theme]) -> str:
        """Formate les thèmes pour le prompt."""
        return '\n'.join(f"- {theme.name}" for theme in themes)

    def _clean_json_string(self, json_str: str) -> str:
        """
        Nettoie le JSON généré par LLM (trailing commas, comments, etc.).

        Les modèles locaux (Qwen, etc.) génèrent parfois du JSON invalide.
        """
        # Supprimer les commentaires // et /* */
        json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)

        # Supprimer les trailing commas avant } ou ]
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)

        # Remplacer les single quotes par double quotes (si pas dans une string)
        # Attention: simplification, peut ne pas gérer tous les cas
        json_str = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', json_str)

        return json_str.strip()

    def _parse_response(
        self,
        response: str,
        doc_id: str,
        themes: List[Theme],
        doc_content: str = "",
        batch_mode: bool = False
    ) -> Tuple[List[Concept], List[Dict]]:
        """
        Parse la réponse JSON du LLM avec détection de troncature et nettoyage.

        V2.1: Valide également les lexical_triggers si doc_content est fourni.
        V2.3: Support batch_mode pour C1 two-tier (2026-01-28).
        """
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        # GUARDRAIL: Détection troncature JSON (ADR: LLM Contract)
        json_str_stripped = json_str.strip()
        if json_str_stripped and not json_str_stripped.endswith(('}', ']')):
            logger.error(
                f"[OSMOSE:Pass1:1.2] TRONCATURE DÉTECTÉE - JSON incomplet. "
                f"Fin: ...{json_str_stripped[-100:]}"
            )
            raise ValueError(
                f"LLM Contract Violation: JSON tronqué détecté. "
                f"Le modèle a probablement atteint sa limite de tokens. "
                f"Fin de réponse: ...{json_str_stripped[-50:]}"
            )

        # Nettoyage JSON pour modèles locaux (trailing commas, etc.)
        json_str_clean = self._clean_json_string(json_str_stripped)

        try:
            data = json.loads(json_str_clean)
            # V2.1: Passer doc_content pour validation C1
            # V2.3: Passer batch_mode pour C1 two-tier
            return self._validate_and_convert(
                data, doc_id, themes, doc_content, batch_mode=batch_mode
            )
        except json.JSONDecodeError as e:
            logger.error(f"Réponse LLM invalide: {e}")
            logger.debug(f"JSON brut: {json_str_stripped[:500]}")
            logger.debug(f"JSON nettoyé: {json_str_clean[:500]}")
            raise ValueError(f"Réponse LLM invalide: {e}\nRéponse: {response[:500]}")

    def _validate_and_convert(
        self,
        data: Dict,
        doc_id: str,
        themes: List[Theme],
        doc_content: str = "",
        unit_texts: Optional[List[str]] = None,
        batch_mode: bool = False
    ) -> Tuple[List[Concept], List[Dict]]:
        """
        Valide et convertit la réponse en objets Pydantic V2.

        V2.1: Valide également les lexical_triggers (C1, C1b, C1c).
        V2.3: Support batch_mode pour C1 two-tier (2026-01-28).
        """
        concepts = []
        refused = []
        theme_map = {t.name.lower(): t.theme_id for t in themes}

        # Calculer les top 50 tokens fréquents pour C1b (anti-trivial)
        top_50_tokens = self._get_top_frequent_tokens(doc_content, n=50) if doc_content else set()

        # Préparer unit_texts si non fourni (utiliser le contenu découpé)
        if unit_texts is None and doc_content:
            # Découper en pseudo-unités (paragraphes/phrases)
            unit_texts = [p.strip() for p in re.split(r'\n\n+|\. ', doc_content) if p.strip()]

        valid_idx = 0
        for c_data in data.get("concepts", []):
            name = c_data.get("name", f"Concept_{valid_idx}")
            triggers = c_data.get("lexical_triggers", [])

            # Valider les lexical_triggers (C1, C1b, C1c) + C1 two-tier en batch_mode
            triggers_audit = {}  # Audit pour validation rôle C1b
            if doc_content and triggers:
                is_valid, triggers_audit = self._validate_lexical_triggers(
                    c_data, doc_content, unit_texts or [], top_50_tokens,
                    batch_mode=batch_mode
                )
                if not is_valid:
                    refused.append({
                        "term": name,
                        "reason": f"Triggers invalides: {triggers_audit.get('rejected', [])}"
                    })
                    logger.debug(f"[OSMOSE:C1] Concept rejeté '{name}': {triggers_audit}")
                    continue
            elif not triggers:
                # Pas de triggers fournis - accepter avec warning (rétrocompatibilité)
                logger.warning(f"[OSMOSE:C1] Concept '{name}' sans triggers (LLM n'a pas respecté le format)")

            # Valider et potentiellement dégrader le rôle selon C1b (2026-01-27)
            # Empêche les concepts "aspirateur" avec triggers génériques d'être CENTRAL
            role = self._validate_role_requirements(c_data, triggers_audit)

            # Trouver le theme_id correspondant
            theme_ref = c_data.get("theme", "")
            theme_id = theme_map.get(theme_ref.lower(), themes[0].theme_id if themes else "")

            # Générer lex_key (clé lexicale normalisée)
            lex_key = self._generate_lex_key(name)

            concept = Concept(
                concept_id=f"concept_{doc_id}_{valid_idx}",
                theme_id=theme_id,
                name=name,
                definition=c_data.get("definition"),
                role=role,
                variants=c_data.get("variants", []),
                lex_key=lex_key,
                lexical_triggers=triggers[:4]  # Max 4 triggers
            )
            concepts.append(concept)
            valid_idx += 1

        # === DÉDUPLICATION PAR NOM (2026-01-27) ===
        # Le LLM (Qwen notamment) peut renvoyer le même concept plusieurs fois
        # On garde uniquement la première occurrence par nom normalisé
        seen_names: Set[str] = set()
        unique_concepts = []
        duplicates_removed = 0

        for concept in concepts:
            normalized_name = concept.name.lower().strip()
            if normalized_name not in seen_names:
                seen_names.add(normalized_name)
                unique_concepts.append(concept)
            else:
                duplicates_removed += 1
                logger.debug(f"[OSMOSE:DEDUP] Doublon éliminé: '{concept.name}'")

        if duplicates_removed > 0:
            logger.warning(
                f"[OSMOSE:DEDUP] {duplicates_removed} concepts dupliqués éliminés "
                f"({len(concepts)} → {len(unique_concepts)})"
            )
            # Réindexer les concept_id après déduplication
            for idx, concept in enumerate(unique_concepts):
                concept.concept_id = f"concept_{doc_id}_{idx}"
            concepts = unique_concepts
        # === FIN DÉDUPLICATION ===

        # Ajouter les termes refusés par le LLM
        for r in data.get("refused_terms", []):
            refused.append({
                "term": r.get("term", ""),
                "reason": r.get("reason", "Non spécifié")
            })

        return concepts, refused

    def _get_top_frequent_tokens(self, content: str, n: int = 50) -> Set[str]:
        """
        Calcule les n tokens les plus fréquents du document.

        Utilisé pour C1b: rejeter les triggers trop fréquents.
        """
        # Tokeniser simplement (mots alphanumériques)
        tokens = re.findall(r'\b\w+\b', content.lower())
        # Filtrer les tokens trop courts
        tokens = [t for t in tokens if len(t) >= 3]
        # Compter les fréquences
        freq = Counter(tokens)
        # Retourner les n plus fréquents
        return {t for t, _ in freq.most_common(n)}

    def _validate_role_requirements(
        self,
        concept: Dict,
        triggers_audit: Dict
    ) -> ConceptRole:
        """
        Valide et ajuste le rôle selon les triggers discriminants.

        Règle C1b renforcée (2026-01-27 - Phase 1 Nettoyage):
        - CENTRAL requiert au moins 1 trigger rare (<1%) ou valeur
        - STANDARD requiert au moins 1 trigger semi-rare (<2%) ou valeur
        - Sinon → CONTEXTUAL

        Ceci empêche les concepts "aspirateur" (ex: "infrastructure SAP")
        avec triggers trop génériques de devenir CENTRAL.

        Args:
            concept: Dict avec 'name' et 'role'
            triggers_audit: Dict retourné par _validate_lexical_triggers

        Returns:
            ConceptRole ajusté
        """
        name = concept.get('name', 'Unknown')
        requested_role = concept.get('role', 'STANDARD').upper()

        # Vérifier si au moins 1 trigger est discriminant
        has_rare = triggers_audit.get('rare_found', False)
        has_semi_rare = any(
            t_info.get('rare') in [True, 'semi-rare', 'fallback_value']
            for t_info in triggers_audit.get('triggers', {}).values()
        )

        # Appliquer les règles de dégradation
        if requested_role == 'CENTRAL':
            if not has_rare:
                if has_semi_rare:
                    logger.info(
                        f"[OSMOSE:C1b] '{name}' dégradé "
                        f"CENTRAL → STANDARD (pas de trigger rare)"
                    )
                    return ConceptRole.STANDARD
                else:
                    logger.info(
                        f"[OSMOSE:C1b] '{name}' dégradé "
                        f"CENTRAL → CONTEXTUAL (pas de trigger discriminant)"
                    )
                    return ConceptRole.CONTEXTUAL

        if requested_role == 'STANDARD':
            if not has_semi_rare and not has_rare:
                logger.info(
                    f"[OSMOSE:C1b] '{name}' dégradé "
                    f"STANDARD → CONTEXTUAL (pas de trigger discriminant)"
                )
                return ConceptRole.CONTEXTUAL

        # Rôle valide - retourner tel quel
        try:
            return ConceptRole(requested_role)
        except ValueError:
            return ConceptRole.STANDARD

    def _validate_lexical_triggers(
        self,
        concept: Dict,
        doc_content: str,
        unit_texts: List[str],
        top_50_tokens: Set[str],
        batch_mode: bool = False
    ) -> Tuple[bool, Dict]:
        """
        Valide les lexical_triggers avec C1 two-tier (2026-01-28).

        NOUVELLE LOGIQUE C1 TWO-TIER:
        Un concept est ACCEPTÉ si AU MOINS UNE de ces conditions est vraie:
        1. discriminant_trigger: au moins 1 trigger hors top-K ET hors stopwords
        2. composite_trigger: au moins 1 trigger snake_case avec 3+ sous-tokens
        3. product_pattern: le nom matche un pattern produit SAP connu
        4. rare_compound: le nom complet (n-gram) est rare dans le document

        Args:
            concept: Dict avec 'name' et 'lexical_triggers'
            doc_content: Contenu complet du document
            unit_texts: Liste des textes des unités (pour calcul fréquence)
            top_50_tokens: Set des 50 tokens les plus fréquents
            batch_mode: Si True, utilise la logique two-tier plus permissive

        Returns:
            (is_valid, audit_info)
        """
        triggers = concept.get('lexical_triggers', [])
        concept_name = concept.get('name', '')
        audit = {
            'concept': concept_name,
            'triggers': {},
            'rejected': [],
            'acceptance_reason': None
        }

        if len(triggers) < 2:
            audit['rejected'].append('< 2 triggers')
            return False, audit

        valid_triggers = []
        rare_trigger_found = False
        composite_trigger_found = False
        doc_lower = doc_content.lower()
        total_units = len(unit_texts) if unit_texts else 1

        # === NOUVELLE RÈGLE 1: Product Pattern Check ===
        # Si le nom du concept matche un pattern produit SAP, c'est discriminant
        product_match = SAP_PRODUCT_PATTERNS.search(concept_name)
        if product_match:
            audit['product_pattern'] = product_match.group()
            logger.debug(f"[OSMOSE:C1] '{concept_name}' matche product pattern: {product_match.group()}")

        # === NOUVELLE RÈGLE 2: Compound Rarity Check ===
        # Vérifier si le nom complet (ou trigram central) est rare
        compound_rare = self._check_compound_rarity(concept_name, doc_lower, total_units, unit_texts)
        audit['compound_rare'] = compound_rare

        for t in triggers:
            t_lower = t.lower()
            trigger_info = {'trigger': t, 'found': False, 'frequency': 0, 'examples': []}

            # C1b: Refuser < 3 chars sauf patterns valeur
            if len(t) < 3 and not VALUE_PATTERN.match(t):
                audit['rejected'].append(f"'{t}' trop court (<3 chars)")
                continue

            # === NOUVELLE RÈGLE 3: Composite Trigger Check ===
            # Un trigger snake_case avec 3+ sous-tokens est toujours discriminant
            is_composite = '_' in t and len(t.split('_')) >= 3
            if is_composite:
                composite_trigger_found = True
                trigger_info['composite'] = True
                logger.debug(f"[OSMOSE:C1] Trigger composite détecté: '{t}'")

            # Déterminer si le trigger est "trop fréquent"
            # En batch mode, on utilise la stoplist hybride au lieu du top-50 brut
            is_stopword = t_lower in LINGUISTIC_STOPWORDS
            is_generic = t_lower in GENERIC_DOMAIN_TERMS
            is_top_frequent = t_lower in top_50_tokens

            # ANCIENNE LOGIQUE (trop stricte en batch mode):
            # if t_lower in top_50_tokens: reject
            #
            # NOUVELLE LOGIQUE TWO-TIER:
            # - Stopwords linguistiques → toujours rejetés
            # - Generic domain terms seuls → rejetés (sauf si composite)
            # - Top-50 tokens → OK si composite OU si product pattern OU si compound rare

            if is_stopword:
                audit['rejected'].append(f"'{t}' est un stopword linguistique")
                continue

            if is_generic and not is_composite:
                audit['rejected'].append(f"'{t}' terme générique seul")
                continue

            # En mode batch, on ne rejette pas les top-50 si on a d'autres signaux
            if is_top_frequent and not batch_mode:
                # Mode classique: rejet strict des top-50
                audit['rejected'].append(f"'{t}' trop fréquent (top 50)")
                continue
            elif is_top_frequent and batch_mode:
                # Mode batch: accepter si composite/product/compound
                if not (is_composite or product_match or compound_rare):
                    audit['rejected'].append(f"'{t}' trop fréquent (top 50, no discriminant found)")
                    continue
                # Sinon: on accepte mais on note
                trigger_info['top_frequent_but_accepted'] = True

            # C1c: Matching avec word boundary pour alphanum, substring pour valeurs
            is_value = VALUE_PATTERN.match(t)
            if is_composite:
                # Pour les composites, chercher l'expression avec espaces
                search_expr = t.replace('_', ' ')
                found_in_content = search_expr in doc_lower
            elif is_value:
                # Substring pour valeurs (8%, 1.2, 2-8°C)
                found_in_content = t_lower in doc_lower
            else:
                # Word boundary pour éviter matchs absurdes ("cat" dans "category")
                pattern = rf'\b{re.escape(t_lower)}\b'
                found_in_content = bool(re.search(pattern, doc_lower))

            if not found_in_content:
                audit['rejected'].append(f"'{t}' absent du document")
                continue

            # Calculer fréquence (nombre d'unités contenant ce trigger)
            if is_composite:
                search_expr = t.replace('_', ' ')
                matching_units = [u for u in unit_texts if search_expr in u.lower()]
            elif is_value:
                matching_units = [u for u in unit_texts if t_lower in u.lower()]
            else:
                pattern = rf'\b{re.escape(t_lower)}\b'
                matching_units = [u for u in unit_texts if re.search(pattern, u.lower())]

            freq = len(matching_units)
            freq_rate = freq / total_units if total_units > 0 else 0
            trigger_info['found'] = True
            trigger_info['frequency'] = f"{freq}/{total_units} ({freq_rate:.1%})"
            trigger_info['examples'] = [u[:80] for u in matching_units][:2]
            trigger_info['is_value'] = is_value

            # Déterminer si ce trigger est "discriminant"
            if is_composite:
                rare_trigger_found = True
                trigger_info['rare'] = 'composite'
            elif freq_rate < 0.01:
                rare_trigger_found = True
                trigger_info['rare'] = True
            elif freq_rate < 0.02:
                trigger_info['rare'] = 'semi-rare'
            elif is_value:
                rare_trigger_found = True
                trigger_info['rare'] = 'fallback_value'

            valid_triggers.append(t)
            audit['triggers'][t] = trigger_info

        # === CONTRAT STRUCTUREL (Fix H2) ===
        # Appliquer R1/R2/R3 agnostiques pour éliminer les triggers non-discriminants
        valid_triggers, audit = self._enforce_trigger_contract(
            valid_triggers, audit, concept_name, doc_lower, unit_texts, total_units
        )

        # === VALIDATION FINALE TWO-TIER ===
        audit['valid_count'] = len(valid_triggers)
        audit['rare_found'] = rare_trigger_found
        audit['composite_found'] = composite_trigger_found

        # Vérifier si au moins un trigger semi-rare si pas de rare strict
        has_semi_rare = any(
            info.get('rare') == 'semi-rare'
            for info in audit['triggers'].values()
        )

        # NOUVELLE LOGIQUE D'ACCEPTATION:
        # ACCEPT si: discriminant_trigger OR composite_trigger OR product_pattern OR rare_compound
        has_discriminant = rare_trigger_found or has_semi_rare
        has_composite = composite_trigger_found
        has_product = product_match is not None
        has_rare_compound = compound_rare

        # Au moins 1 trigger valide requis
        if len(valid_triggers) < 1:
            audit['acceptance_reason'] = 'no_valid_triggers'
            return False, audit

        # Décision d'acceptation
        if has_discriminant:
            audit['acceptance_reason'] = 'discriminant_trigger'
            is_valid = True
        elif has_composite:
            audit['acceptance_reason'] = 'composite_trigger'
            is_valid = True
        elif has_product:
            audit['acceptance_reason'] = 'product_pattern'
            is_valid = True
        elif has_rare_compound:
            audit['acceptance_reason'] = 'rare_compound'
            is_valid = True
        elif len(valid_triggers) >= 2:
            # Fallback: si on a au moins 2 triggers valides (même fréquents)
            # en mode batch, on accepte avec un warning
            if batch_mode:
                audit['acceptance_reason'] = 'batch_mode_fallback'
                is_valid = True
                logger.warning(
                    f"[OSMOSE:C1] '{concept_name}' accepté en fallback batch "
                    f"({len(valid_triggers)} triggers, no discriminant)"
                )
            else:
                is_valid = False
        else:
            is_valid = False

        if not is_valid and valid_triggers:
            audit['rejected'].append("Aucun trigger rare (<1%) ni semi-rare (<2%) ni valeur")

        logger.info(
            f"[OSMOSE:C1] {concept.get('name')}: "
            f"{len(valid_triggers)} triggers valides, rare={rare_trigger_found}, "
            f"reason={audit.get('acceptance_reason', 'rejected')}"
        )
        return is_valid, audit

    def _enforce_trigger_contract(
        self,
        valid_triggers: List[str],
        audit: Dict,
        concept_name: str,
        doc_lower: str,
        unit_texts: List[str],
        total_units: int
    ) -> Tuple[List[str], Dict]:
        """
        Contrat structurel agnostique pour les triggers.

        R1: Proportionnalité nom/trigger (≥2 multi-mots si concept ≥2 tokens)
        R2: Mono-mots seulement si acronyme ou rare (<1%)
        R3: Tronquer triggers > 5 tokens → meilleur bigram/trigram interne
        """
        ACRONYM_RE = re.compile(r'^[A-Z0-9./]{2,10}$')

        concept_tokens = concept_name.split()
        concept_token_count = len(concept_tokens)
        modified = False

        # --- R3: Remplacer triggers > 5 tokens par le meilleur n-gram interne ---
        new_triggers = []
        for t in valid_triggers:
            t_tokens = t.split()
            if len(t_tokens) > 5:
                best_ngram = self._best_internal_ngram(t, doc_lower, unit_texts, total_units)
                if best_ngram:
                    new_triggers.append(best_ngram)
                    audit.setdefault('contract_r3_replaced', []).append(
                        {'original': t, 'replacement': best_ngram}
                    )
                    modified = True
                    logger.debug(
                        f"[OSMOSE:Contract:R3] '{t}' → '{best_ngram}' (trigger trop long)"
                    )
                else:
                    # Pas de n-gram trouvé dans le doc, rejeter
                    audit.setdefault('contract_r3_rejected', []).append(t)
                    modified = True
            else:
                new_triggers.append(t)
        valid_triggers = new_triggers

        # --- R2: Filtrer mono-mots non-acronymes et non-rares ---
        filtered_triggers = []
        mono_rejected = []
        for t in valid_triggers:
            t_tokens = t.split()
            if len(t_tokens) == 1:
                # Acronyme → toujours OK
                if ACRONYM_RE.match(t):
                    filtered_triggers.append(t)
                    continue
                # Vérifier rareté (<1% des unités)
                t_lower = t.lower()
                if unit_texts and total_units > 0:
                    pattern = rf'\b{re.escape(t_lower)}\b'
                    matching = sum(1 for u in unit_texts if re.search(pattern, u.lower()))
                    freq_rate = matching / total_units
                    if freq_rate < 0.01:
                        filtered_triggers.append(t)
                        continue
                # Mono-mot fréquent non-acronyme → rejeter
                mono_rejected.append(t)
                modified = True
            else:
                filtered_triggers.append(t)

        if mono_rejected:
            audit['contract_r2_rejected'] = mono_rejected
            logger.debug(
                f"[OSMOSE:Contract:R2] '{concept_name}': mono-mots rejetés: {mono_rejected}"
            )
        valid_triggers = filtered_triggers

        # --- R1: Proportionnalité nom/trigger ---
        # Si concept ≥ 2 tokens, au moins 2 triggers doivent avoir ≥ 2 tokens
        if concept_token_count >= 2:
            multi_word_triggers = [t for t in valid_triggers if len(t.split()) >= 2]
            if len(multi_word_triggers) < 2:
                # Tenter auto-composition (Fix 2 + GF-B)
                composed = self._auto_compose_ngrams(
                    concept_name, doc_lower, unit_texts, total_units,
                    max_ngrams=3
                )
                if composed:
                    # Ajouter les n-grams composés (sans doublons)
                    existing_lower = {t.lower() for t in valid_triggers}
                    added = []
                    for ng in composed:
                        if ng.lower() not in existing_lower:
                            valid_triggers.append(ng)
                            existing_lower.add(ng.lower())
                            added.append(ng)
                    if added:
                        audit['contract_r1_autocomposed'] = added
                        modified = True
                        logger.info(
                            f"[OSMOSE:Contract:R1] '{concept_name}': "
                            f"auto-composé {len(added)} n-grams: {added}"
                        )

                # Re-vérifier R1 après auto-composition
                multi_word_triggers = [t for t in valid_triggers if len(t.split()) >= 2]
                if len(multi_word_triggers) < 2:
                    audit['contract_r1_failed'] = True
                    logger.debug(
                        f"[OSMOSE:Contract:R1] '{concept_name}': "
                        f"seulement {len(multi_word_triggers)} triggers multi-mots "
                        f"(requis: 2)"
                    )

        audit['contract_applied'] = modified
        return valid_triggers, audit

    def _best_internal_ngram(
        self,
        trigger: str,
        doc_lower: str,
        unit_texts: List[str],
        total_units: int
    ) -> Optional[str]:
        """
        Pour un trigger > 5 tokens, trouve le meilleur bigram/trigram interne
        (le plus rare dans le document).
        """
        tokens = trigger.lower().split()
        candidates = []

        # Générer trigrams puis bigrams
        for n in [3, 2]:
            for i in range(len(tokens) - n + 1):
                ngram = ' '.join(tokens[i:i + n])
                # Vérifier présence dans le doc
                if ngram in doc_lower:
                    # Calculer fréquence
                    if unit_texts and total_units > 0:
                        matching = sum(1 for u in unit_texts if ngram in u.lower())
                        freq = matching / total_units
                    else:
                        freq = 0.5  # Fallback conservateur
                    candidates.append((ngram, n, freq))

        if not candidates:
            return None

        # Trier: trigrams d'abord (n décroissant), puis fréquence croissante
        candidates.sort(key=lambda x: (-x[1], x[2]))
        return candidates[0][0]

    def _auto_compose_ngrams(
        self,
        concept_name: str,
        doc_lower: str,
        unit_texts: List[str],
        total_units: int,
        max_ngrams: int = 3
    ) -> List[str]:
        """
        Génère des bigrams + trigrams depuis le nom du concept,
        filtrés par présence doc et rareté.
        100% mécanique, aucun savoir métier.

        Retourne jusqu'à max_ngrams n-grams triés par discriminance.
        """
        tokens = concept_name.lower().split()
        if len(tokens) < 2:
            return []

        candidates = []

        # Générer trigrams ET bigrams contigus
        for n in [3, 2]:
            for i in range(len(tokens) - n + 1):
                ngram = ' '.join(tokens[i:i + n])
                # Vérifier présence dans le document (word boundary)
                pattern = rf'\b{re.escape(ngram)}\b'
                if not re.search(pattern, doc_lower):
                    continue

                # Calculer fréquence doc (nb unités contenant / total)
                if unit_texts and total_units > 0:
                    matching = sum(
                        1 for u in unit_texts
                        if re.search(pattern, u.lower())
                    )
                    freq = matching / total_units
                else:
                    freq = 0.0

                # Filtrer: garder seulement si freq < 5%
                if freq < 0.05:
                    candidates.append((ngram, n, freq))

        if not candidates:
            return []

        # Trier: trigrams d'abord (plus discriminants), puis fréquence croissante
        candidates.sort(key=lambda x: (-x[1], x[2]))

        return [c[0] for c in candidates[:max_ngrams]]

    def _check_compound_rarity(
        self,
        concept_name: str,
        doc_lower: str,
        total_units: int,
        unit_texts: List[str],
        max_occurrences: int = 10
    ) -> bool:
        """
        Vérifie si le nom complet du concept (compound) est rare dans le document.

        Un compound est considéré rare si:
        - Le nom complet (ou un trigram central) apparaît <= max_occurrences fois
        - Cela indique que c'est une expression spécifique, pas du vocabulaire générique

        Args:
            concept_name: Nom complet du concept
            doc_lower: Contenu du document en lowercase
            total_units: Nombre total d'unités
            unit_texts: Liste des textes des unités
            max_occurrences: Seuil de rareté (défaut: 10)

        Returns:
            True si le compound est rare (discriminant)
        """
        name_lower = concept_name.lower().strip()

        # Méthode 1: Vérifier le nom complet
        full_count = doc_lower.count(name_lower)
        if full_count > 0 and full_count <= max_occurrences:
            logger.debug(
                f"[OSMOSE:C1:Compound] '{concept_name}' rare: "
                f"{full_count} occurrences (full match)"
            )
            return True

        # Méthode 2: Pour les noms longs (4+ mots), vérifier le trigram central
        words = name_lower.split()
        if len(words) >= 4:
            # Prendre le trigram central
            mid = len(words) // 2
            trigram = ' '.join(words[mid-1:mid+2])
            trigram_count = doc_lower.count(trigram)
            if trigram_count > 0 and trigram_count <= max_occurrences:
                logger.debug(
                    f"[OSMOSE:C1:Compound] '{concept_name}' rare: "
                    f"trigram '{trigram}' = {trigram_count} occurrences"
                )
                return True

        # Méthode 3: Vérifier dans combien d'unités le nom apparaît
        if unit_texts:
            matching_units = sum(1 for u in unit_texts if name_lower in u.lower())
            unit_rate = matching_units / total_units if total_units > 0 else 0
            # Si présent dans moins de 2% des unités, c'est rare
            if matching_units > 0 and unit_rate < 0.02:
                logger.debug(
                    f"[OSMOSE:C1:Compound] '{concept_name}' rare: "
                    f"{matching_units}/{total_units} units ({unit_rate:.1%})"
                )
                return True

        return False

    def _generate_lex_key(self, name: str) -> str:
        """Génère une clé lexicale normalisée."""
        # Normaliser: lowercase, remplacer espaces, supprimer accents simples
        lex = name.lower().strip()
        lex = re.sub(r'\s+', '_', lex)
        lex = re.sub(r'[^a-z0-9_]', '', lex)
        return lex

    def _apply_frugality(self, concepts: List[Concept], max_count: int) -> List[Concept]:
        """Applique la limite de frugalité en priorisant par rôle."""
        # Trier par rôle: CENTRAL > STANDARD > CONTEXTUAL
        role_order = {ConceptRole.CENTRAL: 0, ConceptRole.STANDARD: 1, ConceptRole.CONTEXTUAL: 2}
        sorted_concepts = sorted(concepts, key=lambda c: role_order.get(c.role, 1))
        return sorted_concepts[:max_count]

    def _fallback_identification(
        self,
        doc_id: str,
        subject_text: str,
        themes: List[Theme],
        content: str
    ) -> Tuple[List[Concept], List[Dict]]:
        """Identification de secours sans LLM."""
        # Extraction naive basée sur la fréquence
        words = re.findall(r'\b[A-Z][a-zA-Z]{3,}\b', content)
        word_freq = {}
        stop_words = {'this', 'that', 'with', 'from', 'have', 'been', 'would', 'should'}

        for word in words:
            word_lower = word.lower()
            if word_lower not in stop_words:
                word_freq[word] = word_freq.get(word, 0) + 1

        # Garder les top termes (frugalité)
        sorted_terms = sorted(word_freq.items(), key=lambda x: -x[1])[:self.MAX_CONCEPTS]

        concepts = []
        default_theme_id = themes[0].theme_id if themes else "theme_default"

        for idx, (term, freq) in enumerate(sorted_terms):
            role = ConceptRole.CENTRAL if idx == 0 else ConceptRole.STANDARD

            concept = Concept(
                concept_id=f"concept_{doc_id}_{idx}",
                theme_id=default_theme_id,
                name=term,
                role=role,
                variants=[],
                lex_key=self._generate_lex_key(term)
            )
            concepts.append(concept)

        # Termes refusés (les moins fréquents)
        refused = [
            {"term": t, "reason": f"Fréquence trop faible ({f})"}
            for t, f in sorted_terms[self.MAX_CONCEPTS:self.MAX_CONCEPTS + 10]
        ] if len(sorted_terms) > self.MAX_CONCEPTS else []

        return concepts, refused

    def _default_system_prompt(self) -> str:
        # COMPACT OUTPUT (ADR: LLM Contract)
        # System prompt minimaliste pour éviter génération verbose
        return """Expert extraction concepts OSMOSE.

FRUGALITÉ STRICTE:
- Max 10 concepts
- Noms courts (2-4 mots)
- Pas de définitions
- Pas de variantes

RÔLES:
- CENTRAL: Cœur du document
- STANDARD: Important secondaire
- CONTEXTUAL: Contexte

FORMAT: JSON compact uniquement, PAS de texte explicatif.
"""

    def _default_user_prompt(self) -> str:
        # COMPACT OUTPUT (ADR: LLM Contract)
        # Sortie minimaliste pour éviter troncature JSON
        # variants/definition seront enrichis en Pass 2 si nécessaire
        return """Identifie les concepts CLÉS de ce document.

SUJET: {subject}
STRUCTURE: {structure}
LANGUE: {language}

THÈMES DISPONIBLES:
{themes}

CONTENU (extrait):
{content}

RÈGLES STRICTES:
- Maximum {max_concepts} concepts
- Chaque concept DOIT être rattaché à un thème existant
- Éviter les termes génériques (système, méthode, processus)

Réponds UNIQUEMENT avec ce JSON COMPACT:
```json
{{
  "concepts": [
    {{"name": "Nom", "role": "CENTRAL", "theme": "Thème"}},
    {{"name": "Nom2", "role": "STANDARD", "theme": "Thème2"}}
  ],
  "refused_terms": [
    {{"term": "Terme", "reason": "Raison"}}
  ]
}}
```"""
