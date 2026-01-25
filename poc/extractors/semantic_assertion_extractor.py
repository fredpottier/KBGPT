"""
Phase 1.3 REFONTE - Semantic Assertion Extractor

Approche en 2 temps:
1. EXTRACT: Identifier les ASSERTIONS dans le texte (phrases portant une connaissance)
2. LINK: Rattacher chaque assertion aux concepts pertinents (raisonnement semantique)

Differences avec l'ancien InformationExtractor:
- Matching SEMANTIQUE, pas lexical
- Raisonnement sur le SENS, pas sur la surface
- Gestion multilingue (concept FR, texte EN)
- Anchor par SEGMENT identifie, pas par positions devinees
"""

import json
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

from poc.models.schemas import (
    Information,
    InfoType,
    Anchor,
    ConceptSitue
)
from poc.validators.anchor_validator import AnchorValidator

# Type hint pour PROMOTION_POLICY (defini apres les Enums)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    pass


class AssertionType(Enum):
    """Types d'assertions dans le texte source"""
    DEFINITIONAL = "definitional"      # Definit quelque chose
    FACTUAL = "factual"                # Enonce un fait
    PRESCRIPTIVE = "prescriptive"      # Obligation, regle
    PERMISSIVE = "permissive"          # Possibilite, option
    CONDITIONAL = "conditional"        # Si... alors...
    CAUSAL = "causal"                  # A cause B, A implique B
    COMPARATIVE = "comparative"        # A vs B, A meilleur que B
    PROCEDURAL = "procedural"          # Etape, processus


# =========================================================================
# ASSERTION PROMOTION POLICY
# =========================================================================
# Seules certaines assertions meritent d'etre promues en Information.
# Les autres sont de la "matiere documentaire" non conceptuelle.

class PromotionTier(Enum):
    """Niveaux de promotion des assertions"""
    ALWAYS = "always"          # Toujours promouvoir si lie a un concept
    CONDITIONAL = "conditional"  # Promouvoir si confiance >= 0.7
    RARELY = "rarely"          # Promouvoir seulement si confiance >= 0.9
    NEVER = "never"            # Ne jamais promouvoir en Information


# Politique de promotion par type d'assertion
PROMOTION_POLICY: Dict[AssertionType, PromotionTier] = {
    AssertionType.DEFINITIONAL: PromotionTier.ALWAYS,     # Definitions = coeur conceptuel
    AssertionType.PRESCRIPTIVE: PromotionTier.ALWAYS,     # Regles normatives = haute valeur
    AssertionType.CAUSAL: PromotionTier.ALWAYS,           # Relations causales = structurantes
    AssertionType.FACTUAL: PromotionTier.CONDITIONAL,     # Faits = depends du contexte
    AssertionType.CONDITIONAL: PromotionTier.CONDITIONAL, # Conditions = utiles si precises
    AssertionType.PERMISSIVE: PromotionTier.CONDITIONAL,  # Options = utiles si specifiques
    AssertionType.COMPARATIVE: PromotionTier.RARELY,      # Comparaisons = souvent locales
    AssertionType.PROCEDURAL: PromotionTier.NEVER,        # Procedures = non conceptuelles
}


@dataclass
class Assertion:
    """Une assertion identifiee dans le texte"""
    text: str                          # Le texte exact de l'assertion
    assertion_type: AssertionType      # Type d'assertion
    chunk_id: str                      # Chunk source
    start_char: int                    # Position debut
    end_char: int                      # Position fin
    confidence: float                  # Confiance de l'extraction
    language: str                      # Langue detectee (en, fr, etc.)


@dataclass
class ConceptLink:
    """Lien semantique entre une assertion et un concept"""
    assertion_idx: int                 # Index de l'assertion
    concept_id: str                    # ID du concept lie
    link_type: str                     # Type de lien (defines, describes, constrains, etc.)
    semantic_justification: str        # Pourquoi ce lien existe
    confidence: float                  # Confiance du lien


class SemanticAssertionExtractor:
    """
    Extracteur d'assertions avec raisonnement semantique.

    Pipeline:
    1. Segmenter le texte en assertions candidates
    2. Classifier chaque assertion (type, langue)
    3. Pour chaque concept, identifier les assertions semantiquement liees
    4. Convertir en Information avec Anchor valide
    """

    def __init__(
        self,
        llm_client=None,
        prompts_path: Optional[Path] = None,
        allow_fallback: bool = False
    ):
        self.llm_client = llm_client
        self.prompts = self._load_prompts(prompts_path)
        self.anchor_validator = AnchorValidator()
        self.allow_fallback = allow_fallback

    def _load_prompts(self, prompts_path: Optional[Path]) -> Dict:
        """Charge les prompts depuis le fichier YAML"""
        import yaml

        if prompts_path is None:
            prompts_path = Path(__file__).parent.parent / "prompts" / "poc_prompts_v2.yaml"

        # Fallback sur l'ancien fichier si v2 n'existe pas
        if not prompts_path.exists():
            prompts_path = Path(__file__).parent.parent / "prompts" / "poc_prompts.yaml"

        with open(prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    # =========================================================================
    # ETAPE 1: EXTRACTION DES ASSERTIONS
    # =========================================================================

    def extract_assertions(
        self,
        chunks: Dict[str, str],
        doc_language: Optional[str] = None
    ) -> List[Assertion]:
        """
        Extrait toutes les assertions du document.

        Une assertion est une phrase/segment qui porte une connaissance:
        - Definition
        - Fait verifiable
        - Regle/contrainte
        - Relation causale
        - etc.

        Args:
            chunks: Dict chunk_id -> texte
            doc_language: Langue du document (detectee si None)

        Returns:
            Liste d'Assertions avec positions exactes
        """
        if not self.llm_client and not self.allow_fallback:
            raise RuntimeError(
                "LLM non disponible et fallback non autorise. "
                "Utilisez allow_fallback=True uniquement pour les tests."
            )

        all_assertions = []

        for chunk_id, text in chunks.items():
            if len(text.strip()) < 50:  # Skip chunks trop courts
                continue

            chunk_assertions = self._extract_assertions_from_chunk(
                chunk_id, text, doc_language
            )
            all_assertions.extend(chunk_assertions)

        return all_assertions

    def _extract_assertions_from_chunk(
        self,
        chunk_id: str,
        text: str,
        doc_language: Optional[str]
    ) -> List[Assertion]:
        """Extrait les assertions d'un chunk unique"""

        if self.llm_client:
            return self._extract_assertions_llm(chunk_id, text, doc_language)
        else:
            return self._extract_assertions_heuristic(chunk_id, text)

    def _extract_assertions_llm(
        self,
        chunk_id: str,
        text: str,
        doc_language: Optional[str]
    ) -> List[Assertion]:
        """Extraction via LLM avec prompt specialise"""

        prompt_config = self.prompts.get("assertion_extraction", {})
        system_prompt = prompt_config.get("system", self._default_assertion_system_prompt())
        user_template = prompt_config.get("user", self._default_assertion_user_prompt())

        # Limiter la taille du texte
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
            return self._parse_assertions_response(response, chunk_id, text)
        except Exception as e:
            print(f"Warning: Assertion extraction failed for {chunk_id}: {e}")
            return self._extract_assertions_heuristic(chunk_id, text)

    def _extract_assertions_heuristic(
        self,
        chunk_id: str,
        text: str
    ) -> List[Assertion]:
        """Extraction heuristique sans LLM"""
        assertions = []

        # Splitter en phrases
        sentences = re.split(r'(?<=[.!?])\s+', text)

        current_pos = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:  # Skip phrases trop courtes
                current_pos = text.find(sentence, current_pos) + len(sentence)
                continue

            # Detecter le type d'assertion par heuristique
            assertion_type = self._detect_assertion_type_heuristic(sentence)

            # Trouver la position exacte
            start = text.find(sentence, current_pos)
            if start == -1:
                start = current_pos
            end = start + len(sentence)
            current_pos = end

            # Detecter la langue
            language = self._detect_language_heuristic(sentence)

            assertions.append(Assertion(
                text=sentence,
                assertion_type=assertion_type,
                chunk_id=chunk_id,
                start_char=start,
                end_char=end,
                confidence=0.5,  # Confiance basse pour heuristique
                language=language
            ))

        return assertions

    def _detect_assertion_type_heuristic(self, sentence: str) -> AssertionType:
        """Detecte le type d'assertion par patterns"""
        s = sentence.lower()

        # Patterns definitionnels
        if any(p in s for p in ['is defined as', 'refers to', 'means', 'est defini', 'designe']):
            return AssertionType.DEFINITIONAL

        # Patterns prescriptifs
        if any(p in s for p in ['must', 'shall', 'required', 'doit', 'obligatoire', 'mandatory']):
            return AssertionType.PRESCRIPTIVE

        # Patterns permissifs
        if any(p in s for p in ['may', 'can', 'possible', 'peut', 'option', 'allowed']):
            return AssertionType.PERMISSIVE

        # Patterns conditionnels
        if any(p in s for p in ['if', 'when', 'unless', 'si', 'lorsque', 'provided that']):
            return AssertionType.CONDITIONAL

        # Patterns causaux
        if any(p in s for p in ['because', 'therefore', 'leads to', 'results in', 'car', 'donc']):
            return AssertionType.CAUSAL

        # Patterns proceduraux
        if any(p in s for p in ['step', 'first', 'then', 'finally', 'etape', 'ensuite']):
            return AssertionType.PROCEDURAL

        # Par defaut: factuel
        return AssertionType.FACTUAL

    def _detect_language_heuristic(self, text: str) -> str:
        """Detecte la langue par heuristique simple"""
        # Mots francais courants
        fr_words = ['le', 'la', 'les', 'de', 'du', 'des', 'est', 'sont', 'pour', 'avec', 'dans']
        # Mots anglais courants
        en_words = ['the', 'is', 'are', 'for', 'with', 'in', 'to', 'of', 'and', 'that']

        words = text.lower().split()
        fr_count = sum(1 for w in words if w in fr_words)
        en_count = sum(1 for w in words if w in en_words)

        if fr_count > en_count:
            return "fr"
        return "en"

    # =========================================================================
    # ETAPE 1.5: FILTRAGE PAR PROMOTION POLICY
    # =========================================================================

    def filter_promotable_assertions(
        self,
        assertions: List[Assertion],
        strict_mode: bool = True
    ) -> Tuple[List[Assertion], Dict[str, int]]:
        """
        Filtre les assertions selon la Promotion Policy.

        Seules les assertions de type ALWAYS ou CONDITIONAL (avec confiance)
        peuvent devenir des Information. Les PROCEDURAL sont exclues.

        Args:
            assertions: Liste des assertions extraites
            strict_mode: Si True, applique ALWAYS uniquement. Si False, inclut CONDITIONAL.

        Returns:
            (assertions_promotables, stats)
        """
        promotable = []
        stats = {
            "total": len(assertions),
            "always": 0,
            "conditional": 0,
            "rarely": 0,
            "never": 0,
            "promoted": 0
        }

        for assertion in assertions:
            tier = PROMOTION_POLICY.get(assertion.assertion_type, PromotionTier.RARELY)

            if tier == PromotionTier.ALWAYS:
                stats["always"] += 1
                promotable.append(assertion)
                stats["promoted"] += 1

            elif tier == PromotionTier.CONDITIONAL:
                stats["conditional"] += 1
                if not strict_mode and assertion.confidence >= 0.7:
                    promotable.append(assertion)
                    stats["promoted"] += 1

            elif tier == PromotionTier.RARELY:
                stats["rarely"] += 1
                if not strict_mode and assertion.confidence >= 0.9:
                    promotable.append(assertion)
                    stats["promoted"] += 1

            else:  # NEVER
                stats["never"] += 1
                # Ne jamais promouvoir

        return promotable, stats

    # =========================================================================
    # ETAPE 2: LIAISON SEMANTIQUE ASSERTIONS <-> CONCEPTS
    # =========================================================================

    def link_assertions_to_concepts(
        self,
        assertions: List[Assertion],
        concepts: List[ConceptSitue]
    ) -> List[ConceptLink]:
        """
        Etablit les liens semantiques entre assertions et concepts.

        IMPORTANT: Ce n'est PAS un matching lexical.
        Le LLM doit RAISONNER sur le sens pour determiner si une assertion
        apporte de la connaissance sur un concept.

        Args:
            assertions: Liste des assertions extraites
            concepts: Liste des concepts identifies

        Returns:
            Liste de ConceptLinks
        """
        if not self.llm_client and not self.allow_fallback:
            raise RuntimeError("LLM requis pour le linking semantique")

        if self.llm_client:
            return self._link_via_llm(assertions, concepts)
        else:
            return self._link_heuristic(assertions, concepts)

    def _link_via_llm(
        self,
        assertions: List[Assertion],
        concepts: List[ConceptSitue]
    ) -> List[ConceptLink]:
        """Linking via raisonnement LLM"""

        prompt_config = self.prompts.get("semantic_linking", {})
        system_prompt = prompt_config.get("system", self._default_linking_system_prompt())
        user_template = prompt_config.get("user", self._default_linking_user_prompt())

        # Preparer les donnees pour le prompt
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
            print(f"Warning: Semantic linking failed: {e}")
            return self._link_heuristic(assertions, concepts)

    def _link_heuristic(
        self,
        assertions: List[Assertion],
        concepts: List[ConceptSitue]
    ) -> List[ConceptLink]:
        """Linking heuristique (fallback)"""
        links = []

        for idx, assertion in enumerate(assertions):
            text_lower = assertion.text.lower()

            for concept in concepts:
                # Verifier si le concept est mentionne (avec variantes)
                concept_variants = self._get_concept_variants(concept.name)

                for variant in concept_variants:
                    if variant.lower() in text_lower:
                        links.append(ConceptLink(
                            assertion_idx=idx,
                            concept_id=concept.id,
                            link_type=self._infer_link_type(assertion.assertion_type),
                            semantic_justification=f"Mention de '{variant}' dans l'assertion",
                            confidence=0.6
                        ))
                        break  # Un seul lien par concept par assertion

        return links

    def _get_concept_variants(self, concept_name: str) -> List[str]:
        """Genere des variantes du nom de concept pour matching"""
        variants = [concept_name]

        # Variantes simples
        variants.append(concept_name.lower())
        variants.append(concept_name.upper())

        # Acronymes possibles
        words = concept_name.split()
        if len(words) > 1:
            acronym = ''.join(w[0].upper() for w in words if w)
            variants.append(acronym)

        # Traductions courantes FR <-> EN
        translations = {
            # GDPR related
            "consentement": ["consent", "agreement"],
            "donnees personnelles": ["personal data", "PII"],
            "sous-traitant": ["processor", "sub-processor"],
            "responsable de traitement": ["controller", "data controller"],
            "droit a l'oubli": ["right to be forgotten", "erasure right"],
            "droit d'acces": ["right of access", "access right"],
            "portabilite": ["portability", "data portability"],
            "privacy by design": ["protection des donnees des la conception"],
            # SAP related
            "customer data cloud": ["cloud donnees client"],
            # General
            "securite": ["security"],
            "conformite": ["compliance"],
        }

        name_lower = concept_name.lower()
        for key, values in translations.items():
            if key in name_lower or name_lower in key:
                variants.extend(values)
            for v in values:
                if v in name_lower or name_lower in v:
                    variants.append(key)

        return list(set(variants))

    def _infer_link_type(self, assertion_type: AssertionType) -> str:
        """Infere le type de lien depuis le type d'assertion"""
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

    # =========================================================================
    # ETAPE 3: CONVERSION EN INFORMATION
    # =========================================================================

    def convert_to_informations(
        self,
        assertions: List[Assertion],
        links: List[ConceptLink],
        concepts: List[ConceptSitue]
    ) -> Tuple[List[Information], Dict[str, List[str]]]:
        """
        Convertit les assertions liees en objets Information.

        Returns:
            (all_informations, concept_to_info_ids)
        """
        all_informations = []
        concept_to_info_ids: Dict[str, List[str]] = {c.id: [] for c in concepts}

        # Grouper les links par assertion
        links_by_assertion: Dict[int, List[ConceptLink]] = {}
        for link in links:
            if link.assertion_idx not in links_by_assertion:
                links_by_assertion[link.assertion_idx] = []
            links_by_assertion[link.assertion_idx].append(link)

        # Creer une Information pour chaque assertion liee
        for idx, assertion in enumerate(assertions):
            assertion_links = links_by_assertion.get(idx, [])

            if not assertion_links:
                continue  # Assertion non liee a aucun concept

            # Convertir le type d'assertion en InfoType
            info_type = self._assertion_to_info_type(assertion.assertion_type)

            # Creer l'anchor
            anchor = Anchor(
                chunk_id=assertion.chunk_id,
                start_char=assertion.start_char,
                end_char=assertion.end_char
            )

            # Collecter tous les concepts lies
            concept_refs = [link.concept_id for link in assertion_links]

            # Determiner le theme (depuis le premier concept)
            theme_ref = ""
            for link in assertion_links:
                for concept in concepts:
                    if concept.id == link.concept_id:
                        theme_ref = concept.theme_ref
                        break
                if theme_ref:
                    break

            info = Information(
                info_type=info_type,
                anchor=anchor,
                concept_refs=concept_refs,
                theme_ref=theme_ref
            )

            all_informations.append(info)

            # Enregistrer le lien concept -> info
            for concept_id in concept_refs:
                if concept_id in concept_to_info_ids:
                    concept_to_info_ids[concept_id].append(info.id)

        return all_informations, concept_to_info_ids

    def _assertion_to_info_type(self, assertion_type: AssertionType) -> InfoType:
        """Convertit AssertionType en InfoType"""
        mapping = {
            AssertionType.DEFINITIONAL: InfoType.DEFINITION,
            AssertionType.FACTUAL: InfoType.FACT,
            AssertionType.PRESCRIPTIVE: InfoType.CONSTRAINT,
            AssertionType.PERMISSIVE: InfoType.OPTION,
            AssertionType.CONDITIONAL: InfoType.CONDITION,
            AssertionType.CAUSAL: InfoType.CONSEQUENCE,
            AssertionType.COMPARATIVE: InfoType.FACT,
            AssertionType.PROCEDURAL: InfoType.CAPABILITY,
        }
        return mapping.get(assertion_type, InfoType.FACT)

    # =========================================================================
    # API PRINCIPALE
    # =========================================================================

    def extract_all(
        self,
        concepts: List[ConceptSitue],
        chunks: Dict[str, str],
        strict_promotion: bool = True
    ) -> Tuple[List[Information], Dict[str, List[str]]]:
        """
        API principale - compatible avec l'ancien InformationExtractor.

        Pipeline complet:
        1. Extraire les assertions du texte
        1.5. Filtrer par Promotion Policy (NOUVEAU)
        2. Lier semantiquement aux concepts
        3. Convertir en Information avec Anchors

        Args:
            concepts: Liste des ConceptSitue identifies
            chunks: Dictionnaire chunk_id -> texte
            strict_promotion: Si True, seules ALWAYS sont promues. Si False, inclut CONDITIONAL.

        Returns:
            (all_informations, concept_to_info_ids)
        """
        # Etape 1: Extraire les assertions
        all_assertions = self.extract_assertions(chunks)
        print(f"  [SemanticExtractor] {len(all_assertions)} assertions extraites")

        # Etape 1.5: Filtrer par Promotion Policy
        promotable_assertions, promo_stats = self.filter_promotable_assertions(
            all_assertions, strict_mode=strict_promotion
        )
        print(f"  [SemanticExtractor] Promotion Policy: "
              f"{promo_stats['always']} ALWAYS, "
              f"{promo_stats['conditional']} CONDITIONAL, "
              f"{promo_stats['never']} PROCEDURAL (exclues)")
        print(f"  [SemanticExtractor] {len(promotable_assertions)} assertions promotables")

        # Etape 2: Lier aux concepts (uniquement les promotables)
        links = self.link_assertions_to_concepts(promotable_assertions, concepts)
        print(f"  [SemanticExtractor] {len(links)} liens semantiques etablis")

        # Etape 3: Convertir en Information
        informations, concept_to_info_ids = self.convert_to_informations(
            promotable_assertions, links, concepts
        )

        # Valider les anchors
        valid_informations = []
        for info in informations:
            is_valid, _ = self.anchor_validator.validate_single(info.anchor, chunks)
            if is_valid:
                valid_informations.append(info)

        # Recalculer concept_to_info_ids avec les infos valides seulement
        valid_ids = {info.id for info in valid_informations}
        filtered_mapping = {
            cid: [iid for iid in iids if iid in valid_ids]
            for cid, iids in concept_to_info_ids.items()
        }

        print(f"  [SemanticExtractor] {len(valid_informations)} Information valides")

        return valid_informations, filtered_mapping

    # =========================================================================
    # PROMPTS PAR DEFAUT
    # =========================================================================

    def _default_assertion_system_prompt(self) -> str:
        return """Tu es un expert en extraction d'assertions.
Une ASSERTION est une phrase ou segment qui porte une connaissance:
- Definition (ce qu'est quelque chose)
- Fait (information verifiable)
- Regle/Contrainte (obligation, interdiction)
- Possibilite (option, permission)
- Condition (si... alors...)
- Cause/Consequence (A entraine B)

Tu dois identifier les assertions et leur type dans le texte fourni.
Retourne les positions EXACTES dans le texte (start_char, end_char).

IMPORTANT: Detecte aussi la LANGUE de chaque assertion (en, fr, de, etc.)."""

    def _default_assertion_user_prompt(self) -> str:
        return """Extrait les assertions de ce texte.

CHUNK_ID: {chunk_id}
LANGUE ATTENDUE: {language_hint}

TEXTE:
{text}

Reponds UNIQUEMENT avec ce JSON:
```json
{{
  "assertions": [
    {{
      "text": "Le texte exact de l'assertion",
      "type": "definitional|factual|prescriptive|permissive|conditional|causal|procedural",
      "start_char": 145,
      "end_char": 287,
      "confidence": 0.9,
      "language": "en"
    }}
  ]
}}
```"""

    def _default_linking_system_prompt(self) -> str:
        return """Tu es un expert en raisonnement semantique.
Tu dois determiner quelles ASSERTIONS apportent de la connaissance sur quels CONCEPTS.

IMPORTANT - Ce n'est PAS un matching lexical:
- Une assertion peut concerner un concept sans le mentionner explicitement
- Un concept en francais peut etre lie a une assertion en anglais (et vice versa)
- Le lien doit etre SEMANTIQUE (le sens), pas lexical (les mots)

Types de liens:
- defines: L'assertion definit le concept
- describes: L'assertion decrit une propriete du concept
- constrains: L'assertion impose une contrainte sur le concept
- enables: L'assertion dit ce que le concept permet
- conditions: L'assertion specifie une condition pour le concept
- causes: L'assertion decrit un effet du concept

Tu DOIS justifier chaque lien semantiquement."""

    def _default_linking_user_prompt(self) -> str:
        return """Etablis les liens semantiques entre ces assertions et ces concepts.

ASSERTIONS:
{assertions}

CONCEPTS:
{concepts}

Reponds UNIQUEMENT avec ce JSON:
```json
{{
  "links": [
    {{
      "assertion_idx": 0,
      "concept_id": "abc123",
      "link_type": "defines|describes|constrains|enables|conditions|causes",
      "justification": "Pourquoi cette assertion concerne ce concept"
    }}
  ],
  "unlinked_assertions": [
    {{
      "idx": 5,
      "reason": "Cette assertion ne concerne aucun des concepts identifies"
    }}
  ]
}}
```"""

    def _format_assertions_for_prompt(self, assertions: List[Assertion]) -> str:
        """Formate les assertions pour le prompt"""
        lines = []
        for idx, a in enumerate(assertions[:30]):  # Limiter a 30 assertions
            lines.append(f"[{idx}] ({a.language}) {a.text[:200]}")
        return "\n".join(lines)

    def _format_concepts_for_prompt(self, concepts: List[ConceptSitue]) -> str:
        """Formate les concepts pour le prompt"""
        lines = []
        for c in concepts[:20]:  # Limiter a 20 concepts
            lines.append(f"- {c.id}: {c.name} ({c.role.value})")
        return "\n".join(lines)

    def _parse_assertions_response(
        self,
        response: str,
        chunk_id: str,
        original_text: str
    ) -> List[Assertion]:
        """Parse la reponse JSON des assertions"""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            assertions = []

            for a_data in data.get("assertions", []):
                try:
                    # Mapper le type
                    type_str = a_data.get("type", "factual").lower()
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
                    assertion_type = type_mapping.get(type_str, AssertionType.FACTUAL)

                    assertions.append(Assertion(
                        text=a_data.get("text", ""),
                        assertion_type=assertion_type,
                        chunk_id=chunk_id,
                        start_char=a_data.get("start_char", 0),
                        end_char=a_data.get("end_char", 0),
                        confidence=a_data.get("confidence", 0.8),
                        language=a_data.get("language", "en")
                    ))
                except Exception as e:
                    print(f"Warning: Invalid assertion data: {e}")
                    continue

            return assertions

        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse assertions JSON: {e}")
            return self._extract_assertions_heuristic(chunk_id, original_text)

    def _parse_links_response(
        self,
        response: str,
        assertions: List[Assertion],
        concepts: List[ConceptSitue]
    ) -> List[ConceptLink]:
        """Parse la reponse JSON des liens"""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            links = []

            # Construire un set de concept_ids valides
            valid_concept_ids = {c.id for c in concepts}

            for l_data in data.get("links", []):
                try:
                    assertion_idx = l_data.get("assertion_idx", -1)
                    concept_id = l_data.get("concept_id", "")

                    # Valider
                    if assertion_idx < 0 or assertion_idx >= len(assertions):
                        continue
                    if concept_id not in valid_concept_ids:
                        continue

                    links.append(ConceptLink(
                        assertion_idx=assertion_idx,
                        concept_id=concept_id,
                        link_type=l_data.get("link_type", "relates_to"),
                        semantic_justification=l_data.get("justification", ""),
                        confidence=l_data.get("confidence", 0.8)
                    ))
                except Exception as e:
                    print(f"Warning: Invalid link data: {e}")
                    continue

            return links

        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse links JSON: {e}")
            return self._link_heuristic(assertions, concepts)
