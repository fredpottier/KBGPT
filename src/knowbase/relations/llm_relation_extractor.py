# Phase 2 OSMOSE - LLM-First Relation Extraction
# Architecture robuste basée sur gpt-4o-mini
# Phase 2.8 - Support predicate_raw + flags pour RawAssertion
# Phase 2.8+ - ID-First Extraction avec index c1, c2... (version définitive)

import logging
import json
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from knowbase.relations.types import (
    RelationType,
    TypedRelation,
    RelationMetadata,
    ExtractionMethod,
    RelationStrength,
    RelationStatus,
    # Phase 2.8
    RawAssertionFlags,
    # Phase 2.10
    RelationMaturity,
)
from knowbase.common.llm_router import LLMRouter, TaskType

logger = logging.getLogger(__name__)


# =============================================================================
# Phase 2.8+ - Dataclasses pour résultats ID-First
# =============================================================================

@dataclass
class UnresolvedMention:
    """Mention d'entité non trouvée dans le catalogue."""
    mention: str
    context: str
    suggested_type: Optional[str] = None


@dataclass
class ExtractedRelationV3:
    """Relation extraite avec IDs résolus (post index→concept_id mapping)."""
    subject_concept_id: str
    object_concept_id: str
    predicate_raw: str
    evidence: str
    confidence: float
    flags: RawAssertionFlags
    subject_surface_form: str
    object_surface_form: str


@dataclass
class IDFirstExtractionResult:
    """Résultat complet de l'extraction ID-First (Phase 2.8+)."""
    relations: List[ExtractedRelationV3] = field(default_factory=list)
    unresolved_mentions: List[UnresolvedMention] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


# =============================================================================
# Phase 2.10 - Type-First Extraction (Closed Set + Multi-Sourcing)
# =============================================================================

# Les 12 types Core domain-agnostic pour V4
CORE_RELATION_TYPES_V4 = {
    "PART_OF", "SUBTYPE_OF",  # Structurel
    "REQUIRES", "ENABLES", "USES", "INTEGRATES_WITH", "APPLIES_TO",  # Dépendance
    "CAUSES", "PREVENTS",  # Causalité
    "VERSION_OF", "REPLACES",  # Temporel
    "ASSOCIATED_WITH",  # Fallback
}


@dataclass
class ExtractedRelationV4:
    """
    Relation extraite Phase 2.10 - Type-First avec set fermé.

    Nouveaux champs vs V3:
    - relation_type: Type forcé parmi les 12 Core
    - type_confidence: Confiance LLM sur le type
    - alt_type: Type alternatif si ambiguïté
    - alt_type_confidence: Confiance sur l'alternatif
    - relation_subtype_raw: Nuance sémantique fine (audit only)
    - context_hint: Scope/contexte local
    """
    # Identité relation
    subject_concept_id: str
    object_concept_id: str

    # Type forcé (Phase 2.10)
    relation_type: RelationType
    type_confidence: float
    alt_type: Optional[RelationType] = None
    alt_type_confidence: Optional[float] = None

    # Prédicat brut (pour audit)
    predicate_raw: str = ""
    relation_subtype_raw: Optional[str] = None

    # Evidence
    evidence: str = ""
    evidence_start_char: Optional[int] = None
    evidence_end_char: Optional[int] = None
    context_hint: Optional[str] = None

    # Scores
    confidence: float = 0.7  # Confidence extraction globale

    # Flags sémantiques
    flags: RawAssertionFlags = field(default_factory=RawAssertionFlags)

    # Surface forms
    subject_surface_form: str = ""
    object_surface_form: str = ""


@dataclass
class TypeFirstExtractionResult:
    """Résultat complet de l'extraction Type-First (Phase 2.10)."""
    relations: List[ExtractedRelationV4] = field(default_factory=list)
    unresolved_mentions: List[UnresolvedMention] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Phase 2.8 - Nouveau prompt avec predicate_raw + flags
# =============================================================================

RELATION_EXTRACTION_PROMPT_V2 = """Tu es un expert en extraction de relations sémantiques entre concepts.

CONTEXTE DU DOCUMENT:
{full_text_excerpt}

CONCEPTS IDENTIFIÉS:
{concepts_list}

INSTRUCTIONS:
Analyse le contexte pour identifier TOUTES les relations entre les concepts.
Pour chaque relation, extrais:

1. **predicate_raw**: Le verbe/prédicat EXACT tel qu'il apparaît dans le texte
   - Exemples: "requires", "uses", "integrates with", "is part of", "enables", "governs"
   - NE PAS normaliser ou interpréter, garder la forme exacte

2. **subject_concept**: Le concept SOURCE de la relation (celui qui agit/possède)
3. **object_concept**: Le concept CIBLE de la relation (celui qui reçoit/est affecté)

4. **evidence**: Citation EXACTE du texte justifiant la relation (phrase complète)

5. **confidence**: Score 0.0-1.0 (ta confiance dans cette relation)
   - 0.95+: Relation explicite, évidente
   - 0.80-0.94: Relation claire mais contexte nécessaire
   - 0.65-0.79: Relation implicite mais probable
   - <0.65: Relation incertaine

6. **flags** (tous booléens):
   - is_negated: true si la relation est NIÉE ("ne nécessite PAS", "n'utilise pas")
   - is_hedged: true si incertitude exprimée ("peut nécessiter", "pourrait utiliser", "might")
   - is_conditional: true si condition ("si X alors", "when", "in case of")
   - cross_sentence: true si la relation traverse plusieurs phrases

EXEMPLES DE SORTIE:

Texte: "NIS2 requires essential entities to implement risk management."
→ predicate_raw: "requires"
→ subject: "NIS2"
→ object: "risk management"
→ flags: {{is_negated: false, is_hedged: false, is_conditional: false, cross_sentence: false}}

Texte: "GDPR may apply to certain organizations processing personal data."
→ predicate_raw: "may apply to"
→ is_hedged: true

Texte: "S/4HANA does not require on-premise deployment."
→ predicate_raw: "does not require"
→ is_negated: true

Réponds UNIQUEMENT en JSON valide:
```json
{{
  "relations": [
    {{
      "subject_concept": "NIS2",
      "object_concept": "risk management",
      "predicate_raw": "requires",
      "evidence": "NIS2 requires essential entities to implement risk management.",
      "confidence": 0.95,
      "flags": {{
        "is_negated": false,
        "is_hedged": false,
        "is_conditional": false,
        "cross_sentence": false
      }}
    }}
  ]
}}
```

Si aucune relation détectée, réponds: {{"relations": []}}
"""

# =============================================================================
# Phase 2.8+ - Prompt V3 ID-First avec index (c1, c2...) - VERSION DÉFINITIVE
# =============================================================================

RELATION_EXTRACTION_PROMPT_V3 = """Tu es un expert en extraction de relations sémantiques entre concepts.

CONTEXTE DU DOCUMENT (extrait) :
{full_text_excerpt}

CATALOGUE DE CONCEPTS AUTORISÉS (ensemble fermé) :
{concept_catalog_json}

RÈGLES STRICTES - À RESPECTER IMPÉRATIVEMENT :

1) subject_id et object_id = UNIQUEMENT des index du catalogue (c1, c2, c3, etc.)
2) Si une entité mentionnée dans le texte N'EST PAS dans le catalogue :
   → NE CRÉE PAS de relation avec elle
   → AJOUTE-LA dans "unresolved_mentions"
3) predicate_raw = verbe/prédicat EXACT tel qu'il apparaît dans le texte
4) evidence = citation EXACTE du texte (copier-coller, pas de paraphrase)
5) Retourne UNIQUEMENT un JSON valide. Pas de texte avant ou après.

DÉTECTION DES FLAGS :
- is_negated: true si relation niée ("ne nécessite PAS", "n'utilise pas", "does not require")
- is_hedged: true si incertitude ("peut nécessiter", "pourrait", "might", "may")
- is_conditional: true si condition ("si X alors", "when", "in case of")
- cross_sentence: true si la relation traverse plusieurs phrases

FORMAT DE SORTIE JSON :
{{
  "relations": [
    {{
      "subject_id": "c1",
      "object_id": "c2",
      "predicate_raw": "requires compliance with",
      "evidence": "EDPB requires compliance with GDPR for all EU organizations.",
      "confidence": 0.95,
      "flags": {{
        "is_negated": false,
        "is_hedged": false,
        "is_conditional": false,
        "cross_sentence": false
      }}
    }}
  ],
  "unresolved_mentions": [
    {{
      "mention": "ISO 27001",
      "context": "GDPR compliance may also require ISO 27001 certification.",
      "suggested_type": "standard"
    }}
  ]
}}

Si aucune relation détectée : {{"relations": [], "unresolved_mentions": []}}
"""

# =============================================================================
# Phase 2.10 - Prompt V4 Type-First (Closed Set Domain-Agnostic)
# =============================================================================

RELATION_EXTRACTION_V4_SYSTEM_PROMPT = """You are OSMOSE Relation Extractor (V4).

Goal:
Extract factual relations between concepts from a text segment, using a CLOSED, domain-agnostic set of relation types.
You must be strict and conservative. Do not invent facts. Do not infer unstated relations.

You will be given:
1) A text segment (evidence source)
2) A catalog of concepts with IDs (c1, c2, ...), labels, and optional metadata.

Hard constraints:
- You may ONLY use the provided concept IDs as subject/object (no new concepts).
- Output must be ONLY valid JSON (no markdown, no commentary).
- Every relation MUST have an evidence snippet from the text (verbatim or near-verbatim).
- If the text does not explicitly support a relation, do NOT output it.

Relation types (choose exactly ONE primary type):
STRUCTURAL
- PART_OF         (A is part of B / contained in B / belongs to B)
- SUBTYPE_OF      (A is a type/kind/subclass of B)

DEPENDENCY / FUNCTIONAL
- REQUIRES        (A requires/needs B to function/comply/occur)
- ENABLES         (A enables/allows/supports B)
- USES            (A uses/utilizes/leverages B)
- INTEGRATES_WITH (A integrates/interoperates/connects with B)
- APPLIES_TO      (A applies to/governs/regulates/targets B)

CAUSALITY / CONSTRAINT
- CAUSES          (A causes/leads to/results in B)
- PREVENTS        (A prevents/prohibits/blocks B)

TEMPORAL / EVOLUTION
- VERSION_OF      (A is a version/variant of B)
- REPLACES        (A replaces/supersedes B)

FALLBACK
- ASSOCIATED_WITH (weak association; only if nothing stronger fits AND the text clearly links them)

Typing requirements:
- Also return predicate_raw: the exact wording used in the text that expressed the relation (as close as possible).
- Return type_confidence for the chosen relation_type between 0 and 1.
- Optionally provide alt_type (one alternative relation_type) ONLY if ambiguity is real and supported; also include alt_type_confidence.
- Optionally provide relation_subtype_raw for semantic nuance (e.g., "requires compliance with").
- Optionally provide context_hint if the relation has a specific scope (e.g., "for medical devices").

Anti-junk rules (very important):
- Do NOT output relations where subject or object is:
  (a) a purely structural reference (e.g., "Article 12", "Annex III", "Chapter IV", "Section 3", "Recital 28"),
  (b) a generic vague term used without a concrete role (e.g., "Health", "Justice", "Market", "Guidance"), unless the text clearly makes it a specific entity or defined concept.
- Do NOT output "includes/contains" as relations unless it truly expresses PART_OF and the components are meaningful concepts.
- Do NOT output relations that are only list co-occurrence (A and B mentioned in the same list) without a connective claim.

Negation / modality / conditions:
For each relation, set flags:
- is_negated: true if the text asserts the negation (e.g., "does not require", "shall not")
- is_hedged: true if uncertain (e.g., "may", "might", "can", "could", "typically")
- is_conditional: true if conditional (e.g., "if/when/in case/subject to")
- cross_sentence: true ONLY if the relation needs more than one sentence to be explicit (otherwise false)

Evidence:
- evidence must be a short snippet that directly supports the relation (15-40 words recommended).
- Provide evidence_start_char and evidence_end_char as offsets into the provided text segment IF possible; otherwise set them to null.

Deduplication:
- Do not repeat exact duplicates (same subject_id, relation_type, object_id, and same negation flag).

Directionality:
- Preserve direction: "A requires B" => subject=A, object=B.
- If the sentence is passive, normalize direction logically (e.g., "B is required by A" => A REQUIRES B).

If no valid relations exist, return {"relations": []}.
"""

RELATION_EXTRACTION_V4_USER_PROMPT = """Extract relations between the concepts from the text.

TEXT:
{text_segment}

CONCEPT CATALOG (use ONLY these IDs):
{concept_catalog_json}

Output ONLY valid JSON following this schema:
{{
  "relations": [
    {{
      "subject_id": "c1",
      "object_id": "c2",
      "relation_type": "REQUIRES",
      "type_confidence": 0.92,
      "alt_type": "ENABLES",
      "alt_type_confidence": 0.58,
      "predicate_raw": "requires",
      "relation_subtype_raw": "requires compliance with",
      "flags": {{
        "is_negated": false,
        "is_hedged": false,
        "is_conditional": true,
        "cross_sentence": false
      }},
      "context_hint": "for medical devices",
      "evidence": "If the provider places the system on the market, it requires appropriate risk management measures.",
      "evidence_start_char": 1280,
      "evidence_end_char": 1386
    }}
  ],
  "unresolved_mentions": [
    {{
      "mention": "ISO 27001",
      "context": "GDPR compliance may also require ISO 27001 certification.",
      "suggested_type": "standard"
    }}
  ]
}}
"""

# =============================================================================
# Legacy prompt (Phase 2.7 compatibility)
# =============================================================================

RELATION_EXTRACTION_PROMPT = """Tu es un expert en extraction de relations sémantiques entre concepts.

CONTEXTE DU DOCUMENT:
{full_text_excerpt}

CONCEPTS IDENTIFIÉS:
{concepts_list}

TYPES DE RELATIONS POSSIBLES:
1. PART_OF: A est un composant/partie de B (ex: "Fiori fait partie de S/4HANA")
2. SUBTYPE_OF: A est un sous-type de B (ex: "S/4HANA Cloud est un type d'ERP")
3. REQUIRES: A nécessite B (obligatoire) (ex: "S/4HANA requiert HANA")
4. USES: A utilise B (optionnel) (ex: "HANA est chiffré en AES256")
5. INTEGRATES_WITH: A s'intègre avec B (ex: "SAP intègre Salesforce")
6. VERSION_OF: A est une version de B (ex: "CCR 2023 version de CCR")
7. PRECEDES: A précède B chronologiquement (ex: "CCR 2022 avant CCR 2023")
8. REPLACES: A remplace B (ex: "S/4HANA remplace ECC")
9. DEPRECATES: A rend B obsolète (ex: "HANA Cloud déprécie HANA on-premise")

INSTRUCTIONS:
- Analyse le contexte pour identifier TOUTES les relations entre les concepts
- Pour chaque relation, fournis:
  * source_concept: ID du concept source
  * target_concept: ID du concept cible
  * relation_type: Type parmi les 9 ci-dessus
  * confidence: Score 0.0-1.0 (ta confiance dans cette relation)
  * evidence: Citation exacte du texte qui justifie la relation
  * metadata: Informations contextuelles (optionnel si applicable, force, contexte technique, etc.)

IMPORTANT:
- Ne crée une relation QUE si elle est explicite ou fortement implicite dans le texte
- Si "ne nécessite PAS", "incompatible", etc. → ne crée PAS de relation
- "peut utiliser" → USES avec strength=WEAK
- "nécessite" → REQUIRES (obligatoire)
- Attention aux négations et conditions

Réponds UNIQUEMENT en JSON valide (array de relations):
```json
[
  {{
    "source_concept": "concept-id-1",
    "target_concept": "concept-id-2",
    "relation_type": "USES",
    "confidence": 0.92,
    "evidence": "la base HANA est chiffrée au repos en AES256",
    "metadata": {{
      "context": "encryption",
      "scope": "at_rest",
      "strength": "STRONG"
    }}
  }}
]
```

Si aucune relation détectée, réponds: []
"""


class LLMRelationExtractor:
    """
    Extraction LLM-first de relations typées.

    Stratégie:
    1. Pre-filtering: Co-occurrence concepts (réduire coût LLM)
    2. LLM extraction: gpt-4o-mini analyse contexte
    3. Post-processing: Validation + metadata enrichment

    Phase 2 OSMOSE - Architecture robuste
    Phase 2.8 - Support predicate_raw + flags pour RawAssertion
    Phase 2.8+ - ID-First extraction avec index c1, c2... (version définitive)
    """

    def __init__(
        self,
        llm_router: Optional[LLMRouter] = None,
        model: str = "gpt-4o-mini",
        max_context_chars: int = 8000,
        co_occurrence_window: int = 150,
        use_v2_prompt: bool = True,  # Phase 2.8: utiliser prompt V2 (predicate_raw + flags)
        use_id_first: bool = True  # Phase 2.8+: ID-First avec index c1, c2... (DÉFAUT)
    ):
        """
        Initialise LLM extractor.

        Args:
            llm_router: Router LLM (default: nouveau instance)
            model: Modèle à utiliser (default: gpt-4o-mini - bon rapport qualité/prix)
            max_context_chars: Taille max contexte envoyé au LLM
            co_occurrence_window: Fenêtre caractères pour co-occurrence
            use_v2_prompt: Phase 2.8 - Utiliser prompt V2 (predicate_raw + flags)
            use_id_first: Phase 2.8+ - Utiliser ID-First avec index (c1, c2...) - RECOMMANDÉ
        """
        self.llm_router = llm_router or LLMRouter()
        self.model = model
        self.max_context_chars = max_context_chars
        self.co_occurrence_window = co_occurrence_window
        self.use_v2_prompt = use_v2_prompt
        self.use_id_first = use_id_first

        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Initialized "
            f"(model={model}, max_context={max_context_chars}, id_first={use_id_first})"
        )

    def extract_relations(
        self,
        concepts: List[Dict[str, Any]],
        full_text: str,
        document_id: str,
        document_name: str,
        chunk_ids: Optional[List[str]] = None
    ) -> List[TypedRelation]:
        """
        Extraire relations via LLM (gpt-4o-mini).

        Pipeline:
        1. Pre-filtering: Identifier paires concepts co-occurrentes
        2. Chunking: Découper texte si trop long (max_context_chars)
        3. LLM extraction: Envoyer au LLM pour analyse
        4. Post-processing: Parser JSON + créer TypedRelation

        Args:
            concepts: Liste concepts canoniques
            full_text: Texte complet document
            document_id: ID document
            document_name: Nom document
            chunk_ids: IDs chunks Qdrant (optionnel)

        Returns:
            Liste relations extraites
        """
        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Extracting from {len(concepts)} concepts, "
            f"{len(full_text)} chars"
        )

        # Étape 1: Pre-filtering - Trouver paires concepts co-occurrentes
        concept_pairs = self._find_cooccurring_concepts(concepts, full_text)

        if not concept_pairs:
            logger.info("[OSMOSE:LLMRelationExtractor] No co-occurring concept pairs found")
            return []

        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Found {len(concept_pairs)} "
            f"co-occurring concept pairs"
        )

        # Étape 2: Chunking si texte trop long
        text_chunks = self._chunk_text_if_needed(full_text, concepts)

        # Étape 3: LLM extraction par chunk (PARALLÈLE avec 8 workers)
        max_workers = 8
        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Processing {len(text_chunks)} chunks "
            f"in PARALLEL with {max_workers} workers (OPTIMIZED for speed)"
        )

        all_relations = []

        # Extraction parallèle avec ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Soumettre tous les chunks en parallèle
            future_to_chunk = {
                executor.submit(
                    self._extract_from_chunk,
                    chunk_data=chunk_data,
                    document_id=document_id,
                    document_name=document_name,
                    chunk_ids=chunk_ids
                ): (chunk_idx, chunk_data)
                for chunk_idx, chunk_data in enumerate(text_chunks)
            }

            # Récupérer résultats au fur et à mesure (as_completed pour logs temps réel)
            completed = 0
            for future in as_completed(future_to_chunk):
                chunk_idx, chunk_data = future_to_chunk[future]
                completed += 1

                try:
                    chunk_relations = future.result()
                    all_relations.extend(chunk_relations)

                    logger.info(
                        f"[OSMOSE:LLMRelationExtractor] ✅ Chunk {chunk_idx + 1}/{len(text_chunks)} "
                        f"completed ({completed}/{len(text_chunks)} done) - "
                        f"Extracted {len(chunk_relations)} relations"
                    )
                except Exception as e:
                    logger.error(
                        f"[OSMOSE:LLMRelationExtractor] ❌ Chunk {chunk_idx + 1} failed: {e}",
                        exc_info=True
                    )

        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Parallel extraction completed: "
            f"{len(all_relations)} total relations from {len(text_chunks)} chunks"
        )

        # Étape 4: Déduplication (même relation peut apparaître dans plusieurs chunks)
        deduplicated = self._deduplicate_relations(all_relations)

        logger.info(
            f"[OSMOSE:LLMRelationExtractor] ✅ Extracted {len(deduplicated)} relations "
            f"(after deduplication from {len(all_relations)})"
        )

        return deduplicated

    def _find_cooccurring_concepts(
        self,
        concepts: List[Dict[str, Any]],
        full_text: str
    ) -> List[Tuple[Dict, Dict, str]]:
        """
        Trouver paires concepts mentionnés proches (co-occurrence).

        Stratégie:
        - Fenêtre glissante de N caractères
        - Si 2+ concepts dans fenêtre → candidats relation

        Returns:
            [(concept_A, concept_B, context_snippet), ...]
        """
        pairs = []
        text_lower = full_text.lower()

        # Pour chaque concept, trouver toutes ses mentions dans le texte
        concept_mentions = []
        for concept in concepts:
            # Fix 2025-10-20: Skip concepts avec canonical_name None
            canonical_name = concept.get("canonical_name")
            if not canonical_name:
                logger.warning(
                    f"[LLMRelationExtractor] Skipping concept with None canonical_name: {concept}"
                )
                continue

            # Chercher canonical_name
            canonical = canonical_name.lower()
            start = 0
            while True:
                pos = text_lower.find(canonical, start)
                if pos == -1:
                    break
                concept_mentions.append({
                    "concept": concept,
                    "position": pos,
                    "length": len(canonical),
                    "text": canonical
                })
                start = pos + 1

            # Chercher surface_forms
            for form in concept.get("surface_forms", []):
                if not form:  # Skip empty surface forms
                    continue
                form_lower = form.lower()
                start = 0
                while True:
                    pos = text_lower.find(form_lower, start)
                    if pos == -1:
                        break
                    concept_mentions.append({
                        "concept": concept,
                        "position": pos,
                        "length": len(form_lower),
                        "text": form_lower
                    })
                    start = pos + 1

        # Trier par position
        concept_mentions.sort(key=lambda x: x["position"])

        # Trouver paires dans fenêtre de co-occurrence
        for i, mention_a in enumerate(concept_mentions):
            for mention_b in concept_mentions[i + 1:]:
                # Distance entre les deux mentions
                distance = mention_b["position"] - (mention_a["position"] + mention_a["length"])

                if distance > self.co_occurrence_window:
                    break  # Trop loin, passer à mention suivante

                # Vérifier que ce sont des concepts différents (utiliser canonical_name, concept_id peut être None)
                name_a = mention_a["concept"].get("canonical_name", "").lower()
                name_b = mention_b["concept"].get("canonical_name", "").lower()
                if name_a and name_b and name_a != name_b:
                    # Extraire contexte
                    context_start = max(0, mention_a["position"] - 20)
                    context_end = min(len(full_text), mention_b["position"] + mention_b["length"] + 20)
                    context = full_text[context_start:context_end]

                    pairs.append((
                        mention_a["concept"],
                        mention_b["concept"],
                        context
                    ))

        # Déduplication (même paire peut apparaître plusieurs fois)
        # Utiliser canonical_name comme clé (concept_id peut être None si pas encore stocké en Neo4j)
        unique_pairs = []
        seen = set()
        for concept_a, concept_b, context in pairs:
            name_a = concept_a.get("canonical_name", "")
            name_b = concept_b.get("canonical_name", "")
            if not name_a or not name_b:
                continue
            pair_key = tuple(sorted([name_a.lower(), name_b.lower()]))
            if pair_key not in seen:
                seen.add(pair_key)
                unique_pairs.append((concept_a, concept_b, context))

        return unique_pairs

    def _chunk_text_if_needed(
        self,
        full_text: str,
        concepts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Découper texte en chunks si trop long pour LLM.

        Returns:
            [{"text": chunk_text, "concepts": concepts_in_chunk}, ...]
        """
        if len(full_text) <= self.max_context_chars:
            # Texte assez court, un seul chunk
            return [{"text": full_text, "concepts": concepts}]

        # TODO: Implémenter chunking intelligent (par paragraphes, etc.)
        # Pour l'instant, simple découpage
        chunks = []
        chunk_size = self.max_context_chars
        overlap = 200  # Overlap pour éviter de couper relations

        for i in range(0, len(full_text), chunk_size - overlap):
            chunk_text = full_text[i:i + chunk_size]

            # Filtrer concepts présents dans ce chunk
            chunk_concepts = [
                c for c in concepts
                if c["canonical_name"].lower() in chunk_text.lower()
                or any(f.lower() in chunk_text.lower() for f in c.get("surface_forms", []))
            ]

            if chunk_concepts:
                chunks.append({
                    "text": chunk_text,
                    "concepts": chunk_concepts
                })

        return chunks

    def _extract_from_chunk(
        self,
        chunk_data: Dict[str, Any],
        document_id: str,
        document_name: str,
        chunk_ids: Optional[List[str]] = None
    ) -> List[TypedRelation]:
        """
        Extraire relations d'un chunk via LLM.
        """
        chunk_text = chunk_data["text"]
        chunk_concepts = chunk_data["concepts"]

        # Formater concepts pour prompt (utiliser canonical_name comme identifiant principal)
        concepts_list = "\n".join([
            f"- {c.get('canonical_name', 'UNKNOWN')} ({c.get('concept_type', 'UNKNOWN')})"
            for c in chunk_concepts
            if c.get('canonical_name')  # Skip concepts sans nom
        ])

        # Construire prompt (V2 ou legacy selon config)
        prompt_template = RELATION_EXTRACTION_PROMPT_V2 if self.use_v2_prompt else RELATION_EXTRACTION_PROMPT
        prompt = prompt_template.format(
            full_text_excerpt=chunk_text,
            concepts_list=concepts_list
        )

        # Appel LLM via LLMRouter
        try:
            response_text = self.llm_router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,  # Bas pour cohérence
                response_format={"type": "json_object"},  # Force JSON
                model_preference=self.model  # Préférence pour gpt-4o-mini
            )

            # Parser JSON response
            relations_data = json.loads(response_text)

            # Si LLM retourne objet avec clé "relations"
            if isinstance(relations_data, dict) and "relations" in relations_data:
                relations_data = relations_data["relations"]

            # Créer TypedRelation pour chaque relation
            relations = []
            for rel_data in relations_data:
                if self.use_v2_prompt:
                    relation = self._create_relation_from_llm_v2(
                        rel_data=rel_data,
                        concepts=chunk_concepts,
                        document_id=document_id,
                        document_name=document_name,
                        chunk_ids=chunk_ids
                    )
                else:
                    relation = self._create_relation_from_llm(
                        rel_data=rel_data,
                        concepts=chunk_concepts,
                        document_id=document_id,
                        document_name=document_name,
                        chunk_ids=chunk_ids
                    )
                if relation:
                    relations.append(relation)

            logger.info(
                f"[OSMOSE:LLMRelationExtractor] LLM extracted {len(relations)} relations "
                f"from chunk (v2={self.use_v2_prompt})"
            )

            return relations

        except json.JSONDecodeError as e:
            logger.error(
                f"[OSMOSE:LLMRelationExtractor] Failed to parse LLM JSON response: {e}"
            )
            return []
        except Exception as e:
            logger.error(
                f"[OSMOSE:LLMRelationExtractor] LLM extraction error: {e}",
                exc_info=True
            )
            return []

    def _create_relation_from_llm(
        self,
        rel_data: Dict[str, Any],
        concepts: List[Dict[str, Any]],
        document_id: str,
        document_name: str,
        chunk_ids: Optional[List[str]] = None
    ) -> Optional[TypedRelation]:
        """
        Créer TypedRelation depuis réponse LLM.
        """
        try:
            # Extraire fields
            source_id = rel_data["source_concept"]
            target_id = rel_data["target_concept"]
            relation_type_str = rel_data["relation_type"]
            confidence = float(rel_data["confidence"])
            evidence = rel_data.get("evidence", "")
            llm_metadata = rel_data.get("metadata", {})

            # Valider relation_type
            try:
                relation_type = RelationType(relation_type_str)
            except ValueError:
                logger.warning(
                    f"[OSMOSE:LLMRelationExtractor] Invalid relation type: {relation_type_str}"
                )
                return None

            # Déterminer strength depuis metadata LLM
            strength_str = llm_metadata.get("strength", "MODERATE")
            try:
                strength = RelationStrength(strength_str)
            except ValueError:
                strength = RelationStrength.MODERATE

            # Créer metadata
            metadata = RelationMetadata(
                confidence=confidence,
                extraction_method=ExtractionMethod.LLM,
                source_doc_id=document_id,
                source_chunk_ids=chunk_ids or [],
                language="MULTI",
                created_at=datetime.utcnow(),
                strength=strength,
                status=RelationStatus.ACTIVE,
                require_validation=confidence < 0.75  # Validation si confiance basse
            )

            # Créer relation
            relation_id = f"rel-llm-{uuid.uuid4()}"

            relation = TypedRelation(
                relation_id=relation_id,
                source_concept=source_id,
                target_concept=target_id,
                relation_type=relation_type,
                metadata=metadata,
                evidence=evidence[:300],  # Limiter taille
                context=json.dumps(llm_metadata) if llm_metadata else None
            )

            return relation

        except (KeyError, ValueError) as e:
            logger.warning(
                f"[OSMOSE:LLMRelationExtractor] Failed to create relation from LLM data: {e}"
            )
            return None

    def _create_relation_from_llm_v2(
        self,
        rel_data: Dict[str, Any],
        concepts: List[Dict[str, Any]],
        document_id: str,
        document_name: str,
        chunk_ids: Optional[List[str]] = None
    ) -> Optional[TypedRelation]:
        """
        Phase 2.8 - Créer TypedRelation depuis réponse LLM V2 (predicate_raw + flags).

        Le TypedRelation inclut les nouvelles données pour écriture RawAssertion.
        """
        try:
            # Extraire fields V2
            source_name = rel_data["subject_concept"]
            target_name = rel_data["object_concept"]
            predicate_raw = rel_data["predicate_raw"]
            evidence = rel_data.get("evidence", "")
            confidence = float(rel_data.get("confidence", 0.7))

            # Extraire flags
            flags_data = rel_data.get("flags", {})
            flags = RawAssertionFlags(
                is_negated=flags_data.get("is_negated", False),
                is_hedged=flags_data.get("is_hedged", False),
                is_conditional=flags_data.get("is_conditional", False),
                cross_sentence=flags_data.get("cross_sentence", False)
            )

            # Trouver concepts correspondants (match par nom)
            source_concept = self._find_concept_by_name(source_name, concepts)
            target_concept = self._find_concept_by_name(target_name, concepts)

            if not source_concept or not target_concept:
                logger.debug(
                    f"[OSMOSE:LLMRelationExtractor] Concept not found: "
                    f"source={source_name}, target={target_name}"
                )
                return None

            # Déterminer strength depuis flags
            if flags.is_hedged:
                strength = RelationStrength.WEAK
            elif flags.is_negated or flags.is_conditional:
                strength = RelationStrength.MODERATE
            else:
                strength = RelationStrength.STRONG

            # Pour V2, on utilise UNKNOWN comme type initial
            # La consolidation mappera predicate_raw → relation_type plus tard
            relation_type = RelationType.UNKNOWN

            # Créer metadata avec predicate_raw et flags
            metadata = RelationMetadata(
                confidence=confidence,
                extraction_method=ExtractionMethod.LLM,
                source_doc_id=document_id,
                source_chunk_ids=chunk_ids or [],
                language="MULTI",
                created_at=datetime.utcnow(),
                strength=strength,
                status=RelationStatus.ACTIVE,
                require_validation=confidence < 0.75
            )

            # Créer relation avec données étendues
            relation_id = f"rel-llm-{uuid.uuid4()}"

            # Stocker predicate_raw et flags dans context JSON
            context_data = {
                "predicate_raw": predicate_raw,
                "flags": {
                    "is_negated": flags.is_negated,
                    "is_hedged": flags.is_hedged,
                    "is_conditional": flags.is_conditional,
                    "cross_sentence": flags.cross_sentence,
                },
                "subject_surface_form": source_name,
                "object_surface_form": target_name,
            }

            relation = TypedRelation(
                relation_id=relation_id,
                source_concept=source_concept.get("canonical_name", source_name),
                target_concept=target_concept.get("canonical_name", target_name),
                relation_type=relation_type,
                metadata=metadata,
                evidence=evidence[:500],  # Plus de contexte pour Phase 2.8
                context=json.dumps(context_data)
            )

            return relation

        except (KeyError, ValueError) as e:
            logger.warning(
                f"[OSMOSE:LLMRelationExtractor] Failed to create relation from LLM V2 data: {e}"
            )
            return None

    def _find_concept_by_name(
        self,
        name: str,
        concepts: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Trouver concept par nom (exact ou surface form)."""
        name_lower = name.lower().strip()

        for concept in concepts:
            canonical = concept.get("canonical_name", "").lower()
            if canonical == name_lower:
                return concept

            # Vérifier surface forms
            for form in concept.get("surface_forms", []):
                if form and form.lower() == name_lower:
                    return concept

        # Matching partiel si pas de match exact
        for concept in concepts:
            canonical = concept.get("canonical_name", "").lower()
            if name_lower in canonical or canonical in name_lower:
                return concept

        return None

    def _deduplicate_relations(
        self,
        relations: List[TypedRelation]
    ) -> List[TypedRelation]:
        """
        Déduplication relations (même relation peut apparaître dans plusieurs chunks).

        Stratégie: Garder relation avec confidence la plus haute.
        """
        # Group par (source, target, type)
        groups = {}
        for rel in relations:
            key = (rel.source_concept, rel.target_concept, rel.relation_type)
            if key not in groups:
                groups[key] = []
            groups[key].append(rel)

        # Pour chaque groupe, garder relation avec confidence max
        deduplicated = []
        for group_relations in groups.values():
            best_relation = max(group_relations, key=lambda r: r.metadata.confidence)
            deduplicated.append(best_relation)

        return deduplicated

    # =========================================================================
    # Phase 2.8+ - ID-First Extraction avec index (c1, c2...) - VERSION DÉFINITIVE
    # =========================================================================

    def extract_relations_id_first(
        self,
        concepts: List[Dict[str, Any]],
        full_text: str,
        document_id: str,
        chunk_id: str = "chunk_0"
    ) -> IDFirstExtractionResult:
        """
        Extraction ID-First avec index c1, c2... (VERSION DÉFINITIVE).

        Pipeline:
        1. Construire catalogue avec index (c1, c2...)
        2. Envoyer au LLM avec prompt V3
        3. Valider index (closed-world strict)
        4. Résoudre index → concept_id
        5. Retourner relations + unresolved_mentions

        Args:
            concepts: Liste concepts avec canonical_id (depuis state.promoted)
            full_text: Texte du chunk/document
            document_id: ID document source
            chunk_id: ID chunk source

        Returns:
            RelationExtractionResult avec relations et unresolved_mentions
        """
        logger.info(
            f"[OSMOSE:LLMRelationExtractor] ID-First extraction: "
            f"{len(concepts)} concepts, {len(full_text)} chars"
        )

        result = IDFirstExtractionResult(
            stats={
                "concepts_in_catalogue": 0,
                "relations_extracted": 0,
                "relations_valid": 0,
                "relations_invalid": 0,
                "unresolved_mentions": 0,
            }
        )

        if not concepts:
            logger.warning("[OSMOSE:LLMRelationExtractor] No concepts to build catalogue")
            return result

        # Étape 1: Construire catalogue avec index
        catalogue_json, index_to_concept = self._build_concept_catalogue(concepts)
        valid_indices = set(index_to_concept.keys())
        result.stats["concepts_in_catalogue"] = len(valid_indices)

        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Built catalogue with {len(valid_indices)} concepts"
        )

        # Étape 2: Chunking si texte trop long
        text_chunks = self._chunk_text_for_v3(full_text)

        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Processing {len(text_chunks)} text chunks"
        )

        # Étape 3: Extraction par chunk (parallèle si plusieurs chunks)
        all_relations_raw: List[Dict[str, Any]] = []
        all_unresolved: List[Dict[str, Any]] = []

        max_workers = min(8, len(text_chunks))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_chunk = {
                executor.submit(
                    self._extract_from_chunk_v3,
                    chunk_text=chunk_text,
                    catalogue_json=catalogue_json
                ): chunk_idx
                for chunk_idx, chunk_text in enumerate(text_chunks)
            }

            for future in as_completed(future_to_chunk):
                chunk_idx = future_to_chunk[future]
                try:
                    chunk_relations, chunk_unresolved = future.result()
                    all_relations_raw.extend(chunk_relations)
                    all_unresolved.extend(chunk_unresolved)

                    logger.debug(
                        f"[OSMOSE:LLMRelationExtractor] Chunk {chunk_idx}: "
                        f"{len(chunk_relations)} relations, {len(chunk_unresolved)} unresolved"
                    )
                except Exception as e:
                    logger.error(
                        f"[OSMOSE:LLMRelationExtractor] Chunk {chunk_idx} failed: {e}",
                        exc_info=True
                    )

        result.stats["relations_extracted"] = len(all_relations_raw)
        result.stats["unresolved_mentions"] = len(all_unresolved)

        # Étape 4: Valider et résoudre index → concept_id
        for rel_data in all_relations_raw:
            is_valid, error = self._validate_relation_closed_world(rel_data, valid_indices)

            if not is_valid:
                logger.debug(f"[OSMOSE:LLMRelationExtractor] Invalid relation: {error}")
                result.stats["relations_invalid"] += 1
                continue

            # Résoudre index → concept_id
            subject_index = rel_data["subject_id"]
            object_index = rel_data["object_id"]

            subject_concept_id = index_to_concept[subject_index]["canonical_id"]
            object_concept_id = index_to_concept[object_index]["canonical_id"]
            subject_name = index_to_concept[subject_index]["canonical_name"]
            object_name = index_to_concept[object_index]["canonical_name"]

            # Extraire flags
            flags_data = rel_data.get("flags", {})
            flags = RawAssertionFlags(
                is_negated=flags_data.get("is_negated", False),
                is_hedged=flags_data.get("is_hedged", False),
                is_conditional=flags_data.get("is_conditional", False),
                cross_sentence=flags_data.get("cross_sentence", False)
            )

            # Créer ExtractedRelationV3
            extracted_rel = ExtractedRelationV3(
                subject_concept_id=subject_concept_id,
                object_concept_id=object_concept_id,
                predicate_raw=rel_data.get("predicate_raw", "related_to"),
                evidence=rel_data.get("evidence", "")[:500],
                confidence=float(rel_data.get("confidence", 0.7)),
                flags=flags,
                subject_surface_form=subject_name,
                object_surface_form=object_name
            )

            result.relations.append(extracted_rel)
            result.stats["relations_valid"] += 1

        # Étape 5: Collecter unresolved mentions
        for mention_data in all_unresolved:
            mention = UnresolvedMention(
                mention=mention_data.get("mention", ""),
                context=mention_data.get("context", "")[:300],
                suggested_type=mention_data.get("suggested_type")
            )
            result.unresolved_mentions.append(mention)

        # Déduplication des relations (même paire subject/object/predicate)
        result.relations = self._deduplicate_relations_v3(result.relations)

        logger.info(
            f"[OSMOSE:LLMRelationExtractor] ID-First complete: "
            f"{result.stats['relations_valid']} valid relations, "
            f"{result.stats['relations_invalid']} invalid, "
            f"{len(result.unresolved_mentions)} unresolved mentions"
        )

        return result

    def _build_concept_catalogue(
        self,
        concepts: List[Dict[str, Any]]
    ) -> Tuple[str, Dict[str, Dict[str, Any]]]:
        """
        Construit le catalogue JSON avec index (c1, c2...) et le mapping.

        Args:
            concepts: Liste concepts avec canonical_id, canonical_name, surface_forms

        Returns:
            (catalogue_json_str, index_to_concept_map)
        """
        catalogue = []
        index_to_concept = {}

        for i, concept in enumerate(concepts):
            index = f"c{i + 1}"  # c1, c2, c3...

            canonical_id = concept.get("canonical_id") or concept.get("concept_id", "")
            canonical_name = concept.get("canonical_name", "")
            surface_forms = concept.get("surface_forms", [])
            concept_type = concept.get("concept_type", "UNKNOWN")

            if not canonical_id or not canonical_name:
                logger.warning(
                    f"[OSMOSE:LLMRelationExtractor] Skipping concept without ID/name: {concept}"
                )
                continue

            # Entry pour le catalogue LLM
            catalogue_entry = {
                "idx": index,
                "name": canonical_name,
                "aliases": surface_forms[:5],  # Limiter à 5 alias pour économiser tokens
                "type": concept_type.lower()
            }
            catalogue.append(catalogue_entry)

            # Mapping pour résolution
            index_to_concept[index] = {
                "canonical_id": canonical_id,
                "canonical_name": canonical_name,
                "concept_type": concept_type
            }

        catalogue_json = json.dumps(catalogue, ensure_ascii=False, indent=2)

        return catalogue_json, index_to_concept

    def _validate_relation_closed_world(
        self,
        rel_data: Dict[str, Any],
        valid_indices: Set[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validation closed-world stricte : les index DOIVENT être dans le catalogue.

        Returns:
            (is_valid, error_message)
        """
        subject_id = rel_data.get("subject_id", "")
        object_id = rel_data.get("object_id", "")

        if not subject_id:
            return False, "Missing subject_id"

        if not object_id:
            return False, "Missing object_id"

        if subject_id not in valid_indices:
            return False, f"Invalid subject_id '{subject_id}' - not in catalogue"

        if object_id not in valid_indices:
            return False, f"Invalid object_id '{object_id}' - not in catalogue"

        if subject_id == object_id:
            return False, f"Self-relation not allowed: {subject_id}"

        return True, None

    def _chunk_text_for_v3(self, full_text: str) -> List[str]:
        """
        Découpe le texte en chunks pour le prompt V3.
        """
        if len(full_text) <= self.max_context_chars:
            return [full_text]

        chunks = []
        chunk_size = self.max_context_chars
        overlap = 200

        for i in range(0, len(full_text), chunk_size - overlap):
            chunk_text = full_text[i:i + chunk_size]
            if chunk_text.strip():
                chunks.append(chunk_text)

        return chunks

    def _extract_from_chunk_v3(
        self,
        chunk_text: str,
        catalogue_json: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Extrait relations d'un chunk avec prompt V3 (ID-First).

        Returns:
            (relations_list, unresolved_mentions_list)
        """
        prompt = RELATION_EXTRACTION_PROMPT_V3.format(
            full_text_excerpt=chunk_text,
            concept_catalog_json=catalogue_json
        )

        try:
            response_text = self.llm_router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                response_format={"type": "json_object"},
                model_preference=self.model
            )

            # Parser JSON
            response_data = json.loads(response_text)

            relations = response_data.get("relations", [])
            unresolved = response_data.get("unresolved_mentions", [])

            return relations, unresolved

        except json.JSONDecodeError as e:
            logger.error(
                f"[OSMOSE:LLMRelationExtractor] Failed to parse V3 JSON: {e}"
            )
            return [], []
        except Exception as e:
            logger.error(
                f"[OSMOSE:LLMRelationExtractor] V3 extraction error: {e}",
                exc_info=True
            )
            return [], []

    def _deduplicate_relations_v3(
        self,
        relations: List[ExtractedRelationV3]
    ) -> List[ExtractedRelationV3]:
        """
        Déduplication des relations V3.
        Garde celle avec la confidence la plus haute pour chaque triplet.
        """
        groups: Dict[Tuple[str, str, str], List[ExtractedRelationV3]] = {}

        for rel in relations:
            # Clé = (subject_id, object_id, predicate_raw normalisé)
            predicate_norm = rel.predicate_raw.lower().strip()
            key = (rel.subject_concept_id, rel.object_concept_id, predicate_norm)

            if key not in groups:
                groups[key] = []
            groups[key].append(rel)

        deduplicated = []
        for group in groups.values():
            best = max(group, key=lambda r: r.confidence)
            deduplicated.append(best)

        return deduplicated

    # =========================================================================
    # Phase 2.10 - Type-First Extraction (Closed Set + Multi-Sourcing)
    # =========================================================================

    def extract_relations_type_first(
        self,
        concepts: List[Dict[str, Any]],
        full_text: str,
        document_id: str,
        chunk_id: str = "chunk_0",
        min_type_confidence: float = 0.70
    ) -> TypeFirstExtractionResult:
        """
        Extraction Type-First avec set fermé de 12 types (Phase 2.10).

        Différence vs ID-First (V3):
        - LLM choisit un relation_type parmi les 12 Core types
        - type_confidence et alt_type/alt_type_confidence retournés
        - Validation stricte du type (closed-world)
        - Support context_hint et relation_subtype_raw

        Args:
            concepts: Liste concepts avec canonical_id (depuis state.promoted)
            full_text: Texte du chunk/document
            document_id: ID document source
            chunk_id: ID chunk source
            min_type_confidence: Seuil minimum pour type_confidence

        Returns:
            TypeFirstExtractionResult avec relations V4 et unresolved_mentions
        """
        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Type-First extraction (V4): "
            f"{len(concepts)} concepts, {len(full_text)} chars"
        )

        result = TypeFirstExtractionResult(
            stats={
                "concepts_in_catalogue": 0,
                "relations_extracted": 0,
                "relations_valid": 0,
                "relations_invalid_index": 0,
                "relations_invalid_type": 0,
                "relations_low_confidence": 0,
                "unresolved_mentions": 0,
                "types_distribution": {},
            }
        )

        if not concepts:
            logger.warning("[OSMOSE:LLMRelationExtractor] No concepts to build catalogue")
            return result

        # Étape 1: Construire catalogue avec index (réutilise V3)
        catalogue_json, index_to_concept = self._build_concept_catalogue(concepts)
        valid_indices = set(index_to_concept.keys())
        result.stats["concepts_in_catalogue"] = len(valid_indices)

        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Built catalogue with {len(valid_indices)} concepts"
        )

        # Étape 2: Chunking si texte trop long
        text_chunks = self._chunk_text_for_v3(full_text)

        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Processing {len(text_chunks)} text chunks"
        )

        # Étape 3: Extraction par chunk (parallèle si plusieurs chunks)
        all_relations_raw: List[Dict[str, Any]] = []
        all_unresolved: List[Dict[str, Any]] = []

        max_workers = min(8, len(text_chunks))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_chunk = {
                executor.submit(
                    self._extract_from_chunk_v4,
                    chunk_text=chunk_text,
                    catalogue_json=catalogue_json
                ): chunk_idx
                for chunk_idx, chunk_text in enumerate(text_chunks)
            }

            for future in as_completed(future_to_chunk):
                chunk_idx = future_to_chunk[future]
                try:
                    chunk_relations, chunk_unresolved = future.result()
                    all_relations_raw.extend(chunk_relations)
                    all_unresolved.extend(chunk_unresolved)

                    logger.debug(
                        f"[OSMOSE:LLMRelationExtractor] Chunk {chunk_idx}: "
                        f"{len(chunk_relations)} relations, {len(chunk_unresolved)} unresolved"
                    )
                except Exception as e:
                    logger.error(
                        f"[OSMOSE:LLMRelationExtractor] Chunk {chunk_idx} failed: {e}",
                        exc_info=True
                    )

        result.stats["relations_extracted"] = len(all_relations_raw)
        result.stats["unresolved_mentions"] = len(all_unresolved)

        # Étape 4: Valider et résoudre
        for rel_data in all_relations_raw:
            # Validation index (closed-world)
            is_valid, error = self._validate_relation_closed_world(rel_data, valid_indices)
            if not is_valid:
                logger.debug(f"[OSMOSE:LLMRelationExtractor] Invalid index: {error}")
                result.stats["relations_invalid_index"] += 1
                continue

            # Validation type (closed-world)
            relation_type_str = rel_data.get("relation_type", "")
            if relation_type_str not in CORE_RELATION_TYPES_V4:
                logger.debug(
                    f"[OSMOSE:LLMRelationExtractor] Invalid relation_type: {relation_type_str}"
                )
                result.stats["relations_invalid_type"] += 1
                continue

            # Validation type_confidence
            type_confidence = float(rel_data.get("type_confidence", 0.0))
            if type_confidence < min_type_confidence:
                logger.debug(
                    f"[OSMOSE:LLMRelationExtractor] Low type_confidence: "
                    f"{type_confidence} < {min_type_confidence}"
                )
                result.stats["relations_low_confidence"] += 1
                continue

            # Résoudre index → concept_id
            subject_index = rel_data["subject_id"]
            object_index = rel_data["object_id"]

            subject_concept_id = index_to_concept[subject_index]["canonical_id"]
            object_concept_id = index_to_concept[object_index]["canonical_id"]
            subject_name = index_to_concept[subject_index]["canonical_name"]
            object_name = index_to_concept[object_index]["canonical_name"]

            # Résoudre relation_type
            try:
                relation_type = RelationType(relation_type_str)
            except ValueError:
                relation_type = RelationType.ASSOCIATED_WITH

            # Résoudre alt_type si présent
            alt_type: Optional[RelationType] = None
            alt_type_confidence: Optional[float] = None
            alt_type_str = rel_data.get("alt_type")
            if alt_type_str and alt_type_str in CORE_RELATION_TYPES_V4:
                try:
                    alt_type = RelationType(alt_type_str)
                    alt_type_confidence = float(rel_data.get("alt_type_confidence", 0.0))
                except (ValueError, TypeError):
                    pass

            # Extraire flags
            flags_data = rel_data.get("flags", {})
            flags = RawAssertionFlags(
                is_negated=flags_data.get("is_negated", False),
                is_hedged=flags_data.get("is_hedged", False),
                is_conditional=flags_data.get("is_conditional", False),
                cross_sentence=flags_data.get("cross_sentence", False)
            )

            # Créer ExtractedRelationV4
            extracted_rel = ExtractedRelationV4(
                subject_concept_id=subject_concept_id,
                object_concept_id=object_concept_id,
                relation_type=relation_type,
                type_confidence=type_confidence,
                alt_type=alt_type,
                alt_type_confidence=alt_type_confidence,
                predicate_raw=rel_data.get("predicate_raw", "")[:100],
                relation_subtype_raw=rel_data.get("relation_subtype_raw"),
                evidence=rel_data.get("evidence", "")[:500],
                evidence_start_char=rel_data.get("evidence_start_char"),
                evidence_end_char=rel_data.get("evidence_end_char"),
                context_hint=rel_data.get("context_hint"),
                confidence=type_confidence,  # Use type_confidence as main confidence
                flags=flags,
                subject_surface_form=subject_name,
                object_surface_form=object_name
            )

            result.relations.append(extracted_rel)
            result.stats["relations_valid"] += 1

            # Track type distribution
            type_key = relation_type.value
            result.stats["types_distribution"][type_key] = \
                result.stats["types_distribution"].get(type_key, 0) + 1

        # Étape 5: Collecter unresolved mentions
        for mention_data in all_unresolved:
            mention = UnresolvedMention(
                mention=mention_data.get("mention", ""),
                context=mention_data.get("context", "")[:300],
                suggested_type=mention_data.get("suggested_type")
            )
            result.unresolved_mentions.append(mention)

        # Déduplication des relations V4
        result.relations = self._deduplicate_relations_v4(result.relations)

        # Log résumé
        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Type-First complete: "
            f"{result.stats['relations_valid']} valid relations, "
            f"{result.stats['relations_invalid_index']} invalid index, "
            f"{result.stats['relations_invalid_type']} invalid type, "
            f"{result.stats['relations_low_confidence']} low confidence, "
            f"{len(result.unresolved_mentions)} unresolved mentions"
        )

        # Log distribution par type
        if result.stats["types_distribution"]:
            logger.info(
                f"[OSMOSE:LLMRelationExtractor] Type distribution: "
                f"{result.stats['types_distribution']}"
            )

        return result

    def _extract_from_chunk_v4(
        self,
        chunk_text: str,
        catalogue_json: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Extrait relations d'un chunk avec prompt V4 (Type-First).

        Returns:
            (relations_list, unresolved_mentions_list)
        """
        # Construire messages avec system + user prompts
        messages = [
            {"role": "system", "content": RELATION_EXTRACTION_V4_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": RELATION_EXTRACTION_V4_USER_PROMPT.format(
                    text_segment=chunk_text,
                    concept_catalog_json=catalogue_json
                )
            }
        ]

        try:
            response_text = self.llm_router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=messages,
                temperature=0.1,
                response_format={"type": "json_object"},
                model_preference=self.model
            )

            # Parser JSON
            response_data = json.loads(response_text)

            relations = response_data.get("relations", [])
            unresolved = response_data.get("unresolved_mentions", [])

            return relations, unresolved

        except json.JSONDecodeError as e:
            logger.error(
                f"[OSMOSE:LLMRelationExtractor] Failed to parse V4 JSON: {e}"
            )
            return [], []
        except Exception as e:
            logger.error(
                f"[OSMOSE:LLMRelationExtractor] V4 extraction error: {e}",
                exc_info=True
            )
            return [], []

    def _deduplicate_relations_v4(
        self,
        relations: List[ExtractedRelationV4]
    ) -> List[ExtractedRelationV4]:
        """
        Déduplication des relations V4.

        Clé de dédup: (subject_id, object_id, relation_type)
        Garde celle avec la type_confidence la plus haute.
        """
        groups: Dict[Tuple[str, str, str], List[ExtractedRelationV4]] = {}

        for rel in relations:
            # Clé = (subject_id, object_id, relation_type)
            key = (rel.subject_concept_id, rel.object_concept_id, rel.relation_type.value)

            if key not in groups:
                groups[key] = []
            groups[key].append(rel)

        deduplicated = []
        for group in groups.values():
            best = max(group, key=lambda r: r.type_confidence)
            deduplicated.append(best)

        return deduplicated
