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

import numpy as np

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

# V2.1: Pattern valeur pour validation triggers (C1c)
VALUE_PATTERN = re.compile(r'^\d+(\.\d+)*[%°]?[CFc]?$|^\d+[:\-]\d+$')


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
    """
    Lien sémantique entre une assertion et UN concept (format legacy).

    Note: Pour le multi-concept linking V2.1, voir MultiConceptLink.
    """
    assertion_id: str
    concept_id: str
    link_type: str  # defines, describes, constrains, enables, conditions, causes
    justification: str
    confidence: float


@dataclass
class MultiConceptLink:
    """
    Lien sémantique entre une assertion et PLUSIEURS concepts (V2.1).

    Une assertion peut informer 1-5 concepts avec des types de liens différents.
    """
    assertion_id: str
    concept_ids: List[str]  # PLUSIEURS concepts (1-5)
    link_types: Dict[str, str]  # {concept_id → link_type}
    justifications: Dict[str, str]  # {concept_id → justification}
    confidences: Dict[str, float]  # {concept_id → confidence}

    @property
    def primary_concept_id(self) -> str:
        """Concept principal (plus haute confiance)."""
        if not self.concept_ids:
            return ""
        return max(self.concept_ids, key=lambda c: self.confidences.get(c, 0))

    def to_legacy_links(self) -> List[ConceptLink]:
        """Convertit en liste de ConceptLink legacy pour rétrocompatibilité."""
        return [
            ConceptLink(
                assertion_id=self.assertion_id,
                concept_id=cid,
                link_type=self.link_types.get(cid, "relates_to"),
                justification=self.justifications.get(cid, ""),
                confidence=self.confidences.get(cid, 0.8)
            )
            for cid in self.concept_ids
        ]


# Seuils de contrôle multi-linking (C3: Anti "Spray & Pray")
MIN_LINK_CONFIDENCE = 0.70
MAX_LINKS_PER_ASSERTION = 5
TOP_K_IF_CLOSE = 2
CLOSE_THRESHOLD = 0.10  # Écart max entre top-1 et top-k

# ============================================================================
# RERANK "SPECIFICITY WINS" (Fix Concept Aspirateur - 2026-01-28)
# ============================================================================

# Seuils de confiance pour rerank
CONF_THRESHOLD_ORIGINAL = 0.45  # Minimum conf LLM pour être éligible (Qwen calibré ~0.60)
CONF_THRESHOLD_FINAL = 0.35     # Minimum conf après rerank pour garder le lien

# Règle de marge pour détection ambiguïté
MARGIN_AMBIGUOUS = 0.05  # Si écart < margin, marquer AMBIGUOUS

# Top-K dynamique
TOP_K_DEFAULT = 2           # Max concepts par assertion (défaut)
TOP_K_STRONG_MATCH = 1      # Winner-takes-all si match trigger fort (bonus >= 1.25)


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

        # RERANK "Specificity Wins" - Snapshot gelé au début du linking
        self._concept_info_snapshot: Dict[str, int] = {}  # {concept_id: info_count} gelé
        self._total_assertions_count: int = 0              # Pour seuils relatifs

        # Fix H2: Toxicité des triggers et activation des concepts
        self._trigger_toxicity: Dict[str, float] = {}     # {trigger_lower: freq_ratio}
        self._concept_activation: Dict[str, float] = {}   # {concept_id: activation_rate}

        # Sprint 2: Semantic Tie-Breaker (embeddings locaux)
        self._concept_embeddings: Dict[str, np.ndarray] = {}  # {concept_id: embedding 1024D}
        self._assertion_embedding_cache: Dict[str, np.ndarray] = {}  # {assertion_id: embedding}

    def _load_prompts(self, prompts_path: Optional[Path]) -> Dict:
        """Charge les prompts depuis le fichier YAML."""
        if prompts_path is None:
            prompts_path = Path(__file__).parent.parent / "prompts" / "pass1_prompts.yaml"

        if not prompts_path.exists():
            return {}

        with open(prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    # =========================================================================
    # RERANK "SPECIFICITY WINS" - Module A: Snapshot (Frozen during batch)
    # =========================================================================

    def _freeze_concept_counts(self, concepts: List[Concept], total_assertions: int) -> None:
        """
        Gèle les counts au début du linking (appelé 1x avant tous les batches).

        Args:
            concepts: Liste des concepts disponibles
            total_assertions: Nombre total d'assertions à linker (pour seuils relatifs)

        Note:
            Pour un doc neuf, tous les counts seront 0.
            Pour un re-import avec données existantes, on pourrait charger depuis Neo4j.
            Ici on utilise 0 pour simplicité et déterminisme.
        """
        # Initialiser tous les counts à 0 (doc neuf, simple et déterministe)
        self._concept_info_snapshot = {c.concept_id: 0 for c in concepts}
        self._total_assertions_count = total_assertions

        # Calcul des seuils relatifs pour audit
        start = max(10, int(0.20 * total_assertions))
        end = max(start + 10, int(0.50 * total_assertions))
        logger.info(
            f"[OSMOSE:Rerank] Snapshot gelé: {len(concepts)} concepts, "
            f"N={total_assertions}, seuils relatifs: start={start}, end={end}"
        )

    def _get_concept_info_count(self, concept_id: str) -> int:
        """Retourne le count GELÉ (pas d'incrément pendant le batch)."""
        return self._concept_info_snapshot.get(concept_id, 0)

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

        RERANK "Specificity Wins" (2026-01-28):
        Après le linking LLM, applique un rerank pour privilégier les concepts
        spécifiques et pénaliser les "concepts aspirateurs".
        """
        if not assertions or not concepts:
            return []

        # RERANK: Geler le snapshot des counts au début (avant tous les batches)
        self._freeze_concept_counts(concepts, len(assertions))

        # Fix H2: Pré-calculer la toxicité des triggers
        self._precompute_trigger_toxicity(assertions, concepts)

        # Sprint 2: Pré-calculer les embeddings des concepts pour le semantic tie-breaker
        self._precompute_concept_embeddings(concepts)

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
        # Si peu d'assertions, traitement direct (avec rerank aussi)
        if len(assertions) <= self.LINKING_BATCH_SIZE:
            links = self._link_batch(assertions, concepts)
            if links:
                links, lexical_bonuses, semantic_bonuses = self._rerank_links_specificity(
                    links, concepts, assertions
                )
                links = self._apply_margin_and_topk(links, lexical_bonuses, semantic_bonuses)
                logger.info(f"[OSMOSE:Pass1:1.4:Rerank] {len(links)} liens après rerank")
            return links

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

        logger.info(f"[OSMOSE:Pass1:1.4] {len(all_links)} liens LLM bruts établis")

        # RERANK "Specificity Wins": Post-traitement pour privilégier concepts spécifiques
        if all_links:
            all_links, lexical_bonuses, semantic_bonuses = self._rerank_links_specificity(
                all_links, concepts, assertions
            )
            all_links = self._apply_margin_and_topk(all_links, lexical_bonuses, semantic_bonuses)
            logger.info(f"[OSMOSE:Pass1:1.4:Rerank] {len(all_links)} liens après rerank")

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
        """
        Parse la réponse JSON des liens.

        V2.1: Supporte le format multi-concept (concept_links array).
        """
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
            concept_triggers = {c.concept_id: c.lexical_triggers for c in concepts}
            concept_names = {c.concept_id: c.name for c in concepts}  # C3 v2

            for l_data in data.get("links", []):
                assertion_id = l_data.get("assertion_id", "")

                if assertion_id not in assertion_map:
                    continue

                assertion_text = assertion_map[assertion_id].text

                # V2.1: Format multi-concept (concept_links array)
                if "concept_links" in l_data:
                    concept_links_raw = l_data.get("concept_links", [])
                    # Filtrer et valider avec C3 v2 (soft gate + hard gate)
                    filtered_links = self._filter_multi_links(
                        concept_links_raw, assertion_text, concept_ids,
                        concept_triggers, concept_names
                    )
                    for cl in filtered_links:
                        links.append(ConceptLink(
                            assertion_id=assertion_id,
                            concept_id=cl["concept_id"],
                            link_type=cl.get("link_type", "relates_to"),
                            justification=cl.get("justification", ""),
                            confidence=cl.get("confidence", 0.8)
                        ))
                else:
                    # Format legacy (un seul concept_id)
                    concept_id = l_data.get("concept_id", "")
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

    def _filter_multi_links(
        self,
        raw_links: List[Dict],
        unit_text: str,
        valid_concept_ids: set,
        concept_triggers: Dict[str, List[str]],
        concept_names: Optional[Dict[str, str]] = None
    ) -> List[Dict]:
        """
        C3 v2: Filtre les liens multiples avec soft gate + hard gate.

        Évite le "spray & pray" tout en permettant les liens légitimes
        où les triggers doc-level n'apparaissent pas dans l'assertion.

        Règles:
        1. Max 5 liens par assertion
        2. Soft gate: pas de trigger → confidence -= 0.20
        3. Hard gate: rejeter si (pas de trigger ET pas de token du nom) ET conf_adj < 0.55
        4. Garder si confidence_adj >= 0.70 OU top-2 si écart faible
        """
        if not raw_links:
            return []

        # Filtrer les concept_ids valides
        raw_links = [l for l in raw_links if l.get("concept_id") in valid_concept_ids]

        if not raw_links:
            return []

        # Trier par confiance décroissante (originale)
        sorted_links = sorted(raw_links, key=lambda l: l.get('confidence', 0), reverse=True)

        validated_links = []
        adjusted_confidences = []

        for i, link in enumerate(sorted_links[:MAX_LINKS_PER_ASSERTION]):
            concept_id = link.get('concept_id', '')
            confidence = link.get('confidence', 0)

            # --- C3 v2: Soft Gate ---
            triggers = concept_triggers.get(concept_id, [])
            has_trigger = self._has_trigger_match(unit_text, triggers) if triggers else False

            # Pénalité si pas de trigger
            confidence_adj = confidence
            if triggers and not has_trigger:
                confidence_adj -= 0.20

            # --- C3 v2: Hard Gate (ancrage minimal) ---
            concept_name = concept_names.get(concept_id, "") if concept_names else ""
            has_name_token = self._has_concept_name_token(unit_text, concept_name)

            # Rejet si: pas de trigger ET pas de token du nom ET conf_adj < 0.55
            if not has_trigger and not has_name_token and confidence_adj < 0.55:
                logger.debug(
                    f"[OSMOSE:C3v2] Rejeté {concept_id}: pas de signal lexical, "
                    f"conf_adj={confidence_adj:.2f}"
                )
                continue

            # --- Règles de sélection (sur confidence ajustée) ---
            adjusted_confidences.append((i, link, confidence_adj, has_trigger))

        if not adjusted_confidences:
            return []

        # Recalculer top_confidence sur les ajustées
        top_confidence_adj = max(c[2] for c in adjusted_confidences)

        for i, link, confidence_adj, has_trigger in adjusted_confidences:
            # Règle: Seuil de confiance ajustée ou top-k proche
            is_high_confidence = confidence_adj >= MIN_LINK_CONFIDENCE
            is_top_k_close = i < TOP_K_IF_CLOSE and (top_confidence_adj - confidence_adj) <= CLOSE_THRESHOLD

            if not (is_high_confidence or is_top_k_close):
                continue

            # Stocker avec confidence ajustée pour tracking
            link_copy = link.copy()
            link_copy['confidence_original'] = link.get('confidence', 0)
            link_copy['confidence'] = confidence_adj
            link_copy['has_trigger_match'] = has_trigger
            validated_links.append(link_copy)

        return validated_links

    def _has_concept_name_token(self, text: str, concept_name: str) -> bool:
        """
        C3 v2: Vérifie si au moins 1 token significatif du nom du concept
        est présent dans le texte (word boundary).

        Filtre les stopwords pour éviter les faux positifs.
        """
        if not concept_name:
            return False

        # Stopwords multilingues (les plus courants)
        STOPWORDS = {
            'the', 'a', 'an', 'of', 'in', 'to', 'for', 'and', 'or', 'is', 'are', 'be',
            'le', 'la', 'les', 'de', 'du', 'des', 'et', 'ou', 'un', 'une', 'en', 'à',
            'der', 'die', 'das', 'und', 'oder', 'in', 'von', 'für',
            'with', 'on', 'at', 'by', 'as', 'from', 'que', 'qui', 'sur', 'par',
            'data', 'system', 'management', 'service', 'process',  # Termes trop génériques
        }

        text_lower = text.lower()

        # Extraire les tokens significatifs du nom du concept
        tokens = re.findall(r'\b[a-zA-Z]{3,}\b', concept_name.lower())
        significant_tokens = [t for t in tokens if t not in STOPWORDS]

        # Vérifier si au moins 1 token significatif est présent
        for token in significant_tokens:
            if re.search(rf'\b{re.escape(token)}\b', text_lower):
                return True

        return False

    def _has_trigger_match(self, text: str, triggers: List[str]) -> bool:
        """C3 + C1c: Vérifie qu'au moins 1 trigger est présent (word boundary)."""
        if not triggers:
            return True  # Pas de triggers définis = accepter (rétrocompatibilité)

        text_lower = text.lower()

        for t in triggers:
            t_lower = t.lower()
            # C1c: Utiliser word boundary pour alphanum, substring pour valeurs
            if VALUE_PATTERN.match(t):
                # Substring pour valeurs (8%, 1.2, 2-8°C)
                if t_lower in text_lower:
                    return True
            else:
                # Word boundary pour éviter matchs absurdes ("cat" dans "category")
                if re.search(rf'\b{re.escape(t_lower)}\b', text_lower):
                    return True

        return False

    # =========================================================================
    # Fix H2: TOXICITÉ DES TRIGGERS + GARDE-FOU ACTIVATION
    # =========================================================================

    def _match_trigger_in_text(self, trigger: str, text: str) -> bool:
        """
        Helper unique de matching trigger → texte.
        Utilisé par _precompute_trigger_toxicity() et _compute_lexical_bonus().
        Normalise: lowercase + word-boundary (courts: no-letter boundary).
        """
        t = trigger.lower()
        text_lower = text.lower()
        if len(t) >= 4:
            return bool(re.search(rf'\b{re.escape(t)}\b', text_lower))
        else:
            return bool(re.search(rf'(?<![a-z]){re.escape(t)}(?![a-z])', text_lower))

    def _precompute_trigger_toxicity(
        self,
        assertions: List[RawAssertion],
        concepts: List[Concept]
    ) -> None:
        """
        Pré-calcule le taux de match de chaque trigger sur les assertions.

        Un trigger est "toxique" s'il matche > 8% des assertions (bruit).
        Stocke dans self._trigger_toxicity: {trigger_lower: frequency_ratio}
        Calcule aussi self._concept_activation: {concept_id: activation_rate}
        """
        total = len(assertions)
        if total == 0:
            self._trigger_toxicity = {}
            self._concept_activation = {}
            return

        # Collecter tous les triggers uniques
        all_triggers: Dict[str, List[str]] = {}  # {trigger_lower: [concept_ids]}
        for concept in concepts:
            triggers = getattr(concept, 'lexical_triggers', None) or []
            for t in triggers:
                t_lower = t.lower()
                if t_lower not in all_triggers:
                    all_triggers[t_lower] = []
                all_triggers[t_lower].append(concept.concept_id)

        # Compter les matches par trigger sur toutes les assertions
        trigger_match_counts: Dict[str, int] = {}
        for t_lower in all_triggers:
            count = sum(
                1 for a in assertions
                if self._match_trigger_in_text(t_lower, a.text)
            )
            trigger_match_counts[t_lower] = count

        # Calculer les ratios de toxicité
        self._trigger_toxicity = {
            t_lower: count / total
            for t_lower, count in trigger_match_counts.items()
        }

        # Log triggers toxiques
        toxic_triggers = {
            t: freq for t, freq in self._trigger_toxicity.items()
            if freq > 0.08
        }
        if toxic_triggers:
            logger.info(
                f"[OSMOSE:Rerank:Toxicity] {len(toxic_triggers)} triggers toxiques (>8%): "
                f"{dict(list(toxic_triggers.items())[:5])}"
            )

        # GF-A: Calculer activation_rate par concept
        self._concept_activation = {}
        for concept in concepts:
            triggers = getattr(concept, 'lexical_triggers', None) or []
            if not triggers:
                self._concept_activation[concept.concept_id] = 0.0
                continue

            # Triggers non-toxiques de ce concept
            non_toxic_triggers = [
                t for t in triggers
                if self._trigger_toxicity.get(t.lower(), 0.0) <= 0.08
            ]

            if not non_toxic_triggers:
                self._concept_activation[concept.concept_id] = 0.0
                logger.info(
                    f"[OSMOSE:Rerank:GF-A] {concept.concept_id} ({concept.name}): "
                    f"activation_rate=0, tous les triggers sont toxiques, "
                    f"bonus lexical désactivé"
                )
                continue

            # Compter les assertions matchant au moins 1 trigger non-toxique
            matching_assertions = sum(
                1 for a in assertions
                if any(
                    self._match_trigger_in_text(t, a.text)
                    for t in non_toxic_triggers
                )
            )
            activation_rate = matching_assertions / total
            self._concept_activation[concept.concept_id] = activation_rate

            if activation_rate < 0.01:
                logger.info(
                    f"[OSMOSE:Rerank:GF-A] {concept.concept_id} ({concept.name}): "
                    f"activation_rate={activation_rate:.1%}, bonus lexical réduit"
                )

    # =========================================================================
    # SPRINT 2: SEMANTIC TIE-BREAKER (embeddings locaux)
    # =========================================================================

    def _precompute_concept_embeddings(self, concepts: List[Concept]) -> None:
        """
        Encode les concepts une seule fois pour le semantic tie-breaker.
        Stocke dans self._concept_embeddings: {concept_id: np.array(1024D)}

        Sprint 4 (4b): Représentation enrichie:
        - Nom du concept
        - Définition (si disponible, tronquée à 80 chars)
        - Triggers cross-filtrés non-toxiques multi-mots (<=5, au lieu de 3)
        - Triggers shared inclus (pertinents sémantiquement)
        - Triggers rejetés par cross-filter exclus
        - SINK exclu de l'encodage
        """
        from knowbase.stratified.models import ConceptRole

        try:
            from knowbase.common.clients.embeddings import get_embedding_manager
        except ImportError:
            logger.warning("[OSMOSE:Rerank:Semantic] embeddings non disponibles, semantic désactivé")
            self._concept_embeddings = {}
            return

        texts = []
        ids = []
        for c in concepts:
            # Sprint 4 (2e): Exclure SINK de l'encodage sémantique
            if c.role == ConceptRole.SINK:
                continue

            triggers = getattr(c, 'lexical_triggers', None) or []
            # Filtrer: uniquement non-toxiques (<=8%) ET multi-mots (>=2 tokens)
            # Sprint 4: Les triggers shared sont inclus (pertinents sémantiquement)
            clean_triggers = [
                t for t in triggers
                if self._trigger_toxicity.get(t.lower(), 0.0) <= 0.08
                and len(t.split()) >= 2
            ]

            repr_text = c.name
            # Sprint 4 (4b): Inclure la définition si disponible
            if c.definition:
                repr_text += " " + c.definition[:80]
            # Sprint 4 (4b): Augmenter de 3 à 5 triggers dans la représentation
            if clean_triggers:
                repr_text += " " + " ".join(clean_triggers[:5])
            texts.append(repr_text)
            ids.append(c.concept_id)

        if not texts:
            self._concept_embeddings = {}
            return

        try:
            manager = get_embedding_manager()
            embeddings = manager.encode(texts)  # Batch encode

            self._concept_embeddings = {
                cid: emb for cid, emb in zip(ids, embeddings)
            }
            logger.info(
                f"[OSMOSE:Rerank:Semantic] {len(ids)} concepts encodés "
                f"(embeddings {embeddings.shape[1]}D, SINK exclu)"
            )
        except Exception as e:
            logger.warning(f"[OSMOSE:Rerank:Semantic] Encodage concepts échoué: {e}")
            self._concept_embeddings = {}

    def _get_assertion_embedding(self, assertion_id: str, assertion_text: str) -> np.ndarray:
        """
        Lazy-encode une assertion (avec cache pour éviter re-calculs).
        Cache key = assertion_id (stable, unique).
        """
        if assertion_id not in self._assertion_embedding_cache:
            from knowbase.common.clients.embeddings import get_embedding_manager
            manager = get_embedding_manager()
            self._assertion_embedding_cache[assertion_id] = manager.encode([assertion_text])[0]

        return self._assertion_embedding_cache[assertion_id]

    def _compute_semantic_bonuses_for_assertion(
        self,
        assertion_id: str,
        assertion_text: str,
        candidate_concept_ids: List[str]
    ) -> Dict[str, float]:
        """
        Calcule le bonus sémantique pour une assertion vs ses concepts candidats.
        Utilise un z-score relatif (pas de seuil absolu).

        Returns: {concept_id: bonus} avec bonus in [1.0, 1.15]
        """
        if not self._concept_embeddings or not candidate_concept_ids:
            return {cid: 1.0 for cid in candidate_concept_ids}

        assertion_emb = self._get_assertion_embedding(assertion_id, assertion_text)

        # Calculer la similarité cosine avec tous les concepts candidats
        sims = {}
        for cid in candidate_concept_ids:
            concept_emb = self._concept_embeddings.get(cid)
            if concept_emb is None:
                sims[cid] = 0.0
                continue
            sim = float(np.dot(assertion_emb, concept_emb) / (
                np.linalg.norm(assertion_emb) * np.linalg.norm(concept_emb) + 1e-8
            ))
            sims[cid] = sim

        # Z-score relatif: (sim - mean) / std
        values = list(sims.values())
        if len(values) < 2:
            return {cid: 1.0 for cid in candidate_concept_ids}

        mean_sim = float(np.mean(values))
        std_sim = float(np.std(values))
        if std_sim < 0.001:
            # Tous les concepts ont la même similarité → pas de signal
            return {cid: 1.0 for cid in candidate_concept_ids}

        bonuses = {}
        for cid, sim in sims.items():
            z = (sim - mean_sim) / std_sim
            # Sprint 4: Mapper z-score → bonus (plafond 1.20):
            # z < 0.5 → 1.0 (pas au-dessus de la moyenne)
            # z 0.5-1.5 → 1.0-1.15 (linéaire)
            # z 1.5-2.0 → 1.15-1.20 (linéaire, nouveau Sprint 4)
            # z > 2.0 → 1.20 (plafonné, nouveau Sprint 4)
            if z < 0.5:
                bonuses[cid] = 1.0
            elif z < 1.5:
                bonuses[cid] = 1.0 + (z - 0.5) * 0.15  # 1.0 → 1.15
            elif z < 2.0:
                bonuses[cid] = 1.15 + (z - 1.5) * 0.10  # 1.15 → 1.20
            else:
                bonuses[cid] = 1.20  # Plafond Sprint 4

        return bonuses

    # =========================================================================
    # RERANK "SPECIFICITY WINS" - Module B: Bonus Lexical et Pénalité
    # =========================================================================

    def _tokenize(self, text: str, min_length: int = 3) -> set:
        """
        Tokenize en mots lowercase, filtre les stop words.

        Args:
            text: Texte à tokenizer
            min_length: longueur minimum des tokens (défaut 3, recommandé 4 pour éviter surmatches)

        Returns:
            Set de tokens lowercase filtrés
        """
        pattern = rf'\b[a-zA-Z]{{{min_length},}}\b'
        tokens = re.findall(pattern, text.lower())

        # Filtrer stop words communs (EN + FR)
        stop_words = {
            'the', 'and', 'for', 'with', 'from', 'that', 'this', 'are', 'was',
            'not', 'can', 'will', 'have', 'has', 'been', 'being', 'other',
            'les', 'des', 'une', 'par', 'pour', 'dans', 'sur', 'avec', 'qui', 'que',
            'est', 'sont', 'aux', 'ces', 'ont', 'mais', 'comme', 'tout',
            # Termes trop génériques pour le domaine
            'data', 'system', 'management', 'service', 'process', 'security',
        }
        return set(t for t in tokens if t not in stop_words)

    def _compute_lexical_bonus(self, assertion_text: str, concept: Concept) -> float:
        """
        Bonus si tokens spécifiques du concept sont dans l'assertion.

        Utilise word boundaries (\\b) pour éviter surmatches.
        Ex: "patch" ne match pas "dispatch", "ha" ne match pas "have".

        Fix H2: Modulé par toxicité des triggers et activation du concept.
        - Trigger toxique (>8% assertions): ignoré (pas de bonus)
        - Trigger faible (3-8%): bonus réduit à 1.10
        - Trigger discriminant (<3%): bonus complet 1.25

        Sprint 4: Triggers shared (cross-filter) → bonus plafonné à 1.05
        Sprint 4: SINK ne reçoit jamais de bonus (1.0 toujours)

        GF-A: Si concept sans activation → neutre (1.0)
              Si concept à faible activation (<1%) → plafonné à 1.10

        Args:
            assertion_text: Texte de l'assertion
            concept: Concept à évaluer

        Returns:
            Bonus multiplicatif: 1.0 (pas de match), 1.05 (shared), 1.10-1.20 (match nom), 1.25 (match trigger)
        """
        from knowbase.stratified.models import ConceptRole

        if not assertion_text:
            return 1.0

        # Sprint 4 (2d): SINK ne reçoit jamais de bonus
        if concept.role == ConceptRole.SINK:
            return 1.0

        # GF-A: Vérifier activation du concept
        activation = self._concept_activation.get(concept.concept_id, -1.0)
        if activation == 0.0:
            # Concept sans trigger utile → neutre, laisser le LLM décider
            return 1.0

        # Plafond de bonus pour concepts à faible activation
        max_bonus = 1.25
        if 0.0 < activation < 0.01:
            max_bonus = 1.10  # GF-A: plafonné

        # Sprint 4: Récupérer les triggers shared du concept
        shared_triggers = getattr(concept, '_shared_triggers', set())

        # Utiliser les triggers si disponibles (plus fiables)
        triggers = getattr(concept, 'lexical_triggers', None) or []
        if triggers:
            for trigger in triggers:
                if self._match_trigger_in_text(trigger, assertion_text):
                    # Fix H2: Moduler par toxicité
                    tox = self._trigger_toxicity.get(trigger.lower(), 0.0)
                    if tox > 0.08:
                        continue  # Trigger toxique, ignorer

                    # Sprint 4: Trigger partagé → bonus plafonné 1.05
                    if trigger.lower() in shared_triggers:
                        return min(1.05, max_bonus)

                    if tox > 0.03:
                        return min(1.10, max_bonus)  # Bonus réduit
                    else:
                        return min(1.25, max_bonus)  # Bonus complet

        # Fallback: tokens du nom du concept (seulement mots longs >= 4 chars)
        concept_tokens = self._tokenize(concept.name, min_length=4)
        assertion_tokens = self._tokenize(assertion_text, min_length=4)

        overlap = concept_tokens & assertion_tokens
        if not overlap:
            return 1.0

        # Bonus plus fort si token long (= plus spécifique)
        has_long_token = any(len(t) >= 6 for t in overlap)
        bonus = 1.20 if has_long_token else 1.10
        return min(bonus, max_bonus)

    def _saturating_penalty(
        self,
        info_count: int,
        concept: Concept,
        lexical_bonus: float,
        num_real_concepts: Optional[int] = None,
        total_assertions: Optional[int] = None,
    ) -> float:
        """
        Sprint 4: Pénalité 3 phases pour concepts aspirateurs.

        Basée sur mean = total_assertions / num_real_concepts (sans SINK).

        Phase 1 (douce)     : 0 → 2×mean     → 1.0 → 0.8 (linéaire)
        Phase 2 (agressive) : 2×mean → 3×mean → 0.8 → 0.5 (linéaire)
        Phase 3 (near-block): > 3×mean        → 0.5 fixe

        Override lexical fort: si bonus_lexical ≥ 1.25, penalty = max(penalty, 0.80)
        SINK exempt: penalty = 1.0 toujours.

        Args:
            info_count: Nombre d'infos assignées au concept (provisional ou snapshot)
            concept: Concept évalué
            lexical_bonus: Bonus lexical calculé
            num_real_concepts: Nombre de concepts réels (sans SINK). Si None, utilise le snapshot.
            total_assertions: Total assertions. Si None, utilise le snapshot.

        Returns:
            Pénalité multiplicative [0.5, 1.0]
        """
        from knowbase.stratified.models import ConceptRole

        # Sprint 4 (2d): SINK n'a pas de pénalité (conçu pour absorber)
        if concept.role == ConceptRole.SINK:
            return 1.0

        N = total_assertions if total_assertions is not None else self._total_assertions_count
        n_concepts = num_real_concepts if num_real_concepts is not None else max(1, len(self._concept_info_snapshot))

        if N == 0 or n_concepts == 0:
            return 1.0

        mean = N / n_concepts

        # Seuils 3 phases
        soft_end = 2.0 * mean   # Fin de la phase douce
        hard_end = 3.0 * mean   # Fin de la phase agressive

        # Calcul de la pénalité 3 phases
        if info_count <= soft_end:
            # Phase 1 (douce): 1.0 → 0.8
            if soft_end <= 0:
                base_penalty = 1.0
            else:
                ratio = info_count / soft_end
                base_penalty = 1.0 - 0.2 * ratio
        elif info_count <= hard_end:
            # Phase 2 (agressive): 0.8 → 0.5
            if hard_end <= soft_end:
                base_penalty = 0.5
            else:
                ratio = (info_count - soft_end) / (hard_end - soft_end)
                base_penalty = 0.8 - 0.3 * ratio
        else:
            # Phase 3 (near-block): 0.5 fixe
            base_penalty = 0.5

        # Log phases agressive et near-block
        if base_penalty < 0.8 and base_penalty >= 0.5:
            logger.debug(
                f"[OSMOSE:Rerank:Saturation:Phase2-agressive] "
                f"{concept.concept_id}: count={info_count}, mean={mean:.1f}, "
                f"penalty={base_penalty:.2f}"
            )
        elif base_penalty <= 0.5:
            logger.debug(
                f"[OSMOSE:Rerank:Saturation:Phase3-near-block] "
                f"{concept.concept_id}: count={info_count}, mean={mean:.1f}, "
                f"penalty={base_penalty:.2f}"
            )

        # Sprint 4: Override lexical fort — perce le near-block
        if lexical_bonus >= 1.25:
            if base_penalty < 0.80:
                logger.debug(
                    f"[OSMOSE:Rerank:Saturation:LexicalOverride] "
                    f"{concept.concept_id}: penalty {base_penalty:.2f} → 0.80 "
                    f"(lexical_bonus={lexical_bonus:.2f})"
                )
            base_penalty = max(base_penalty, 0.80)

        # MICRO-AJUSTEMENT 1: Pénalité légère si count=0 ET pas de signal lexical
        if info_count == 0 and lexical_bonus == 1.0:
            if concept.role in (ConceptRole.CONTEXTUAL,):
                base_penalty *= 0.95

        return base_penalty

    # =========================================================================
    # RERANK "SPECIFICITY WINS" - Module B: Rerank et Top-K
    # =========================================================================

    def _rerank_links_specificity(
        self,
        links: List[ConceptLink],
        concepts: List[Concept],
        assertions: List[RawAssertion]
    ) -> Tuple[List[ConceptLink], Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
        """
        Rerank les liens pour privilégier les concepts spécifiques.

        Sprint 4: Approche 2-pass avec pénalité 3 phases.
        Pass 1: Score sans pénalité → provisional distribution
        Pass 2: Re-score avec pénalité basée sur provisional_counts

        Score = conf_llm × combined_bonus × bonus_central × penalty_saturante
        où combined_bonus = bonus_lexical si lex > 1.0, sinon bonus_semantic

        Sprint 4 SINK: Malus inhérent -10%, seuil < 0.55, pas de bonus.

        Args:
            links: Liens LLM originaux
            concepts: Liste des concepts
            assertions: Liste des assertions

        Returns:
            - links: Liste des liens avec confidences ajustées
            - lexical_bonuses: {assertion_id: {concept_id: bonus}} pour TOP_K dynamique
            - semantic_bonuses: {assertion_id: {concept_id: bonus}} pour TOP_K semantic
        """
        from knowbase.stratified.models import ConceptRole

        concept_map = {c.concept_id: c for c in concepts}
        assertion_map = {a.assertion_id: a for a in assertions}
        lexical_bonuses: Dict[str, Dict[str, float]] = {}

        # Sprint 4: Compter les concepts réels (sans SINK)
        num_real_concepts = sum(
            1 for c in concepts if c.role != ConceptRole.SINK
        )

        # ─── PHASE 1: Pré-calculer les bonus lexicaux ───
        for link in links:
            assertion = assertion_map.get(link.assertion_id)
            assertion_text = assertion.text if assertion else ""

            if link.assertion_id not in lexical_bonuses:
                lexical_bonuses[link.assertion_id] = {}

            concept = concept_map.get(link.concept_id)
            if not concept:
                continue

            bonus_lexical = self._compute_lexical_bonus(assertion_text, concept)
            lexical_bonuses[link.assertion_id][link.concept_id] = bonus_lexical

        # ─── PHASE 2: Pré-calculer les bonus sémantiques (si lexical neutre) ───
        semantic_bonuses: Dict[str, Dict[str, float]] = {}

        for assertion_id, concept_bonuses in lexical_bonuses.items():
            # Semantic UNIQUEMENT si TOUS les bonus lexicaux = 1.0
            all_lexical_neutral = all(b == 1.0 for b in concept_bonuses.values())
            if all_lexical_neutral and self._concept_embeddings:
                assertion = assertion_map.get(assertion_id)
                if not assertion:
                    continue
                candidate_ids = list(concept_bonuses.keys())
                sem_b = self._compute_semantic_bonuses_for_assertion(
                    assertion_id, assertion.text, candidate_ids
                )
                semantic_bonuses[assertion_id] = sem_b

        # Calibration logging (premier document seulement)
        if semantic_bonuses and not hasattr(self, '_semantic_calibration_logged'):
            all_sem_values = [
                v for sb in semantic_bonuses.values()
                for v in sb.values()
                if v > 1.0
            ]
            if all_sem_values:
                logger.info(
                    f"[OSMOSE:Rerank:Semantic:Calibration] "
                    f"assertions_avec_semantic={len(semantic_bonuses)}, "
                    f"bonuses>1.0: n={len(all_sem_values)}, "
                    f"min={min(all_sem_values):.3f}, "
                    f"mean={np.mean(all_sem_values):.3f}, "
                    f"max={max(all_sem_values):.3f}"
                )
            else:
                logger.info(
                    f"[OSMOSE:Rerank:Semantic:Calibration] "
                    f"assertions_avec_semantic={len(semantic_bonuses)}, "
                    f"aucun bonus>1.0 (pas de discrimination sémantique)"
                )
            self._semantic_calibration_logged = True

        # ─── PASS 1: Score SANS pénalité saturante → provisional winners ───
        provisional_scores: Dict[str, Dict[str, float]] = {}  # {assertion_id: {concept_id: score}}
        original_confs: Dict[str, Dict[str, float]] = {}      # {assertion_id: {concept_id: original_conf}}

        for link in links:
            concept = concept_map.get(link.concept_id)
            if not concept:
                continue

            original_conf = link.confidence

            # Stocker la confidence originale
            if link.assertion_id not in original_confs:
                original_confs[link.assertion_id] = {}
            original_confs[link.assertion_id][link.concept_id] = original_conf

            # 1. Bonus lexical
            bonus_lexical = lexical_bonuses.get(link.assertion_id, {}).get(link.concept_id, 1.0)

            # 2. Semantic tie-breaker (seulement si lexical neutre)
            bonus_semantic = semantic_bonuses.get(link.assertion_id, {}).get(link.concept_id, 1.0)

            # Combined: lexical si lex > 1.0, sinon semantic
            combined_bonus = bonus_lexical if bonus_lexical > 1.0 else bonus_semantic

            # 3. S2-A: CENTRAL conditionnel (seulement si preuve locale)
            has_local_evidence = (bonus_lexical > 1.0) or (bonus_semantic > 1.0)
            bonus_central = 1.10 if (concept.role == ConceptRole.CENTRAL and has_local_evidence) else 1.0

            # Sprint 4 SINK: Malus inhérent -10%
            sink_malus = 0.90 if concept.role == ConceptRole.SINK else 1.0

            # Pass 1: Score SANS pénalité saturante
            pass1_score = min(1.0, original_conf * combined_bonus * bonus_central * sink_malus)

            if link.assertion_id not in provisional_scores:
                provisional_scores[link.assertion_id] = {}
            provisional_scores[link.assertion_id][link.concept_id] = pass1_score

        # ─── Calcul provisional distribution ───
        provisional_counts: Dict[str, int] = {}
        for concept in concepts:
            provisional_counts[concept.concept_id] = 0

        for assertion_id, scores in provisional_scores.items():
            if scores:
                winner_id = max(scores, key=scores.get)
                provisional_counts[winner_id] = provisional_counts.get(winner_id, 0) + 1

        # Log la distribution provisoire
        total_assertions = len(provisional_scores)
        non_zero = {k: v for k, v in provisional_counts.items() if v > 0}
        logger.info(
            f"[OSMOSE:Rerank:2Pass] Pass 1: provisional distribution "
            f"({total_assertions} assertions, {len(non_zero)} concepts actifs). "
            f"Top: {sorted(non_zero.items(), key=lambda x: -x[1])[:5]}"
        )

        # ─── PASS 2: Re-score avec pénalité 3 phases basée sur provisional_counts ───
        for link in links:
            concept = concept_map.get(link.concept_id)
            if not concept:
                continue

            original_conf = original_confs.get(link.assertion_id, {}).get(link.concept_id, link.confidence)

            # 1. Bonus lexical
            bonus_lexical = lexical_bonuses.get(link.assertion_id, {}).get(link.concept_id, 1.0)

            # 2. Semantic tie-breaker
            bonus_semantic = semantic_bonuses.get(link.assertion_id, {}).get(link.concept_id, 1.0)
            combined_bonus = bonus_lexical if bonus_lexical > 1.0 else bonus_semantic

            # 3. CENTRAL conditionnel
            has_local_evidence = (bonus_lexical > 1.0) or (bonus_semantic > 1.0)
            bonus_central = 1.10 if (concept.role == ConceptRole.CENTRAL and has_local_evidence) else 1.0

            # Sprint 4 SINK: Malus inhérent -10%
            sink_malus = 0.90 if concept.role == ConceptRole.SINK else 1.0

            # 4. Pénalité saturante 3 phases (basée sur provisional_counts)
            prov_count = provisional_counts.get(link.concept_id, 0)
            penalty = self._saturating_penalty(
                prov_count, concept, bonus_lexical,
                num_real_concepts=num_real_concepts,
                total_assertions=total_assertions,
            )

            # Score final
            new_conf = min(1.0, original_conf * combined_bonus * bonus_central * penalty * sink_malus)

            # Stocker la confidence originale pour le double seuil
            if not hasattr(link, 'original_confidence'):
                link.original_confidence = original_conf

            link.confidence = new_conf

            # Log traçabilité enrichi
            if abs(new_conf - original_conf) > 0.01:
                logger.debug(
                    f"[OSMOSE:Rerank] {link.assertion_id} → {link.concept_id}: "
                    f"conf {original_conf:.2f} → {new_conf:.2f} "
                    f"(lex={bonus_lexical:.2f}, sem={bonus_semantic:.2f}, "
                    f"central={bonus_central:.2f}, penalty={penalty:.2f}, "
                    f"sink_malus={sink_malus:.2f}, prov_count={prov_count})"
                )

        return links, lexical_bonuses, semantic_bonuses

    def _apply_margin_and_topk(
        self,
        links: List[ConceptLink],
        lexical_bonuses: Dict[str, Dict[str, float]],
        semantic_bonuses: Optional[Dict[str, Dict[str, float]]] = None
    ) -> List[ConceptLink]:
        """
        Après rerank, re-trier et appliquer les règles de sélection finale.

        1. Filtrer concepts sous le seuil (double seuil: original + final)
        2. Grouper par assertion
        3. Trier par confidence décroissante
        4. Garder top-k (dynamique: =1 si match trigger fort OU semantic discriminant)
        5. Si écart best/second < margin → log AMBIGUOUS

        Sprint 4 SINK:
        - Si best_non_sink_score < 0.55 → SINK gagne automatiquement
        - Si un concept non-SINK a bonus ≥ 1.15 (signal fort) → éliminer SINK
        - Trigger shared (1.05) ne suffit PAS à éliminer SINK

        Args:
            links: Liens après rerank
            lexical_bonuses: {assertion_id: {concept_id: bonus}} pour TOP_K dynamique
            semantic_bonuses: {assertion_id: {concept_id: bonus}} pour TOP_K semantic

        Returns:
            Liste filtrée des liens
        """
        from knowbase.stratified.models import ConceptRole

        if semantic_bonuses is None:
            semantic_bonuses = {}

        # Identifier le concept SINK
        sink_concept_ids = set()
        for link in links:
            # Vérifier via le concept_map si possible (les concept_ids contenant "_SINK" suffisent)
            if link.concept_id.endswith("_SINK"):
                sink_concept_ids.add(link.concept_id)

        # Grouper les liens par assertion_id
        links_by_assertion: Dict[str, List[ConceptLink]] = {}
        for link in links:
            if link.assertion_id not in links_by_assertion:
                links_by_assertion[link.assertion_id] = []
            links_by_assertion[link.assertion_id].append(link)

        filtered_links = []

        for assertion_id, assertion_links in links_by_assertion.items():
            assertion_bonuses = lexical_bonuses.get(assertion_id, {})
            assertion_sem_bonuses = semantic_bonuses.get(assertion_id, {})

            # Filtrer et scorer
            scored = []
            has_strong_match = False
            has_signal_fort = False  # Sprint 4: bonus ≥ 1.15 sur un non-SINK

            for link in assertion_links:
                conf_final = link.confidence
                conf_original = getattr(link, 'original_confidence', conf_final)
                lex_bonus = assertion_bonuses.get(link.concept_id, 1.0)
                sem_bonus = assertion_sem_bonuses.get(link.concept_id, 1.0)

                # MICRO-AJUSTEMENT 3: Double seuil
                if conf_original < CONF_THRESHOLD_ORIGINAL:
                    continue
                if conf_final < CONF_THRESHOLD_FINAL:
                    continue

                scored.append((link, conf_final, lex_bonus))

                # MICRO-AJUSTEMENT 2: Détection match trigger fort (lexical seul)
                if lex_bonus >= 1.25:
                    has_strong_match = True

                # Sprint 4: Signal fort (non-SINK) → permet d'éliminer SINK
                is_sink = link.concept_id in sink_concept_ids
                if not is_sink and (lex_bonus >= 1.15 or sem_bonus >= 1.15):
                    has_signal_fort = True

            if not scored:
                continue

            # Tri par conf_final décroissante
            scored.sort(key=lambda x: -x[1])

            # ─── Sprint 4: Logique SINK ───
            # Séparer SINK et non-SINK
            non_sink_scored = [(l, c, b) for l, c, b in scored if l.concept_id not in sink_concept_ids]
            sink_scored = [(l, c, b) for l, c, b in scored if l.concept_id in sink_concept_ids]

            if sink_scored and non_sink_scored:
                best_non_sink_score = non_sink_scored[0][1]

                # Règle seuil: si meilleur non-SINK < 0.55 → SINK gagne
                if best_non_sink_score < 0.55:
                    filtered_links.append(sink_scored[0][0])
                    continue

                # Élimination SINK: si signal fort (bonus ≥ 1.15) → exclure SINK
                if has_signal_fort:
                    scored = non_sink_scored
            elif sink_scored and not non_sink_scored:
                # Seul SINK disponible
                filtered_links.append(sink_scored[0][0])
                continue

            # Détection ambiguïté
            if len(scored) >= 2:
                best_conf, second_conf = scored[0][1], scored[1][1]
                if best_conf - second_conf < MARGIN_AMBIGUOUS:
                    logger.info(
                        f"[OSMOSE:Rerank:AMBIGUOUS] {assertion_id}: "
                        f"{scored[0][0].concept_id} ({best_conf:.2f}) vs "
                        f"{scored[1][0].concept_id} ({second_conf:.2f})"
                    )

            # S2-C: Semantic margin → top_k=1 si nettement discriminant
            if not has_strong_match and assertion_id in semantic_bonuses:
                sem_vals = sorted(
                    semantic_bonuses[assertion_id].values(), reverse=True
                )
                if len(sem_vals) >= 2 and sem_vals[0] - sem_vals[1] > 0.05:
                    has_strong_match = True  # Semantic clairement discriminant

            # TOP_K dynamique
            top_k = TOP_K_STRONG_MATCH if has_strong_match else TOP_K_DEFAULT
            kept = scored[:top_k]

            # Ajouter les liens retenus
            for link, _, _ in kept:
                filtered_links.append(link)

        return filtered_links

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
