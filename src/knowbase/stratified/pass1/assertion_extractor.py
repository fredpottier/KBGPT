"""
OSMOSE Pipeline V2 - Phase 1.3 Assertion Extractor
===================================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Extraction d'assertions sémantiques:
1. EXTRACT: Identifier les assertions dans le texte
2. CLASSIFY: Typer chaque assertion (DEFINITIONAL, PRESCRIPTIVE, etc.)
3. LINK: Rattacher aux concepts par raisonnement sémantique

Adapté du POC: poc/extractors/semantic_assertion_extractor.py
"""

import json
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import yaml
import uuid
import os

from knowbase.stratified.models import (
    AssertionType,
    Concept,
)

# Volet A: Validation Verbatim (anti-reformulation Qwen)
from knowbase.stratified.pass1.verbatim_validator import (
    validate_raw_assertions,
    BatchValidationStats,
)

# MVP V1 imports for Information-First extraction
from knowbase.stratified.pass1.value_extractor import get_value_extractor, ValueInfo
from knowbase.stratified.claimkey.patterns import get_claimkey_patterns, PatternMatch
from knowbase.stratified.pass1.promotion_policy import (
    get_promotion_policy as get_mvp_v1_promotion_policy,
    PromotionPolicy as PromotionPolicyMVP,
)
from knowbase.stratified.models.information import PromotionStatus

logger = logging.getLogger(__name__)


# ============================================================================
# PROMOTION POLICY
# ============================================================================

class PromotionTier:
    """Niveaux de promotion des assertions."""
    ALWAYS = "always"          # Toujours promouvoir si lié à un concept
    CONDITIONAL = "conditional"  # Promouvoir si confiance >= 0.7
    RARELY = "rarely"          # Promouvoir seulement si confiance >= 0.9
    NEVER = "never"            # Ne jamais promouvoir en Information


# Politique de promotion par type d'assertion
PROMOTION_POLICY: Dict[AssertionType, str] = {
    AssertionType.DEFINITIONAL: PromotionTier.ALWAYS,     # Définitions = cœur conceptuel
    AssertionType.PRESCRIPTIVE: PromotionTier.ALWAYS,     # Règles normatives = haute valeur
    AssertionType.CAUSAL: PromotionTier.ALWAYS,           # Relations causales = structurantes
    AssertionType.FACTUAL: PromotionTier.CONDITIONAL,     # Faits = dépend du contexte
    AssertionType.CONDITIONAL: PromotionTier.CONDITIONAL, # Conditions = utiles si précises
    AssertionType.PERMISSIVE: PromotionTier.CONDITIONAL,  # Options = utiles si spécifiques
    AssertionType.COMPARATIVE: PromotionTier.RARELY,      # Comparaisons = souvent locales
    AssertionType.PROCEDURAL: PromotionTier.NEVER,        # Procédures = non conceptuelles
}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class RawAssertion:
    """Assertion brute extraite du texte (avant ancrage DocItem)."""
    assertion_id: str
    text: str
    assertion_type: AssertionType
    chunk_id: str  # ID du chunk source (sera converti en docitem_id)
    start_char: int  # Position dans le chunk
    end_char: int
    confidence: float
    language: str = "fr"

    def __post_init__(self):
        if not self.assertion_id:
            self.assertion_id = f"assert_{uuid.uuid4().hex[:8]}"


@dataclass
class ConceptLink:
    """Lien sémantique entre une assertion et un concept."""
    assertion_id: str
    concept_id: str
    link_type: str  # defines, describes, constrains, enables, conditions, causes
    justification: str
    confidence: float


@dataclass
class PromotionResult:
    """Résultat du filtrage par Promotion Policy."""
    promotable: List[RawAssertion] = field(default_factory=list)
    abstained: List[Tuple[RawAssertion, str]] = field(default_factory=list)  # (assertion, reason)
    stats: Dict[str, int] = field(default_factory=dict)


@dataclass
class EnrichedAssertion:
    """
    Assertion enrichie avec les capacités MVP V1.

    Ajoute à RawAssertion:
    - value: Valeur extraite (percent, version, number, boolean, enum)
    - claimkey_match: ClaimKey inféré par pattern Level A
    - promotion_status: Statut de promotion MVP V1
    - promotion_reason: Raison de la décision de promotion
    """
    assertion: RawAssertion
    value: Optional[ValueInfo] = None
    claimkey_match: Optional[PatternMatch] = None
    promotion_status: Optional[PromotionStatus] = None
    promotion_reason: str = ""

    @property
    def has_claimkey(self) -> bool:
        """True si un ClaimKey a été inféré."""
        return self.claimkey_match is not None

    @property
    def has_value(self) -> bool:
        """True si une valeur a été extraite."""
        return self.value is not None

    @property
    def is_promoted(self) -> bool:
        """True si l'assertion est promue (LINKED ou UNLINKED)."""
        return self.promotion_status in [
            PromotionStatus.PROMOTED_LINKED,
            PromotionStatus.PROMOTED_UNLINKED
        ]


@dataclass
class MVPV1EnrichmentResult:
    """Résultat de l'enrichissement MVP V1."""
    enriched: List[EnrichedAssertion] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


# ============================================================================
# EXTRACTOR
# ============================================================================

class AssertionExtractorV2:
    """
    Extracteur d'assertions sémantiques pour Pipeline V2.

    Pipeline:
    1. Segmenter le texte en assertions candidates
    2. Classifier chaque assertion (type, confiance)
    3. Filtrer par Promotion Policy
    4. Lier sémantiquement aux concepts

    IMPORTANT: Retourne des assertions avec chunk_id.
    La conversion chunk_id → docitem_id est faite par AnchorResolver (Phase 1.3b).
    """

    # Parallélisation: nombre de workers par défaut
    DEFAULT_MAX_WORKERS = 8

    def __init__(
        self,
        llm_client=None,
        prompts_path: Optional[Path] = None,
        allow_fallback: bool = False,
        strict_promotion: bool = True,
        max_workers: Optional[int] = None
    ):
        """
        Args:
            llm_client: Client LLM compatible (generate method)
            prompts_path: Chemin vers prompts YAML
            allow_fallback: Si True, autorise le fallback heuristique (test only)
            strict_promotion: Si True, seules ALWAYS sont promues. Si False, inclut CONDITIONAL.
            max_workers: Nombre de workers parallèles (défaut: 8 ou OSMOSE_LLM_WORKERS)
        """
        self.llm_client = llm_client
        self.prompts = self._load_prompts(prompts_path)
        self.allow_fallback = allow_fallback
        self.strict_promotion = strict_promotion
        self.max_workers = max_workers or int(os.environ.get("OSMOSE_LLM_WORKERS", self.DEFAULT_MAX_WORKERS))

    def _load_prompts(self, prompts_path: Optional[Path]) -> Dict:
        """Charge les prompts depuis le fichier YAML."""
        if prompts_path is None:
            prompts_path = Path(__file__).parent.parent / "prompts" / "pass1_prompts.yaml"

        if not prompts_path.exists():
            return {}

        with open(prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    # =========================================================================
    # ÉTAPE 1: EXTRACTION DES ASSERTIONS
    # =========================================================================

    def extract_assertions(
        self,
        chunks: Dict[str, str],
        doc_language: Optional[str] = None
    ) -> List[RawAssertion]:
        """
        Extrait toutes les assertions des chunks EN PARALLÈLE.

        Args:
            chunks: Dict chunk_id -> texte
            doc_language: Langue du document

        Returns:
            Liste de RawAssertion avec positions dans les chunks
        """
        if not self.llm_client and not self.allow_fallback:
            raise RuntimeError(
                "LLM non disponible et fallback non autorisé. "
                "Utilisez allow_fallback=True uniquement pour les tests."
            )

        # Filtrer les chunks trop courts
        valid_chunks = {
            chunk_id: text
            for chunk_id, text in chunks.items()
            if len(text.strip()) >= 50
        }

        if not valid_chunks:
            return []

        all_assertions = []
        errors_count = 0

        logger.info(
            f"[OSMOSE:Pass1:1.3] Extraction parallèle: {len(valid_chunks)} chunks, "
            f"{self.max_workers} workers"
        )

        # Extraction parallèle avec ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Soumettre tous les chunks
            future_to_chunk = {
                executor.submit(
                    self._extract_from_chunk, chunk_id, text, doc_language
                ): chunk_id
                for chunk_id, text in valid_chunks.items()
            }

            # Collecter les résultats au fur et à mesure
            for future in as_completed(future_to_chunk):
                chunk_id = future_to_chunk[future]
                try:
                    chunk_assertions = future.result()
                    all_assertions.extend(chunk_assertions)
                except Exception as e:
                    errors_count += 1
                    logger.warning(f"[OSMOSE:Pass1:1.3] Erreur chunk {chunk_id}: {e}")

        if errors_count > 0:
            logger.warning(f"[OSMOSE:Pass1:1.3] {errors_count} chunks en erreur sur {len(valid_chunks)}")

        logger.info(f"[OSMOSE:Pass1:1.3] {len(all_assertions)} assertions extraites")
        return all_assertions

    def extract_and_validate_assertions(
        self,
        chunks: Dict[str, str],
        doc_language: Optional[str] = None
    ) -> Tuple[List[RawAssertion], List[Tuple[RawAssertion, str]], BatchValidationStats]:
        """
        Extrait les assertions ET applique la validation verbatim (Volet A).

        Cette méthode combine l'extraction et la validation pour:
        1. Extraire les assertions via LLM
        2. Valider que chaque assertion est une copie verbatim du texte source
        3. Rejeter (ABSTAIN) les assertions reformulées par le LLM

        Args:
            chunks: Dict chunk_id -> texte source
            doc_language: Langue du document

        Returns:
            (valid_assertions, abstained_with_reason, validation_stats)
        """
        # Étape 1: Extraction classique
        all_assertions = self.extract_assertions(chunks, doc_language)

        if not all_assertions:
            return [], [], BatchValidationStats()

        # Étape 2: Validation verbatim (Volet A)
        valid, abstained, stats = validate_raw_assertions(all_assertions, chunks)

        # Log si taux de reformulation élevé
        if stats.total > 0 and stats.reformulation_rate > 0.10:
            logger.warning(
                f"[OSMOSE:Pass1:1.3:VERBATIM] Taux de reformulation: {stats.reformulation_rate:.1%} "
                f"({stats.abstain_not_substring}/{stats.total} assertions). "
                f"Le LLM ne respecte pas l'instruction 'texte EXACT'."
            )

        return valid, abstained, stats

    def _extract_from_chunk(
        self,
        chunk_id: str,
        text: str,
        doc_language: Optional[str]
    ) -> List[RawAssertion]:
        """Extrait les assertions d'un chunk."""
        if self.llm_client:
            return self._extract_llm(chunk_id, text, doc_language)
        else:
            return self._extract_heuristic(chunk_id, text)

    def _extract_llm(
        self,
        chunk_id: str,
        text: str,
        doc_language: Optional[str]
    ) -> List[RawAssertion]:
        """Extraction via LLM."""
        prompt_config = self.prompts.get("assertion_extraction", {})
        system_prompt = prompt_config.get("system", self._default_extraction_system())
        user_template = prompt_config.get("user", self._default_extraction_user())

        text_limited = text[:2000] if len(text) > 2000 else text

        user_prompt = user_template.format(
            chunk_id=chunk_id,
            text=text_limited,
            language_hint=doc_language or "auto-detect"
        )

        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2000
            )
            return self._parse_extraction_response(response, chunk_id, text)
        except Exception as e:
            logger.warning(f"Extraction LLM échouée pour {chunk_id}: {e}")
            return self._extract_heuristic(chunk_id, text)

    def _extract_heuristic(self, chunk_id: str, text: str) -> List[RawAssertion]:
        """Extraction heuristique sans LLM."""
        assertions = []
        sentences = re.split(r'(?<=[.!?])\s+', text)

        current_pos = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:
                current_pos = text.find(sentence, current_pos) + len(sentence)
                continue

            assertion_type = self._detect_type_heuristic(sentence)
            language = self._detect_language_heuristic(sentence)

            start = text.find(sentence, current_pos)
            if start == -1:
                start = current_pos
            end = start + len(sentence)
            current_pos = end

            assertions.append(RawAssertion(
                assertion_id=f"assert_{uuid.uuid4().hex[:8]}",
                text=sentence,
                assertion_type=assertion_type,
                chunk_id=chunk_id,
                start_char=start,
                end_char=end,
                confidence=0.5,
                language=language
            ))

        return assertions

    def _detect_type_heuristic(self, sentence: str) -> AssertionType:
        """Détecte le type d'assertion par patterns."""
        s = sentence.lower()

        if any(p in s for p in ['is defined as', 'refers to', 'means', 'est défini', 'désigne']):
            return AssertionType.DEFINITIONAL
        if any(p in s for p in ['must', 'shall', 'required', 'doit', 'obligatoire', 'mandatory']):
            return AssertionType.PRESCRIPTIVE
        if any(p in s for p in ['may', 'can', 'possible', 'peut', 'option', 'allowed']):
            return AssertionType.PERMISSIVE
        if any(p in s for p in ['if', 'when', 'unless', 'si', 'lorsque', 'provided that']):
            return AssertionType.CONDITIONAL
        if any(p in s for p in ['because', 'therefore', 'leads to', 'results in', 'car', 'donc']):
            return AssertionType.CAUSAL
        if any(p in s for p in ['step', 'first', 'then', 'finally', 'étape', 'ensuite']):
            return AssertionType.PROCEDURAL

        return AssertionType.FACTUAL

    def _detect_language_heuristic(self, text: str) -> str:
        """Détecte la langue par heuristique."""
        fr_words = ['le', 'la', 'les', 'de', 'du', 'des', 'est', 'sont', 'pour', 'avec', 'dans']
        en_words = ['the', 'is', 'are', 'for', 'with', 'in', 'to', 'of', 'and', 'that']

        words = text.lower().split()
        fr_count = sum(1 for w in words if w in fr_words)
        en_count = sum(1 for w in words if w in en_words)

        return "fr" if fr_count > en_count else "en"

    # =========================================================================
    # ÉTAPE 2: FILTRAGE PAR PROMOTION POLICY
    # =========================================================================

    def _is_meta_description(self, text: str) -> bool:
        """
        Détecte si le texte est une méta-description (décrit la page, pas l'info).

        Utilise les patterns du promotion_engine (spec V1 complète EN+FR).

        Ces assertions n'apportent pas d'information tangible et doivent être filtrées.
        Exemples filtrés:
        - "La page présente un modèle de déploiement"
        - "This diagram shows the architecture"
        """
        from knowbase.stratified.pass1.promotion_engine import is_meta_pattern
        return is_meta_pattern(text)

    def _is_fragment(self, text: str) -> bool:
        """
        Détecte si le texte est un fragment (non-assertion).

        ChatGPT Priority 2: Filtre "assertion minimale".
        Exemples filtrés:
        - "ISO 27001" (nom seul)
        - "VPC Peering." (fragment)
        - Texte sans verbe
        """
        from knowbase.stratified.pass1.promotion_engine import is_fragment
        return is_fragment(text)

    def filter_by_promotion_policy(
        self,
        assertions: List[RawAssertion]
    ) -> PromotionResult:
        """
        Filtre les assertions selon la Promotion Policy.

        Seules les assertions de type ALWAYS (ou CONDITIONAL si non-strict)
        peuvent devenir des Information.

        Filtre également les méta-descriptions (ex: "La page présente...")
        qui n'apportent pas d'information tangible.
        """
        result = PromotionResult()
        result.stats = {
            "total": len(assertions),
            "always": 0,
            "conditional": 0,
            "rarely": 0,
            "never": 0,
            "promoted": 0,
            "meta_filtered": 0,
            "fragment_filtered": 0  # ChatGPT Priority 2
        }

        for assertion in assertions:
            # FILTRE 1: Méta-descriptions (ex: "La page présente...")
            if self._is_meta_description(assertion.text):
                result.stats["meta_filtered"] += 1
                result.abstained.append((assertion, "meta_description"))
                continue

            # FILTRE 2: Fragments (ChatGPT Priority 2 - assertion minimale)
            if self._is_fragment(assertion.text):
                result.stats["fragment_filtered"] += 1
                result.abstained.append((assertion, "fragment"))
                continue

            tier = PROMOTION_POLICY.get(assertion.assertion_type, PromotionTier.RARELY)

            if tier == PromotionTier.ALWAYS:
                result.stats["always"] += 1
                result.promotable.append(assertion)
                result.stats["promoted"] += 1

            elif tier == PromotionTier.CONDITIONAL:
                result.stats["conditional"] += 1
                if not self.strict_promotion and assertion.confidence >= 0.7:
                    result.promotable.append(assertion)
                    result.stats["promoted"] += 1
                else:
                    result.abstained.append((assertion, "low_confidence"))

            elif tier == PromotionTier.RARELY:
                result.stats["rarely"] += 1
                if not self.strict_promotion and assertion.confidence >= 0.9:
                    result.promotable.append(assertion)
                    result.stats["promoted"] += 1
                else:
                    result.abstained.append((assertion, "policy_rejected"))

            else:  # NEVER
                result.stats["never"] += 1
                result.abstained.append((assertion, "policy_rejected"))

        logger.info(
            f"[OSMOSE:Pass1:1.3] Promotion Policy: "
            f"{result.stats['always']} ALWAYS, "
            f"{result.stats['conditional']} CONDITIONAL, "
            f"{result.stats['never']} PROCEDURAL (exclues), "
            f"{result.stats['meta_filtered']} meta filtrées, "
            f"{result.stats['fragment_filtered']} fragments filtrés → "
            f"{result.stats['promoted']} promues"
        )

        return result

    # =========================================================================
    # ÉTAPE 3: LIAISON SÉMANTIQUE
    # =========================================================================

    # Taille de batch pour le semantic linking
    LINKING_BATCH_SIZE = 30

    def link_to_concepts(
        self,
        assertions: List[RawAssertion],
        concepts: List[Concept]
    ) -> List[ConceptLink]:
        """
        Établit les liens sémantiques assertions ↔ concepts.

        IMPORTANT: Ce n'est PAS un matching lexical.
        Le LLM raisonne sur le sens pour déterminer les liens.

        Si plus de LINKING_BATCH_SIZE assertions, les traite par batch en parallèle.
        """
        if not assertions or not concepts:
            return []

        if self.llm_client:
            return self._link_via_llm(assertions, concepts)
        else:
            return self._link_heuristic(assertions, concepts)

    def _link_via_llm(
        self,
        assertions: List[RawAssertion],
        concepts: List[Concept]
    ) -> List[ConceptLink]:
        """
        Linking via raisonnement LLM avec batching parallèle.

        Si plus de LINKING_BATCH_SIZE assertions, les découpe en batches
        et les traite en parallèle.
        """
        # Si peu d'assertions, traitement direct
        if len(assertions) <= self.LINKING_BATCH_SIZE:
            return self._link_batch(assertions, concepts)

        # Sinon, batching parallèle
        batches = [
            assertions[i:i + self.LINKING_BATCH_SIZE]
            for i in range(0, len(assertions), self.LINKING_BATCH_SIZE)
        ]

        logger.info(
            f"[OSMOSE:Pass1:1.4] Linking parallèle: {len(assertions)} assertions → "
            f"{len(batches)} batches, {self.max_workers} workers"
        )

        all_links = []
        errors_count = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_batch = {
                executor.submit(self._link_batch, batch, concepts): idx
                for idx, batch in enumerate(batches)
            }

            for future in as_completed(future_to_batch):
                batch_idx = future_to_batch[future]
                try:
                    batch_links = future.result()
                    all_links.extend(batch_links)
                except Exception as e:
                    errors_count += 1
                    logger.warning(f"[OSMOSE:Pass1:1.4] Erreur batch {batch_idx}: {e}")

        if errors_count > 0:
            logger.warning(f"[OSMOSE:Pass1:1.4] {errors_count} batches en erreur sur {len(batches)}")

        logger.info(f"[OSMOSE:Pass1:1.4] {len(all_links)} liens sémantiques établis")
        return all_links

    def _link_batch(
        self,
        assertions: List[RawAssertion],
        concepts: List[Concept]
    ) -> List[ConceptLink]:
        """Traite un batch d'assertions pour le linking."""
        prompt_config = self.prompts.get("semantic_linking", {})
        system_prompt = prompt_config.get("system", self._default_linking_system())
        user_template = prompt_config.get("user", self._default_linking_user())

        assertions_text = self._format_assertions_for_prompt(assertions)
        concepts_text = self._format_concepts_for_prompt(concepts)

        user_prompt = user_template.format(
            assertions=assertions_text,
            concepts=concepts_text
        )

        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=3000
            )
            return self._parse_links_response(response, assertions, concepts)
        except Exception as e:
            logger.warning(f"Linking LLM échoué: {e}")
            return self._link_heuristic(assertions, concepts)

    def _link_heuristic(
        self,
        assertions: List[RawAssertion],
        concepts: List[Concept]
    ) -> List[ConceptLink]:
        """Linking heuristique (fallback)."""
        links = []

        for assertion in assertions:
            text_lower = assertion.text.lower()

            for concept in concepts:
                variants = self._get_concept_variants(concept)

                for variant in variants:
                    if variant.lower() in text_lower:
                        link_type = self._infer_link_type(assertion.assertion_type)
                        links.append(ConceptLink(
                            assertion_id=assertion.assertion_id,
                            concept_id=concept.concept_id,
                            link_type=link_type,
                            justification=f"Mention de '{variant}' dans l'assertion",
                            confidence=0.6
                        ))
                        break

        logger.info(f"[OSMOSE:Pass1:1.3] {len(links)} liens sémantiques établis")
        return links

    def _get_concept_variants(self, concept: Concept) -> List[str]:
        """Génère les variantes d'un concept pour matching."""
        variants = [concept.name]
        variants.extend(concept.variants)

        # Ajouter variations simples
        variants.append(concept.name.lower())
        variants.append(concept.name.upper())

        # Acronyme possible
        words = concept.name.split()
        if len(words) > 1:
            acronym = ''.join(w[0].upper() for w in words if w)
            variants.append(acronym)

        return list(set(variants))

    def _infer_link_type(self, assertion_type: AssertionType) -> str:
        """Infère le type de lien depuis le type d'assertion."""
        mapping = {
            AssertionType.DEFINITIONAL: "defines",
            AssertionType.FACTUAL: "describes",
            AssertionType.PRESCRIPTIVE: "constrains",
            AssertionType.PERMISSIVE: "enables",
            AssertionType.CONDITIONAL: "conditions",
            AssertionType.CAUSAL: "causes",
            AssertionType.COMPARATIVE: "compares",
            AssertionType.PROCEDURAL: "involves",
        }
        return mapping.get(assertion_type, "relates_to")

    def _format_assertions_for_prompt(self, assertions: List[RawAssertion]) -> str:
        """Formate les assertions pour le prompt (batch déjà limité par _link_batch)."""
        lines = []
        for a in assertions:
            lines.append(f"[{a.assertion_id}] ({a.language}) {a.text[:200]}")
        return "\n".join(lines)

    def _format_concepts_for_prompt(self, concepts: List[Concept]) -> str:
        """Formate les concepts pour le prompt."""
        lines = []
        for c in concepts[:20]:
            lines.append(f"- {c.concept_id}: {c.name} ({c.role.value})")
        return "\n".join(lines)

    def _parse_extraction_response(
        self,
        response: str,
        chunk_id: str,
        original_text: str
    ) -> List[RawAssertion]:
        """Parse la réponse JSON des assertions."""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            assertions = []

            type_mapping = {
                "definitional": AssertionType.DEFINITIONAL,
                "factual": AssertionType.FACTUAL,
                "prescriptive": AssertionType.PRESCRIPTIVE,
                "permissive": AssertionType.PERMISSIVE,
                "conditional": AssertionType.CONDITIONAL,
                "causal": AssertionType.CAUSAL,
                "comparative": AssertionType.COMPARATIVE,
                "procedural": AssertionType.PROCEDURAL,
            }

            for a_data in data.get("assertions", []):
                type_str = a_data.get("type", "factual").lower()
                assertion_type = type_mapping.get(type_str, AssertionType.FACTUAL)

                assertions.append(RawAssertion(
                    assertion_id=f"assert_{uuid.uuid4().hex[:8]}",
                    text=a_data.get("text", ""),
                    assertion_type=assertion_type,
                    chunk_id=chunk_id,
                    start_char=a_data.get("start_char", 0),
                    end_char=a_data.get("end_char", 0),
                    confidence=a_data.get("confidence", 0.8),
                    language=a_data.get("language", "en")
                ))

            return assertions

        except json.JSONDecodeError as e:
            logger.warning(f"Parse JSON échoué: {e}")
            return self._extract_heuristic(chunk_id, original_text)

    def _parse_links_response(
        self,
        response: str,
        assertions: List[RawAssertion],
        concepts: List[Concept]
    ) -> List[ConceptLink]:
        """Parse la réponse JSON des liens."""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            links = []

            assertion_map = {a.assertion_id: a for a in assertions}
            concept_ids = {c.concept_id for c in concepts}

            for l_data in data.get("links", []):
                assertion_id = l_data.get("assertion_id", "")
                concept_id = l_data.get("concept_id", "")

                if assertion_id not in assertion_map:
                    continue
                if concept_id not in concept_ids:
                    continue

                links.append(ConceptLink(
                    assertion_id=assertion_id,
                    concept_id=concept_id,
                    link_type=l_data.get("link_type", "relates_to"),
                    justification=l_data.get("justification", ""),
                    confidence=l_data.get("confidence", 0.8)
                ))

            return links

        except json.JSONDecodeError as e:
            logger.warning(f"Parse links JSON échoué: {e}")
            return self._link_heuristic(assertions, concepts)

    # =========================================================================
    # PROMPTS PAR DÉFAUT
    # =========================================================================

    def _default_extraction_system(self) -> str:
        return """Tu es un expert en extraction d'assertions pour OSMOSE.
Une ASSERTION est une phrase qui porte une connaissance:
- Définition (ce qu'est quelque chose)
- Fait (information vérifiable)
- Règle/Contrainte (obligation, interdiction)
- Possibilité (option, permission)
- Condition (si... alors...)
- Cause/Conséquence (A entraîne B)

Tu dois identifier les assertions et leur type dans le texte.
Retourne les positions EXACTES (start_char, end_char)."""

    def _default_extraction_user(self) -> str:
        return """Extrait les assertions de ce texte.

CHUNK_ID: {chunk_id}
LANGUE: {language_hint}

TEXTE:
{text}

Réponds avec ce JSON:
```json
{{
  "assertions": [
    {{
      "text": "Le texte exact de l'assertion",
      "type": "definitional|factual|prescriptive|permissive|conditional|causal|procedural",
      "start_char": 145,
      "end_char": 287,
      "confidence": 0.9,
      "language": "fr"
    }}
  ]
}}
```"""

    def _default_linking_system(self) -> str:
        return """Tu es un expert en raisonnement sémantique pour OSMOSE.
Tu dois déterminer quelles ASSERTIONS apportent de la connaissance sur quels CONCEPTS.

IMPORTANT - Ce n'est PAS un matching lexical:
- Une assertion peut concerner un concept sans le mentionner explicitement
- Un concept en français peut être lié à une assertion en anglais
- Le lien doit être SÉMANTIQUE (le sens), pas lexical (les mots)

Types de liens:
- defines: L'assertion définit le concept
- describes: L'assertion décrit une propriété du concept
- constrains: L'assertion impose une contrainte
- enables: L'assertion dit ce que le concept permet
- conditions: L'assertion spécifie une condition
- causes: L'assertion décrit un effet"""

    def _default_linking_user(self) -> str:
        return """Établis les liens sémantiques.

ASSERTIONS:
{assertions}

CONCEPTS:
{concepts}

Réponds avec ce JSON:
```json
{{
  "links": [
    {{
      "assertion_id": "assert_abc123",
      "concept_id": "concept_xyz",
      "link_type": "defines|describes|constrains|enables|conditions|causes",
      "justification": "Pourquoi cette assertion concerne ce concept",
      "confidence": 0.85
    }}
  ]
}}
```"""

    # =========================================================================
    # MVP V1: ENRICHISSEMENT INFORMATION-FIRST
    # =========================================================================

    def enrich_with_mvp_v1(
        self,
        assertions: List[RawAssertion],
        context: Optional[Dict] = None
    ) -> MVPV1EnrichmentResult:
        """
        Enrichit les assertions avec les capacités MVP V1 (Usage B).

        Pour chaque assertion:
        1. Extrait les valeurs bornées (percent, version, number, boolean, enum)
        2. Infère le ClaimKey par pattern Level A (sans LLM)
        3. Évalue la promotion selon la politique Information-First

        Args:
            assertions: Liste d'assertions brutes
            context: Contexte optionnel (product, theme, etc.) pour l'inférence ClaimKey

        Returns:
            MVPV1EnrichmentResult avec assertions enrichies et statistiques
        """
        if context is None:
            context = {}

        value_extractor = get_value_extractor()
        claimkey_patterns = get_claimkey_patterns()
        promotion_policy = get_mvp_v1_promotion_policy()

        result = MVPV1EnrichmentResult()
        result.stats = {
            "total": len(assertions),
            "with_value": 0,
            "with_claimkey": 0,
            "promoted_linked": 0,
            "promoted_unlinked": 0,
            "rejected": 0,
        }

        for assertion in assertions:
            # 1. Extraction de valeur
            value = value_extractor.extract(assertion.text)
            if value:
                result.stats["with_value"] += 1

            # 2. Inférence ClaimKey Level A
            claimkey_match = claimkey_patterns.infer_claimkey(assertion.text, context)
            if claimkey_match:
                result.stats["with_claimkey"] += 1

            # 3. Évaluation promotion MVP V1
            promotion_input = {
                "text": assertion.text,
                "type": assertion.assertion_type.value if assertion.assertion_type else None,
                "rhetorical_role": self._map_assertion_type_to_rhetorical_role(assertion.assertion_type),
                "value": value.to_dict() if value and hasattr(value, 'to_dict') else ({"kind": value.kind.value} if value else None),
            }
            status, reason = promotion_policy.evaluate(promotion_input)

            if status == PromotionStatus.PROMOTED_LINKED:
                result.stats["promoted_linked"] += 1
            elif status == PromotionStatus.PROMOTED_UNLINKED:
                result.stats["promoted_unlinked"] += 1
            else:
                result.stats["rejected"] += 1

            # Créer l'assertion enrichie
            enriched = EnrichedAssertion(
                assertion=assertion,
                value=value,
                claimkey_match=claimkey_match,
                promotion_status=status,
                promotion_reason=reason
            )
            result.enriched.append(enriched)

        # Log statistiques
        logger.info(
            f"[OSMOSE:MVP_V1] Enrichissement: {result.stats['total']} assertions → "
            f"{result.stats['with_value']} avec valeur, "
            f"{result.stats['with_claimkey']} avec ClaimKey, "
            f"{result.stats['promoted_linked']} LINKED, "
            f"{result.stats['promoted_unlinked']} UNLINKED, "
            f"{result.stats['rejected']} rejetées"
        )

        # INVARIANT 1: Alerte si UNLINKED > 10%
        if result.stats["total"] > 0:
            unlinked_ratio = result.stats["promoted_unlinked"] / result.stats["total"]
            if unlinked_ratio > 0.10:
                logger.warning(
                    f"[OSMOSE:MVP_V1:INVARIANT_1] ALERTE: {unlinked_ratio:.1%} assertions UNLINKED "
                    f"(> 10%). Patterns ClaimKey à enrichir."
                )

        return result

    def _map_assertion_type_to_rhetorical_role(self, assertion_type: AssertionType) -> str:
        """Mappe le type d'assertion vers un rôle rhétorique MVP V1."""
        mapping = {
            AssertionType.DEFINITIONAL: "definition",
            AssertionType.FACTUAL: "fact",
            AssertionType.PRESCRIPTIVE: "instruction",
            AssertionType.PERMISSIVE: "claim",
            AssertionType.CONDITIONAL: "claim",
            AssertionType.CAUSAL: "claim",
            AssertionType.COMPARATIVE: "claim",
            AssertionType.PROCEDURAL: "example",
        }
        return mapping.get(assertion_type, "claim")

    # =========================================================================
    # MODE POINTER: EXTRACTION ANTI-REFORMULATION
    # =========================================================================

    def extract_assertions_pointer_mode(
        self,
        docitem_id: str,
        units_text: str,
        doc_language: Optional[str] = None,
    ) -> List[Dict]:
        """
        Extrait les assertions en mode pointer (anti-reformulation).

        Le LLM pointe vers des unités (U1, U2...) au lieu de copier le texte.
        La reconstruction du texte verbatim est faite côté code depuis l'index.

        Args:
            docitem_id: ID du DocItem
            units_text: Texte formaté avec unités numérotées (U1: text, U2: text...)
            doc_language: Langue du document

        Returns:
            Liste de dicts avec keys: label, type, unit_id, confidence, value_kind
        """
        if not self.llm_client and not self.allow_fallback:
            raise RuntimeError(
                "LLM non disponible et fallback non autorisé pour mode pointer."
            )

        prompt_config = self.prompts.get("pointer_concept_extraction", {})
        system_prompt = prompt_config.get("system", self._default_pointer_system())
        user_template = prompt_config.get("user", self._default_pointer_user())

        user_prompt = user_template.format(
            docitem_id=docitem_id,
            language=doc_language or "auto-detect",
            units_text=units_text[:3000],  # Limite pour éviter troncature
        )

        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2000
            )
            return self._parse_pointer_response(response)
        except Exception as e:
            logger.warning(f"[OSMOSE:Pass1:POINTER] Extraction LLM échouée pour {docitem_id}: {e}")
            return []

    def _parse_pointer_response(self, response: str) -> List[Dict]:
        """Parse la réponse JSON de l'extraction pointer."""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            concepts = data.get("concepts", [])

            # Valider et filtrer
            valid_concepts = []
            for c in concepts:
                unit_id = c.get("unit_id", "")
                # Valider format unit_id (U1, U2, etc.)
                if unit_id and unit_id.startswith("U") and unit_id[1:].isdigit():
                    valid_concepts.append({
                        "label": c.get("label", ""),
                        "type": c.get("type", "FACTUAL").upper(),
                        "unit_id": unit_id,
                        "confidence": float(c.get("confidence", 0.8)),
                        "value_kind": c.get("value_kind"),
                    })
                else:
                    logger.debug(f"[OSMOSE:Pass1:POINTER] Invalid unit_id ignoré: {unit_id}")

            return valid_concepts

        except json.JSONDecodeError as e:
            logger.warning(f"[OSMOSE:Pass1:POINTER] JSON parse error: {e}")
            return []

    def _default_pointer_system(self) -> str:
        """Prompt système par défaut pour extraction pointer."""
        return """Tu es un expert en extraction de concepts pour OSMOSE.

MÉTHODE POINTER-BASED:
Le texte est découpé en unités numérotées (U1, U2, U3...).
Tu dois POINTER vers l'unité qui contient le concept, PAS copier le texte.

TYPES DE CONCEPTS:
- PRESCRIPTIVE: Obligation, règle ("must", "shall", "required", "doit", "obligatoire")
- DEFINITIONAL: Définition, explication ("is defined as", "refers to")
- FACTUAL: Information vérifiable, fait technique
- PERMISSIVE: Option, possibilité ("may", "can", "peut")

RÈGLES CRITIQUES:
1. Retourne UNIQUEMENT le numéro d'unité (U1, U2...), JAMAIS le texte
2. NE PROPOSE UN CONCEPT QUE SI TU PEUX POINTER UNE UNITÉ
3. SI AUCUNE UNITÉ NE CORRESPOND, NE RETOURNE PAS LE CONCEPT
4. La confidence reflète ta certitude sur le type
5. value_kind si applicable: "version", "percentage", "size", "number", "duration"

FORMAT JSON STRICT."""

    def _default_pointer_user(self) -> str:
        """Prompt utilisateur par défaut pour extraction pointer."""
        return """Extrais les concepts de ce texte avec unités numérotées.

DOCITEM_ID: {docitem_id}
LANGUE: {language}

TEXTE AVEC UNITÉS:
{units_text}

INSTRUCTIONS:
- Indique UNIQUEMENT le numéro d'unité (U1, U2...).
- NE RECOPIE PAS le texte.
- Si aucune unité ne correspond à un concept, n'inclus pas ce concept.

Réponds UNIQUEMENT avec ce JSON:
```json
{{
  "concepts": [
    {{
      "label": "Nom court du concept (2-5 mots)",
      "type": "PRESCRIPTIVE|DEFINITIONAL|FACTUAL|PERMISSIVE",
      "unit_id": "U1",
      "confidence": 0.9,
      "value_kind": "version|percentage|size|number|duration|null"
    }}
  ]
}}
```"""
