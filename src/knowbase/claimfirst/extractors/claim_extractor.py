# src/knowbase/claimfirst/extractors/claim_extractor.py
"""
ClaimExtractor - Extraction de Claims documentées.

Réutilise AssertionUnitIndexer pour le mode pointer (verbatim garanti).

Charte de la "bonne Claim" (non négociable):
1. Dit UNE chose précise
2. Supportée par passage(s) verbatim exact(s)
3. Jamais exhaustive par défaut
4. Contextuelle (scope, conditions, version)
5. N'infère rien (pas de déduction)
6. Comparable (compatible/contradictoire/disjointe)
7. Peut NE PAS exister si le document est vague
8. Révisable par addition, jamais par réécriture

INV-1: La preuve d'une Claim est `unit_ids`, pas `passage_id`.
       Le LLM POINTE vers une unité au lieu de COPIER le texte.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple, Any

from knowbase.claimfirst.models.claim import (
    Claim,
    ClaimType,
    ClaimScope,
    ClaimQualifier,
    QualifierType,
)
from knowbase.claimfirst.models.entity import is_valid_entity_name
from knowbase.claimfirst.models.passage import Passage
from knowbase.stratified.pass1.assertion_unit_indexer import (
    AssertionUnitIndexer,
    UnitIndexResult,
    AssertionUnit,
    format_units_for_llm,
)

logger = logging.getLogger(__name__)


# ============================================================================
# PRÉDICATS CANONIQUES — Liste fermée pour structured_form
# ============================================================================

# Constantes centralisees — source unique dans constants.py
from knowbase.claimfirst.constants import (
    CANONICAL_PREDICATES,
    PREDICATE_NORMALIZATION_MAP,
    CORE_PREDICATE_DESCRIPTIONS,
)


def normalize_predicate(raw_predicate: str) -> Optional[str]:
    """
    Normalise un prédicat vers la whitelist canonique core (Layer B, fallback).

    Pour domain-aware, utiliser ClaimExtractor._normalize_effective() qui
    combine core + predicats des Domain Packs actifs.

    Returns:
        Le prédicat canonique core, ou None si non mappable.
    """
    pred = raw_predicate.strip().upper().replace(" ", "_")
    if pred in CANONICAL_PREDICATES:
        return pred
    mapped = PREDICATE_NORMALIZATION_MAP.get(pred)
    if mapped:
        return mapped
    return None


def build_predicates_table(descriptions: Dict[str, str]) -> str:
    """Construit la table markdown de predicats pour injection dans le prompt LLM.

    Args:
        descriptions: Dict {PREDICATE: description}

    Returns:
        Table markdown formatee.
    """
    lines = ["| Predicate | Meaning |", "|-----------|---------|"]
    for pred in sorted(descriptions.keys()):
        lines.append(f"| {pred} | {descriptions[pred]} |")
    return "\n".join(lines)


# ============================================================================
# PROMPT V2.1 — Prédicats contraints (Layer A)
# ============================================================================

# Note: Les {{ et }} sont échappés pour str.format()
CLAIM_EXTRACTION_PROMPT_TEMPLATE = """You are an expert in structured knowledge extraction from documents.

You receive numbered text units (U1, U2, etc.) from a document.
Your task is to identify CLAIMS — precise, documented assertions useful
for building a knowledge graph.

{domain_context}
## Document context

Title: {doc_title}
Type: {doc_type}
Primary subject: {doc_subject}
Current section: {section_title}
Key concepts in this section: {section_concepts}

## Value grid (IMPORTANT)

Not all claims have the same value. Prioritize in this order:

**HIGH VALUE** — Relational claims between two named entities:
- X uses / is based on / requires Y
- X replaces / succeeds Y
- X is integrated in / embedded in Y
- X is compatible with / supports Y
→ For these claims, fill the `structured_form` field.

**MEDIUM VALUE** — Specific factual claims with an identifiable subject:
- X offers a specific capability
- X has a specific limitation / constraint
→ `structured_form` = null

**DO NOT EXTRACT**:
- Fragments without a verb or identifiable subject ("reduce costs", "improve tracking")
- Generic user actions without specificity ("You can define...", "Users can create...")
  UNLESS they reveal a specific technical capability
- Reformulations of section titles
- Legal texts, disclaimers, copyrights

## Claim types

- FACTUAL: Verifiable factual assertion
- PRESCRIPTIVE: Obligation or prohibition
- DEFINITIONAL: Definition or description
- CONDITIONAL: Conditional assertion
- PERMISSIVE: Permission or authorization
- PROCEDURAL: Step or process

## DECONTEXTUALIZATION — every claim_text must be self-standing (CRITICAL)

A claim must be understandable ALONE, without reading the source unit or any
neighbouring sentence. Before writing each `claim_text`:
- **Resolve every anaphora**: replace "it / this / that / the latter / the former /
  the system / the above" with the explicit named entity it refers to.
- **Name the subject explicitly**: never start with a bare pronoun or a generic
  noun. State WHICH entity/product/object/article the claim is about.
- **Include the minimal disambiguating scope** inline: which version, which
  region, which condition makes the claim true — just enough to remove ambiguity,
  not the whole paragraph.
- **Do NOT over-stuff**: keep it one precise statement. Decontextualized AND
  minimal (a "molecular" fact), not a paragraph.

Bad (too atomic / context-stripped): "It must be initialized before use."
Good (molecular): "The Expert cache must be initialized via transaction CG5Z
before it can be used."

## What to look for — question coverage (IMPORTANT)

Documents are queried with multi-step, conditional and time-scoped questions.
Actively extract claims that answer these universal question archetypes WHEN the
unit contains the information (never invent):
- **Conditions / prerequisites**: what must be true / done / authorized BEFORE
  something applies or works ("requires X", "only if Y", "after Z").
- **Sequences / order**: the order of steps, what comes before/after, dependencies.
- **Versions / temporal validity**: from which version/date something applies,
  until when, what changed between versions.
- **Comparisons / distinctions**: how one option/version/entity differs from another.
- **Causes / consequences**: why something happens, what it leads to.
These often need TWO linked claims (e.g. a condition claim + the conditioned fact)
rather than one — extract both, each self-standing.

## Response format (JSON)

[
  {{
    "claim_text": "Self-contained synthetic formulation of the claim",
    "claim_type": "FACTUAL",
    "unit_id": "U1",
    "confidence": 0.95,
    "scope": {{"version": null, "region": null, "edition": null, "conditions": []}},
    "qualifiers": [
      {{"qualifier_type": "condition", "value": "for enterprise customers", "confidence": 0.9}}
    ],
    "structured_form": {{
      "subject": "Name of the subject entity",
      "predicate": "USES",
      "object": "Name of the object entity",
      "open_predicate": false
    }}
  }}
]

## Qualifiers — conditions of applicability (IMPORTANT)

A claim is often true only under certain conditions. Capture them as
structured `qualifiers`. Each qualifier MUST be grounded in the source unit
(appear verbatim or as a direct paraphrase) — NEVER infer one.

Qualifier types (universal, valid across all domains):
- "temporal": time bound — e.g. "since 2024", "until v2.5", "effective from the 2021 amendment"
- "spatial": geographic/zone scope — e.g. "EU only", "on-premise deployments", "above FL250"
- "version": product/edition/release — e.g. "release 2023", "Private Cloud edition"
- "condition": activation condition — e.g. "if MFA is enabled", "for premium subscribers", "in adults over 65"
- "scope_limit": scope restriction — e.g. "non-production only", "excluding renal insufficiency"

Rules:
- Add a qualifier ONLY if its value is stated in the source unit. If unsure, omit it.
- `qualifiers` defaults to [] (empty list) when the claim is unconditional.
- `confidence` in [0,1] reflects how explicitly the qualifier is stated.
- Do not duplicate the same condition in both `scope` and `qualifiers`; prefer `qualifiers`.

## structured_form predicates — prefer the closed list, else open

Preferred predicates (CLOSED list — use one of these whenever it fits):

{predicates_table}

**RULES:**
- **First choice**: pick EXACTLY one predicate from the list above (set
  `"open_predicate": false`). No synonyms/inflections of a listed predicate —
  use the listed form.
- **Fallback (open predicate)**: if there IS a clear relation between two named
  entities but NONE of the listed predicates fits, do NOT discard it. Instead use
  a concise free predicate (a short lowercase verb phrase, e.g. "is_initialized_by",
  "expires_after") and set `"open_predicate": true`. This preserves the relation
  for retrieval instead of losing it.
- Subject and object must be proper nouns or technical terms, NOT descriptions or clauses.
- If there is genuinely no relation between two named entities → "structured_form": null.

## Rules

- DO NOT copy the text. Point to unit_ids only.
- If a unit does not contain a useful claim, IGNORE it.
- The claim must be self-contained and understandable without reading the source unit.
- Extract every genuine claim. Only abstain if the unit is truly non-informative (title, label, boilerplate).
- IMPORTANT: Write all claim_text in the SAME LANGUAGE as the source document units.

## Source passage (CONTEXT ONLY — for disambiguation, do NOT extract from here)

The full source passage is provided below SOLELY to resolve anaphora and name
implicit subjects when writing self-contained claims. Use it to understand what
"it / this / the system / the latter" refers to. You MUST still extract claims
only from the numbered units listed afterwards (point to their unit_id).

\"\"\"
{passage_context}
\"\"\"

## Units to analyze (extract claims from THESE)

{units_text}

Return ONLY a JSON object: {{"claims": [...]}}
No explanation, no markdown fences."""


def build_claim_extraction_prompt(
    units_text: str,
    doc_title: str,
    doc_type: str,
    doc_subject: str = "",
    section_title: str = "",
    section_concepts: str = "",
    domain_context: str = "",
    predicates_table: str = "",
    passage_context: str = "",
) -> str:
    """Construit le prompt d'extraction de claims (V2 enrichi, domain-aware).

    passage_context : texte brut complet du passage source. Fourni en lecture
    seule pour permettre la résolution d'anaphores / la nomination du sujet
    implicite (décontextualisation P1.3.5), indépendamment du batch_size.
    """
    if not predicates_table:
        predicates_table = build_predicates_table(CORE_PREDICATE_DESCRIPTIONS)
    return CLAIM_EXTRACTION_PROMPT_TEMPLATE.format(
        units_text=units_text,
        doc_title=doc_title,
        doc_type=doc_type,
        doc_subject=doc_subject or "Unknown",
        section_title=section_title or "N/A",
        section_concepts=section_concepts or "N/A",
        domain_context=domain_context,
        predicates_table=predicates_table,
        passage_context=(passage_context or "(not available)"),
    )


# Nombre max d'appels LLM en parallèle (évite de surcharger vLLM/OpenAI)
# Concurrence des appels LLM d'extraction. Défaut 180 (calibré DeepInfra ~200).
# CRITIQUE pour un LLM self-hosted à faible concurrence : le 72B-AWQ sur L40S
# tourne à max_num_seqs=2 → 180 appels concurrents saturent la queue (timeouts).
# Mettre CLAIMFIRST_MAX_CONCURRENT_LLM=2-4 pour la ré-ingestion 72B.
MAX_CONCURRENT_LLM_CALLS = int(os.getenv("CLAIMFIRST_MAX_CONCURRENT_LLM", "180"))


@dataclass
class BatchTask:
    """Tâche de batch pour extraction parallèle."""
    batch_id: int
    units: List[AssertionUnit]
    passage: Passage
    unit_result: UnitIndexResult
    tenant_id: str
    doc_id: str
    doc_title: str
    doc_type: str
    doc_subject: str = ""
    section_title: str = ""
    section_concepts: str = ""
    domain_context: str = ""


class ClaimExtractor:
    """
    Extracteur de Claims documentées.

    Utilise AssertionUnitIndexer pour segmenter le texte en unités,
    puis le LLM pour identifier les claims en mode pointer.

    Le verbatim est GARANTI car reconstruit depuis l'index d'unités.

    Les appels LLM sont parallélisés pour optimiser les performances.
    """

    def __init__(
        self,
        llm_client: Any,
        min_unit_length: int = 30,
        max_unit_length: int = 500,
        batch_size: int = 10,
        max_concurrent: int = MAX_CONCURRENT_LLM_CALLS,
        canonical_predicates: Optional[frozenset] = None,
        predicate_descriptions: Optional[Dict[str, str]] = None,
        predicate_normalization_map: Optional[Dict[str, str]] = None,
        use_staged_pipeline: Optional[bool] = None,
    ):
        """
        Initialise l'extracteur.

        Args:
            llm_client: Client LLM pour l'extraction (non utilisé, gardé pour compatibilité)
            min_unit_length: Longueur minimale d'une unité
            max_unit_length: Longueur maximale d'une unité
            batch_size: Nombre d'unités par batch LLM
            max_concurrent: Nombre max d'appels LLM en parallèle
            canonical_predicates: Predicats autorises (core + domain packs actifs).
                Si None, utilise CANONICAL_PREDICATES core.
            predicate_descriptions: Descriptions des predicats pour prompt LLM.
                Si None, utilise CORE_PREDICATE_DESCRIPTIONS.
            predicate_normalization_map: Mapping alias -> canonique.
                Si None, utilise PREDICATE_NORMALIZATION_MAP core.
        """
        self.llm_client = llm_client
        self.batch_size = batch_size
        # Si burst mode actif, utiliser la limite burst (cap GPU vLLM ~16-32 seqs)
        # plutot que la limite DeepInfra (180). Evite avalanche de 500.
        try:
            from knowbase.ingestion.burst.provider_switch import get_burst_concurrency_config
            burst_cfg = get_burst_concurrency_config()
            burst_max = burst_cfg.get("max_concurrent_llm")
            if burst_max and burst_max < max_concurrent:
                logger.info(
                    f"[OSMOSE:ClaimExtractor] Burst mode active — capping max_concurrent "
                    f"from {max_concurrent} to {burst_max}"
                )
                max_concurrent = burst_max
        except Exception:
            pass
        self.max_concurrent = max_concurrent

        # Predicats domain-aware (core + domain packs actifs)
        self.canonical_predicates: frozenset = canonical_predicates or CANONICAL_PREDICATES
        self.predicate_descriptions: Dict[str, str] = (
            predicate_descriptions or CORE_PREDICATE_DESCRIPTIONS
        )
        self.predicate_normalization_map: Dict[str, str] = (
            predicate_normalization_map or PREDICATE_NORMALIZATION_MAP
        )
        # Table markdown precalculee pour injection dans le prompt LLM
        self._predicates_table: str = build_predicates_table(self.predicate_descriptions)
        logger.info(
            f"[OSMOSE:ClaimExtractor] Predicates: {len(self.canonical_predicates)} canonical, "
            f"{len(self.predicate_normalization_map)} normalization aliases"
        )

        # P1.4b — pipeline d'extraction multi-étapes (Sélection -> Décomposition).
        # Opt-in (défaut OFF via env), pour ne pas altérer le chemin legacy.
        if use_staged_pipeline is None:
            use_staged_pipeline = os.getenv("CLAIMFIRST_STAGED_PIPELINE", "0") == "1"
        self.use_staged_pipeline = bool(use_staged_pipeline)

        # Indexer pour segmentation. En staged : segmentation plus GROSSIÈRE (1 claim ≈ 1
        # phrase) — anti-fragmentation énumération + on ne découpe PAS les phrases sur :/;
        # (la granularité interne est gérée par Stage B + le schéma objects[]). On NE fusionne
        # PAS de phrases (éviter les claims multi-faits) : c'est un coarsening sûr, pas mécanique.
        _coarse = self.use_staged_pipeline
        self.unit_indexer = AssertionUnitIndexer(
            min_unit_length=min_unit_length,
            max_unit_length=max_unit_length,
            keep_enumeration_as_unit=self.use_staged_pipeline,
            split_on_semicolon=not _coarse,
            split_on_colon=not _coarse,
        )

        # Stages (LLM async injecté via self._staged_llm_async)
        self._selection_gate = None
        self._decomposition_stage = None
        self._grounding_gate = None
        self._grounding_executor = None  # thread dédié : grounding NLI hors event loop
        if self.use_staged_pipeline:
            from knowbase.claimfirst.extractors.selection_gate import SelectionGate
            from knowbase.claimfirst.extractors.decomposition_stage import DecompositionStage
            from knowbase.claimfirst.quality.grounding_gate import GroundingGate
            self._selection_gate = SelectionGate(self._staged_llm_async, enabled=True)
            self._decomposition_stage = DecompositionStage(self._staged_llm_async, enabled=True)
            # Grounding gate (P1.4b-4) : flag marginal, ne rejette pas. Modèle NLI chargé
            # paresseusement au 1er check. Désactivable via CLAIMFIRST_GROUNDING_GATE=0.
            grounding_on = os.getenv("CLAIMFIRST_GROUNDING_GATE", "1") == "1"
            self._grounding_gate = GroundingGate(enabled=grounding_on)
            if grounding_on:
                # 1 seul worker : ne bloque pas l'event loop (concurrence LLM préservée),
                # et sérialise les appels NLI entre eux (accès modèle thread-safe).
                self._grounding_executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="grounding"
                )
            logger.info(
                "[OSMOSE:ClaimExtractor] Pipeline STAGED activé "
                "(Sélection -> Décomposition%s)",
                " -> Grounding" if grounding_on else "",
            )

        # Stats
        self.stats = {
            "units_indexed": 0,
            "llm_calls": 0,
            "tokens_used": 0,
            "claims_extracted": 0,
            "claims_rejected": 0,
            "predicates_canonical": 0,
            "predicates_normalized": 0,
            "predicates_retried": 0,
            "predicates_dropped": 0,
            "sf_dropped_invalid_entity": 0,
            "json_repaired": 0,
            "json_parse_errors": 0,
            "empty_responses": 0,
        }

    def _normalize_effective(self, raw_predicate: str) -> Optional[str]:
        """Normalise un predicat avec le set effectif (core + domain packs).

        Returns:
            Le predicat canonique (effectif), ou None si non-mappable.
        """
        pred = raw_predicate.strip().upper().replace(" ", "_")
        if pred in self.canonical_predicates:
            return pred
        mapped = self.predicate_normalization_map.get(pred)
        if mapped and mapped in self.canonical_predicates:
            return mapped
        return None

    def extract(
        self,
        passages: List[Passage],
        tenant_id: str,
        doc_id: str,
        doc_title: str = "",
        doc_type: str = "technical",
        doc_subject: str = "",
        domain_context: str = "",
        on_block_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Tuple[List[Claim], Dict[str, UnitIndexResult]]:
        """
        Extrait les Claims des passages.

        Args:
            passages: Liste de Passages à traiter
            tenant_id: Tenant ID
            doc_id: Document ID
            doc_title: Titre du document (contexte)
            doc_type: Type de document (contexte)
            doc_subject: Sujet principal du document (contexte V2)
            domain_context: Bloc de contexte métier injecté dans le prompt (V2)
            on_block_complete: P4.3 — callback optionnel invoqué après chaque batch LLM
                avec dict {block_index, total_blocks, claims_in_block, total_claims_so_far}.
                Permet à l'orchestrator de checkpointer le JobManager (P4.1) en
                Redis pour la reprise au crash.

        Returns:
            Tuple (claims, unit_index) où unit_index permet de retrouver le verbatim
        """
        claims: List[Claim] = []
        unit_index: Dict[str, UnitIndexResult] = {}

        # Phase 1: Indexer tous les passages en unités
        logger.info(f"[OSMOSE:ClaimExtractor] Indexing {len(passages)} passages...")
        for passage in passages:
            result = self.unit_indexer.index_docitem(
                docitem_id=passage.passage_id,
                text=passage.text,
                item_type=passage.item_type,
            )
            if result.units:
                unit_index[passage.passage_id] = result
                self.stats["units_indexed"] += len(result.units)

        logger.info(
            f"[OSMOSE:ClaimExtractor] Indexed {self.stats['units_indexed']} units "
            f"from {len(unit_index)} passages"
        )

        # Phase 2: Collecter tous les batches à traiter
        batch_tasks: List[BatchTask] = []
        batch_id = 0

        for passage_id, unit_result in unit_index.items():
            passage = next((p for p in passages if p.passage_id == passage_id), None)
            if not passage:
                continue

            # Créer une tâche par batch
            for i in range(0, len(unit_result.units), self.batch_size):
                batch_units = unit_result.units[i:i + self.batch_size]
                batch_tasks.append(BatchTask(
                    batch_id=batch_id,
                    units=batch_units,
                    passage=passage,
                    unit_result=unit_result,
                    tenant_id=tenant_id,
                    doc_id=doc_id,
                    doc_title=doc_title,
                    doc_type=doc_type,
                    doc_subject=doc_subject,
                    section_title=passage.section_title or "",
                    section_concepts="",
                    domain_context=domain_context,
                ))
                batch_id += 1

        logger.info(
            f"[OSMOSE:ClaimExtractor] Processing {len(batch_tasks)} batches "
            f"with max {self.max_concurrent} concurrent LLM calls..."
        )

        # Phase 3: Exécuter tous les batches en parallèle
        # P4.3 — propager le callback via attribut self (cross thread/loop safe)
        self._on_block_complete = on_block_complete
        try:
            if batch_tasks:
                claims = asyncio.run(self._extract_all_batches_async(batch_tasks))
            else:
                claims = []
        finally:
            # Reset l'attribut pour ne pas polluer un autre call
            self._on_block_complete = None

        logger.info(
            f"[OSMOSE:ClaimExtractor] Extracted {len(claims)} claims "
            f"({self.stats['llm_calls']} LLM calls)"
        )

        return claims, unit_index

    async def _extract_all_batches_async(
        self,
        batch_tasks: List[BatchTask],
    ) -> List[Claim]:
        """
        Exécute tous les batches en parallèle avec un semaphore.

        Args:
            batch_tasks: Liste des tâches de batch

        Returns:
            Liste de toutes les claims extraites
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)
        all_claims: List[Claim] = []
        lock = asyncio.Lock()

        # P4.3 — callback invoqué à chaque batch terminé pour permettre checkpoint Redis
        on_block_complete: Optional[Callable[[Dict[str, Any]], None]] = getattr(
            self, "_on_block_complete", None
        )
        n_total_batches = len(batch_tasks)
        completed_counter = {"n": 0}

        async def process_batch(task: BatchTask) -> None:
            async with semaphore:
                try:
                    claims = await self._extract_claims_from_units_async(task)
                    async with lock:
                        all_claims.extend(claims)
                        completed_counter["n"] += 1
                        # Callback P4.3 — sous lock pour cohérence
                        if on_block_complete is not None:
                            try:
                                on_block_complete({
                                    "block_index": completed_counter["n"],
                                    "total_blocks": n_total_batches,
                                    "claims_in_block": len(claims),
                                    "total_claims_so_far": len(all_claims),
                                    "batch_id": task.batch_id,
                                })
                            except Exception as cb_exc:
                                logger.warning(
                                    f"[OSMOSE:ClaimExtractor] on_block_complete callback failed: {cb_exc}"
                                )
                except Exception as e:
                    logger.error(f"[OSMOSE:ClaimExtractor] Batch {task.batch_id} failed: {e}")

        # Lancer toutes les tâches en parallèle
        await asyncio.gather(*[process_batch(task) for task in batch_tasks])

        return all_claims

    # ── P1.4b — pipeline multi-étapes (Sélection -> Décomposition) ──────────────
    async def _staged_llm_async(self, system: str, user: str) -> str:
        """LLM async pour les stages. Router = burst (vLLM) / DeepInfra automatique."""
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()
        return await router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

    async def _extract_claims_staged_async(self, task: "BatchTask") -> Optional[List[Claim]]:
        """Stage A (sélection check-worthiness) -> Stage B (décomposition minimalité).

        Retourne la liste de Claims, ou None pour demander le fallback legacy (si Stage B
        échoue techniquement, on ne perd pas le batch).
        """
        unit_pairs = [(u.unit_local_id, u.text) for u in task.units]

        # Stage A — sélection
        sel = await self._selection_gate.aclassify(unit_pairs)
        self.stats["llm_calls"] += 1
        kept_set = set(sel.kept_ids)
        kept = [(uid, txt) for uid, txt in unit_pairs if uid in kept_set]
        self.stats["claims_rejected"] += sel.n_dropped
        if not kept:
            return []

        # Stage B — décomposition minimalité + décontextualisation
        decomp = await self._decomposition_stage.adecompose(
            kept, task.passage.text if task.passage else ""
        )
        self.stats["llm_calls"] += 1
        if decomp.judge_failed:
            logger.warning(
                "[OSMOSE:ClaimExtractor] Stage B échec batch %s — fallback legacy",
                task.batch_id,
            )
            return None  # fallback méga-prompt

        claims: List[Claim] = []
        for cand in decomp.claims:
            try:
                claim = self._claim_from_candidate(cand, task)
            except Exception as exc:
                logger.warning("[OSMOSE:ClaimExtractor] mapping candidate échec: %s", exc)
                claim = None
            if claim:
                claims.append(claim)
                self.stats["claims_extracted"] += 1
            else:
                self.stats["claims_rejected"] += 1

        # P1.4b-4 — grounding gate : flag marginal (ne supprime PAS), record quality_scores.
        # Prémisse = passage (la décontextualisation puise le sujet dans le contexte).
        if self._grounding_gate is not None and self._grounding_gate.enabled and claims:
            src = task.passage.text if task.passage else ""
            try:
                items = [(c.text, src) for c in claims]
                # Grounding NLI hors event loop (thread dédié) → ne sérialise pas la
                # concurrence LLM des autres batches. Fallback sync si pas d'executor.
                if self._grounding_executor is not None:
                    grs = await asyncio.get_event_loop().run_in_executor(
                        self._grounding_executor, self._grounding_gate.check_batch, items
                    )
                else:
                    grs = self._grounding_gate.check_batch(items)
                for c, gr in zip(claims, grs):
                    qs = dict(c.quality_scores or {})
                    if gr.entail_score is not None:
                        qs["grounding_entail"] = round(gr.entail_score, 4)
                    qs["grounding_id_anchored"] = 1.0 if gr.identifier_anchored else 0.0
                    qs["grounding_marginal"] = 1.0 if gr.marginal else 0.0
                    c.quality_scores = qs
                    if gr.marginal:
                        self.stats["grounding_marginal"] = self.stats.get("grounding_marginal", 0) + 1
            except Exception as exc:
                logger.warning("[OSMOSE:ClaimExtractor] grounding gate échec: %s", exc)

        return claims

    _MODALITY_TO_CLAIM_TYPE = {
        "assertive": "FACTUAL", "prescriptive": "PRESCRIPTIVE",
        "permissive": "PERMISSIVE", "recommended": "PRESCRIPTIVE",
        "conditional": "CONDITIONAL", "procedural": "PROCEDURAL",
    }

    def _claim_from_candidate(self, cand, task: "BatchTask") -> Optional[Claim]:
        """Mappe un ClaimCandidate (Stage B) -> Claim en RÉUTILISANT _build_claim
        (verbatim GARANTI reconstruit depuis l'unité source). L'énumération `objects[]`
        est jointe dans l'objet du structured_form ; open_predicate=True (canonicalisé en aval)."""
        valid_ids = {u.unit_local_id for u in task.units}
        src_id = next((s for s in cand.source_unit_ids if s in valid_ids), None)
        if src_id is None:
            src_id = task.units[0].unit_local_id if task.units else ""
        raw = {
            "claim_text": cand.self_contained_text,
            "unit_id": src_id,
            "claim_type": self._MODALITY_TO_CLAIM_TYPE.get(cand.modality, "FACTUAL"),
            "confidence": 0.8,
            "structured_form": {
                "subject": cand.subject,
                "predicate": cand.predicate,
                "object": ", ".join(cand.objects) if cand.objects else "",
                "open_predicate": True,
            },
            # Phase B — qualifiers structurés issus du Stage B (parsés par _build_claim)
            "qualifiers": cand.qualifiers,
        }
        return self._build_claim(
            raw=raw, units=task.units, unit_result=task.unit_result,
            passage=task.passage, tenant_id=task.tenant_id, doc_id=task.doc_id,
        )

    async def _extract_claims_from_units_async(
        self,
        task: BatchTask,
    ) -> List[Claim]:
        """
        Version async de _extract_claims_from_units.

        Utilise le LLM Router async pour bénéficier de la parallélisation.
        """
        if not task.units:
            return []

        # P1.4b — chemin STAGED (Sélection -> Décomposition). Retourne None pour
        # demander le fallback sur le chemin legacy (méga-prompt) ci-dessous.
        if self.use_staged_pipeline and self._decomposition_stage is not None:
            staged = await self._extract_claims_staged_async(task)
            if staged is not None:
                return staged

        # Formatter les unités pour le LLM
        units_text = format_units_for_llm(task.units)

        # Construire le prompt V2 (enrichi avec contexte + domain-aware predicates)
        prompt = build_claim_extraction_prompt(
            units_text=units_text,
            doc_title=task.doc_title or "Unknown",
            doc_type=task.doc_type,
            doc_subject=task.doc_subject,
            section_title=task.section_title,
            section_concepts=task.section_concepts,
            domain_context=task.domain_context,
            predicates_table=self._predicates_table,
            # P1.3.5 : passage source complet pour résolution d'anaphores
            passage_context=(task.passage.text if task.passage else ""),
        )

        # DEBUG dump PROMPT input (canary 2026-04-27 phase 2 — diagnostiquer empty claims)
        if not hasattr(self, "_debug_prompt_dump_count"):
            self._debug_prompt_dump_count = 0
        if self._debug_prompt_dump_count < 3:
            self._debug_prompt_dump_count += 1
            logger.info(
                f"[OSMOSE:ClaimExtractor:DEBUG_PROMPT_DUMP {self._debug_prompt_dump_count}/3] "
                f"doc={task.doc_id} batch={task.batch_id} units={len(task.units)} "
                f"prompt_len={len(prompt)}\n"
                f"{'='*70}\n{prompt}\n{'='*70}"
            )

        # Appel LLM async
        try:
            response = await self._call_llm_async(prompt)
            self.stats["llm_calls"] += 1

            # Parser la réponse JSON
            raw_claims = self._parse_llm_response(response)

            # DEBUG : si la réponse est non-vide mais raw_claims=0, log le détail
            if response and not raw_claims and self._debug_prompt_dump_count <= 3:
                logger.warning(
                    f"[OSMOSE:ClaimExtractor:DEBUG_EMPTY] doc={task.doc_id} "
                    f"batch={task.batch_id} units={len(task.units)} "
                    f"response_len={len(response)} response_first200={response[:200]!r}"
                )

        except Exception as e:
            logger.error(f"[OSMOSE:ClaimExtractor] LLM error: {e}")
            return []

        # Construire les Claims avec verbatim garanti
        claims = []
        claims_needing_retry: List[Tuple[Claim, str]] = []  # (claim, raw_predicate)

        for raw in raw_claims:
            try:
                claim, needs_retry = self._build_claim_with_predicate_check(
                    raw=raw,
                    units=task.units,
                    unit_result=task.unit_result,
                    passage=task.passage,
                    tenant_id=task.tenant_id,
                    doc_id=task.doc_id,
                )
                if claim:
                    claims.append(claim)
                    self.stats["claims_extracted"] += 1
                    if needs_retry:
                        claims_needing_retry.append((claim, needs_retry))
                else:
                    self.stats["claims_rejected"] += 1
            except Exception as e:
                logger.warning(f"[OSMOSE:ClaimExtractor] Failed to build claim: {e}")
                self.stats["claims_rejected"] += 1

        # Layer C: Retry LLM pour les prédicats non canoniques
        if claims_needing_retry:
            await self._retry_predicates_async(claims_needing_retry)

        return claims

    async def _retry_predicates_async(
        self,
        claims_to_fix: List[Tuple[Claim, str]],
    ) -> None:
        """
        Layer C — Retry LLM batch pour remapper les prédicats non canoniques.

        Envoie un seul appel LLM avec toutes les claims à corriger,
        puis met à jour les structured_form in-place.
        Gratuit sur vLLM (EC2), seul le temps compte.
        """
        predicates_list = ", ".join(sorted(self.canonical_predicates))

        items_text = "\n".join(
            f'{i+1}. Claim: "{c.text[:120]}" | '
            f'Subject: {c.structured_form["subject"]} | '
            f'Predicate: {raw_pred} | '
            f'Object: {c.structured_form["object"]}'
            for i, (c, raw_pred) in enumerate(claims_to_fix)
        )

        prompt = f"""The following claims have predicates NOT in the allowed list.
For each, choose the CLOSEST valid predicate from: {predicates_list}

If no predicate fits at all, reply "NONE" for that claim.

Claims to fix:
{items_text}

Reply ONLY with a JSON array, one entry per claim:
[{{"index": 1, "predicate": "PART_OF"}}, {{"index": 2, "predicate": "NONE"}}]"""

        try:
            response = await self._call_llm_async(prompt)
            self.stats["llm_calls"] += 1
            fixes = self._parse_llm_response(response)

            if isinstance(fixes, list):
                for fix in fixes:
                    idx = fix.get("index")
                    new_pred = fix.get("predicate", "").strip().upper()
                    if not idx or not isinstance(idx, int):
                        continue
                    if idx < 1 or idx > len(claims_to_fix):
                        continue

                    claim, raw_pred = claims_to_fix[idx - 1]

                    if new_pred in self.canonical_predicates:
                        claim.structured_form["predicate"] = new_pred
                        self.stats["predicates_retried"] += 1
                        logger.debug(
                            f"[OSMOSE:ClaimExtractor] Predicate retry: "
                            f"{raw_pred} → {new_pred}"
                        )
                        # Valider S/O après correction du prédicat
                        subj = claim.structured_form["subject"]
                        obj = claim.structured_form["object"]
                        if not is_valid_entity_name(subj) or not is_valid_entity_name(obj):
                            claim.structured_form = None
                            self.stats["sf_dropped_invalid_entity"] += 1
                    else:
                        # NONE ou invalide → drop le structured_form
                        claim.structured_form = None
                        self.stats["predicates_dropped"] += 1
                        logger.debug(
                            f"[OSMOSE:ClaimExtractor] Predicate dropped after retry: "
                            f"{raw_pred}"
                        )

        except Exception as e:
            logger.warning(f"[OSMOSE:ClaimExtractor] Predicate retry failed: {e}")
            # En cas d'échec du retry, drop tous les structured_form non canoniques
            for claim, raw_pred in claims_to_fix:
                claim.structured_form = None
                self.stats["predicates_dropped"] += 1

    async def _call_llm_async(self, prompt: str) -> str:
        """
        Version async de _call_llm.

        Utilise le LLM Router async pour la parallélisation.
        """
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()

        messages = [
            {"role": "system", "content": "You are an expert in structured knowledge extraction."},
            {"role": "user", "content": prompt}
        ]

        # Appel async via le router (utilise vLLM si burst mode actif)
        response = await router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=0.1,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )

        # DEBUG temporaire (canary 2026-04-27) : dump des 5 premieres responses async.
        if not hasattr(self, "_debug_dump_count_async"):
            self._debug_dump_count_async = 0
        if self._debug_dump_count_async < 5:
            self._debug_dump_count_async += 1
            logger.info(
                f"[OSMOSE:ClaimExtractor:DEBUG_DUMP_ASYNC {self._debug_dump_count_async}/5] "
                f"LLM RAW RESPONSE (first 1500 chars):\n"
                f"{'='*60}\n{response[:1500] if response else '<EMPTY/NULL>'}\n{'='*60}"
            )
        return response

    def _extract_claims_from_units(
        self,
        units: List[AssertionUnit],
        passage: Passage,
        unit_result: UnitIndexResult,
        tenant_id: str,
        doc_id: str,
        doc_title: str,
        doc_type: str,
        doc_subject: str = "",
        section_title: str = "",
        section_concepts: str = "",
        domain_context: str = "",
    ) -> List[Claim]:
        """
        Extrait les claims d'un batch d'unités via LLM.

        Le LLM retourne des unit_ids, pas du texte.
        Le verbatim est reconstruit depuis l'index (GARANTI).
        """
        if not units:
            return []

        # Formatter les unités pour le LLM
        units_text = format_units_for_llm(units)

        # Construire le prompt V2 (enrichi avec contexte + domain-aware predicates)
        prompt = build_claim_extraction_prompt(
            units_text=units_text,
            doc_title=doc_title or "Unknown",
            doc_type=doc_type,
            doc_subject=doc_subject,
            section_title=section_title,
            section_concepts=section_concepts,
            domain_context=domain_context,
            predicates_table=self._predicates_table,
            # P1.3.5 : passage source complet pour résolution d'anaphores
            passage_context=(passage.text if passage else ""),
        )

        # Appel LLM
        try:
            response = self._call_llm(prompt)
            self.stats["llm_calls"] += 1

            # Parser la réponse JSON
            raw_claims = self._parse_llm_response(response)

        except Exception as e:
            logger.error(f"[OSMOSE:ClaimExtractor] LLM error: {e}")
            return []

        # Construire les Claims avec verbatim garanti
        claims = []
        for raw in raw_claims:
            try:
                claim = self._build_claim(
                    raw=raw,
                    units=units,
                    unit_result=unit_result,
                    passage=passage,
                    tenant_id=tenant_id,
                    doc_id=doc_id,
                )
                if claim:
                    claims.append(claim)
                    self.stats["claims_extracted"] += 1
                else:
                    self.stats["claims_rejected"] += 1
            except Exception as e:
                logger.warning(f"[OSMOSE:ClaimExtractor] Failed to build claim: {e}")
                self.stats["claims_rejected"] += 1

        return claims

    def _call_llm(self, prompt: str) -> str:
        """
        Appelle le LLM pour extraire les claims.

        Utilise le LLM Router pour bénéficier du mode Burst (vLLM sur EC2).
        """
        # Utiliser le LLM Router pour le mode Burst
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()

        messages = [
            {"role": "system", "content": "You are an expert in structured knowledge extraction."},
            {"role": "user", "content": prompt}
        ]

        # Appel via le router (utilise vLLM si burst mode actif)
        response = router.complete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=0.1,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )

        # DEBUG temporaire (canary 2026-04-27) : dump des 5 premieres responses LLM
        # pour diagnostiquer si Qwen3-235B retourne du JSON valide ou non.
        # A supprimer apres validation.
        if not hasattr(self, "_debug_dump_count"):
            self._debug_dump_count = 0
        if self._debug_dump_count < 5:
            self._debug_dump_count += 1
            logger.info(
                f"[OSMOSE:ClaimExtractor:DEBUG_DUMP {self._debug_dump_count}/5] "
                f"LLM RAW RESPONSE (first 1500 chars):\n"
                f"{'='*60}\n{response[:1500] if response else '<EMPTY/NULL>'}\n{'='*60}"
            )
        return response

    def _parse_llm_response(self, response: str) -> List[dict]:
        """
        Parse la réponse JSON du LLM.

        Gère les formats malformés avec JSON repair en backstop.
        """
        if not response:
            self.stats["empty_responses"] += 1
            return []

        # Nettoyer la réponse
        response = response.strip()

        # Détecteur de dégénérescence (P3.3 — bug Qwen2.5-14B WEF Presidio).
        # Court-circuite les réponses dégénératives avant tentative parse JSON.
        if self._is_degenerative_response(response):
            self.stats["degenerative_responses"] = self.stats.get("degenerative_responses", 0) + 1
            logger.warning(
                f"[OSMOSE:ClaimExtractor] Degenerative response detected (skipped): "
                f"{repr(response[:120])}..."
            )
            return []

        # Extraire le JSON si encapsulé dans markdown fences
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if end > start:
                response = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end > start:
                response = response[start:end].strip()

        try:
            data = json.loads(response)

            # Gérer différents formats de réponse
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # Le LLM peut encapsuler dans {"claims": [...]}
                if "claims" in data:
                    return data["claims"]
                # Ou retourner un seul objet claim
                else:
                    return [data]
            else:
                return []

        except json.JSONDecodeError as e:
            # Tentative de repair minimal
            repaired = self._try_repair_json(response)
            if repaired is not None:
                self.stats["json_repaired"] += 1
                return repaired
            self.stats["json_parse_errors"] += 1
            logger.warning(f"[OSMOSE:ClaimExtractor] JSON parse error: {e}")
            logger.debug(f"[OSMOSE:ClaimExtractor] Raw response (first 500): {response[:500]}")
            # P3.3 — Forensics : si > 5 errors consécutives, dump le prompt+response problématique
            # pour investigation Qwen dégénérescence (cas WEF Presidio).
            n_errors = self.stats.get("json_parse_errors", 0)
            if n_errors in (5, 10, 25, 50, 100) or (n_errors >= 100 and n_errors % 50 == 0):
                try:
                    from datetime import datetime
                    from pathlib import Path
                    forensics_dir = Path("/data/forensics/claimfirst_qwen_degeneration")
                    forensics_dir.mkdir(parents=True, exist_ok=True)
                    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    fpath = forensics_dir / f"json_parse_error_n{n_errors}_{ts}.txt"
                    fpath.write_text(
                        f"=== JSON Parse Error #{n_errors} ===\n"
                        f"Timestamp: {ts}\n"
                        f"Error: {e}\n\n"
                        f"=== Raw response ===\n{response[:4000]}\n",
                        encoding="utf-8",
                    )
                    logger.error(
                        f"[OSMOSE:ClaimExtractor] Recurring JSON errors detected "
                        f"(n={n_errors}). Forensics saved : {fpath}"
                    )
                except Exception as fexc:
                    logger.warning(f"[OSMOSE:ClaimExtractor] Forensics dump failed: {fexc}")
            return []

    def _try_repair_json(self, response: str) -> Optional[List[dict]]:
        """
        Repair minimal et déterministe du JSON malformé.

        3 opérations safe :
        1. Strip markdown fences
        2. Extraire substring entre premier [{  et dernier }]
        3. Retirer trailing commas

        Returns None si le repair échoue (ABSTAIN).
        """
        import re

        text = response.strip()

        # 1. Strip markdown fences (déjà fait en amont mais au cas où)
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()

        # 2. Extraire substring entre premier [ ou { et dernier ] ou }
        first_bracket = -1
        for i, c in enumerate(text):
            if c in '[{':
                first_bracket = i
                break
        if first_bracket == -1:
            return None

        last_bracket = -1
        for i in range(len(text) - 1, -1, -1):
            if text[i] in ']}':
                last_bracket = i
                break
        if last_bracket == -1 or last_bracket <= first_bracket:
            return None

        text = text[first_bracket:last_bracket + 1]

        # 3. Retirer trailing commas avant ] ou }
        text = re.sub(r',\s*([}\]])', r'\1', text)

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                if "claims" in data:
                    return data["claims"]
                return [data]
            return None
        except json.JSONDecodeError:
            return None

    def _is_degenerative_response(self, response: str) -> bool:
        """Détecte les réponses LLM dégénératives (boucles de tokens répétés).

        Cas observés (bug WEF Presidio Qwen2.5-14B 14/04/2026) :
        - Token court répété >40 fois consécutivement (ex: `U1 U1 U1...`, `N N N...`)
        - Pattern court (10-25 chars) répété >20 fois (ex: `, "region": null, "region": null...`)
        - Diversité des caractères très faible sur la queue (stuck sur une boucle)

        Ces patterns gaspillent des tokens GPU sans produire de claims valides.
        Court-circuit AVANT json.loads pour éviter le forensics dump à répétition.
        """
        if len(response) < 200:
            return False

        import re

        # 1. Token court répété >40 fois (séparé par espaces ou virgules)
        # Capture: début, token (1-12 chars sans espace), répété
        token_repeat = re.search(
            r'(?:^|[\s,])([^\s,"{}\[\]]{1,12})(?:[\s,]+\1){40,}',
            response,
        )
        if token_repeat:
            return True

        # 2. Pattern de 10-30 chars répété >20 fois consécutivement
        # Heuristique : chercher dans les 2000 derniers chars pour éviter O(N²)
        tail = response[-2000:]
        for size in (10, 15, 20, 25):
            for start in range(0, min(500, len(tail) - size * 21), 5):
                pattern = tail[start:start + size]
                # Ignore patterns trop simples (1-2 chars uniques)
                if len(set(pattern)) < 3:
                    continue
                count = tail.count(pattern, start)
                if count > 20:
                    return True

        # 3. Diversité chars trop faible sur la queue (>500 chars avec <8 chars uniques)
        if len(response) >= 500:
            tail500 = response[-500:]
            if len(set(tail500)) < 8:
                return True

        return False

    def _build_claim_with_predicate_check(
        self,
        raw: dict,
        units: List[AssertionUnit],
        unit_result: UnitIndexResult,
        passage: Passage,
        tenant_id: str,
        doc_id: str,
    ) -> Tuple[Optional[Claim], Optional[str]]:
        """
        Construit une Claim avec normalisation de prédicat (Layer A+B).

        Returns:
            (claim, raw_predicate_for_retry)
            - Si prédicat canonique ou normalisé → (claim, None)
            - Si prédicat non mappable → (claim avec structured_form intact, raw_predicate)
              Le caller async enverra un retry LLM (Layer C).
            - Si claim invalide → (None, None)
        """
        claim = self._build_claim_core(raw, units, unit_result, passage, tenant_id, doc_id)
        if not claim:
            return None, None

        # Pas de structured_form → rien à normaliser
        if not claim.structured_form:
            return claim, None

        raw_pred = claim.structured_form["predicate"]

        # Layer B: normalisation statique (domain-aware)
        canonical = self._normalize_effective(raw_pred)
        if canonical:
            if raw_pred.upper() in self.canonical_predicates:
                self.stats["predicates_canonical"] += 1
            else:
                self.stats["predicates_normalized"] += 1
                logger.debug(
                    f"[OSMOSE:ClaimExtractor] Predicate normalized: "
                    f"{raw_pred} → {canonical}"
                )
            claim.structured_form["predicate"] = canonical

            # Layer B.5: validation sujet/objet (stoplist, fragments de phrase)
            subj = claim.structured_form["subject"]
            obj = claim.structured_form["object"]
            if not is_valid_entity_name(subj) or not is_valid_entity_name(obj):
                self.stats["sf_dropped_invalid_entity"] += 1
                logger.debug(
                    f"[OSMOSE:ClaimExtractor] SF dropped — invalid entity: "
                    f"S={subj!r} O={obj!r}"
                )
                claim.structured_form = None

            return claim, None

        # Non mappable par la whitelist.
        # P1.3.5 (open-then-canonicalize) : si le LLM a flaggé open_predicate,
        # CONSERVER le prédicat libre (au lieu de retry/drop) pour préserver le
        # rappel relationnel — à condition que sujet/objet soient des entités valides.
        if claim.open_predicate:
            subj = claim.structured_form["subject"]
            obj = claim.structured_form["object"]
            if not is_valid_entity_name(subj) or not is_valid_entity_name(obj):
                self.stats["sf_dropped_invalid_entity"] += 1
                claim.structured_form = None
                claim.open_predicate = None
            else:
                # Normaliser la forme du prédicat libre (lowercase, espaces → _)
                claim.structured_form["predicate"] = (
                    raw_pred.strip().lower().replace(" ", "_")
                )
                self.stats.setdefault("predicates_open", 0)
                self.stats["predicates_open"] += 1
            return claim, None

        # Non mappable et non flaggé open → marquer pour retry LLM (Layer C)
        return claim, raw_pred

    def _build_claim(
        self,
        raw: dict,
        units: List[AssertionUnit],
        unit_result: UnitIndexResult,
        passage: Passage,
        tenant_id: str,
        doc_id: str,
    ) -> Optional[Claim]:
        """
        Construit une Claim avec normalisation (Layer A+B, sans retry).

        Utilisé par le path synchrone. Les prédicats non mappables
        entraînent le drop du structured_form.
        """
        claim, needs_retry = self._build_claim_with_predicate_check(
            raw, units, unit_result, passage, tenant_id, doc_id,
        )
        if claim and needs_retry:
            # Path sync: pas de retry, on drop le structured_form
            logger.debug(
                f"[OSMOSE:ClaimExtractor] Predicate dropped (sync): {needs_retry}"
            )
            claim.structured_form = None
            self.stats["predicates_dropped"] += 1
        return claim

    def _build_claim_core(
        self,
        raw: dict,
        units: List[AssertionUnit],
        unit_result: UnitIndexResult,
        passage: Passage,
        tenant_id: str,
        doc_id: str,
    ) -> Optional[Claim]:
        """
        Construit une Claim depuis la sortie LLM (logique commune).

        Le verbatim est GARANTI car reconstruit depuis l'index d'unités.
        """
        # Extraire les champs
        claim_text = raw.get("claim_text", "").strip()
        unit_id = raw.get("unit_id", "").strip()
        claim_type_str = raw.get("claim_type", "FACTUAL").upper()
        confidence = float(raw.get("confidence", 0.8))

        # Valider les champs obligatoires
        if not claim_text or len(claim_text) < 10:
            logger.debug(f"[OSMOSE:ClaimExtractor] Rejected: claim_text too short")
            return None

        if not unit_id:
            logger.debug(f"[OSMOSE:ClaimExtractor] Rejected: no unit_id")
            return None

        # Retrouver l'unité source
        unit = unit_result.get_unit_by_local_id(unit_id)
        if not unit:
            logger.debug(f"[OSMOSE:ClaimExtractor] Rejected: unit {unit_id} not found")
            return None

        # VERBATIM GARANTI: reconstruit depuis l'index
        verbatim_quote = unit.text

        # Parser le type de claim
        try:
            claim_type = ClaimType(claim_type_str)
        except ValueError:
            claim_type = ClaimType.FACTUAL

        # Parser le scope
        scope_data = raw.get("scope", {})
        scope = ClaimScope(
            version=scope_data.get("version"),
            region=scope_data.get("region"),
            edition=scope_data.get("edition"),
            conditions=scope_data.get("conditions", []),
        )

        # Parser le structured_form
        structured_form = None
        open_predicate: Optional[bool] = None
        sf_raw = raw.get("structured_form")
        if sf_raw and isinstance(sf_raw, dict):
            subj = sf_raw.get("subject", "").strip()
            pred = sf_raw.get("predicate", "").strip()
            obj = sf_raw.get("object", "").strip()
            if subj and pred and obj:
                structured_form = {
                    "subject": subj,
                    "predicate": pred,
                    "object": obj,
                }
                # P1.3.5 (open-then-canonicalize) : flag prédicat libre
                if bool(sf_raw.get("open_predicate", False)):
                    open_predicate = True

        # Phase B (25/05/2026) : parser les qualifiers (domain-agnostic)
        qualifiers = self._parse_qualifiers(raw.get("qualifiers"))

        # Générer l'ID unique
        claim_id = f"claim_{uuid.uuid4().hex[:12]}"

        # Construire la Claim
        return Claim(
            claim_id=claim_id,
            tenant_id=tenant_id,
            doc_id=doc_id,
            text=claim_text,
            claim_type=claim_type,
            scope=scope,
            verbatim_quote=verbatim_quote,
            passage_id=passage.passage_id,
            unit_ids=[unit.unit_global_id],
            confidence=confidence,
            structured_form=structured_form,
            qualifiers=qualifiers,
            open_predicate=open_predicate,
        )

    @staticmethod
    def _parse_qualifiers(quals_raw: Any) -> List[ClaimQualifier]:
        """Parse la liste de qualifiers de la sortie LLM (Phase B, tolérant).

        Filtre les entrées mal formées ou de type inconnu plutôt que d'échouer.
        Domain-agnostic : les 5 types sont universels (cf QualifierType).
        """
        if not isinstance(quals_raw, list):
            return []
        result: List[ClaimQualifier] = []
        for q in quals_raw:
            if not isinstance(q, dict):
                continue
            qtype = str(q.get("qualifier_type", "")).strip().lower()
            value = str(q.get("value", "")).strip()
            if not qtype or not value:
                continue
            try:
                qtype_enum = QualifierType(qtype)
            except ValueError:
                # Type hors whitelist → on ignore (pas d'invention de type)
                continue
            try:
                conf = float(q.get("confidence", 1.0))
            except (TypeError, ValueError):
                conf = 1.0
            conf = max(0.0, min(1.0, conf))
            result.append(
                ClaimQualifier(qualifier_type=qtype_enum, value=value, confidence=conf)
            )
        return result

    def get_stats(self) -> dict:
        """Retourne les statistiques d'extraction."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "units_indexed": 0,
            "llm_calls": 0,
            "tokens_used": 0,
            "claims_extracted": 0,
            "claims_rejected": 0,
            "predicates_canonical": 0,
            "predicates_normalized": 0,
            "predicates_retried": 0,
            "predicates_dropped": 0,
            "sf_dropped_invalid_entity": 0,
            "json_repaired": 0,
            "json_parse_errors": 0,
            "empty_responses": 0,
        }


class MockLLMClient:
    """
    Client LLM mock pour les tests.

    Retourne des réponses prédéfinies basées sur le contenu.
    """

    def generate(self, prompt: str) -> str:
        """Génère une réponse mock."""
        # Détecter les patterns dans le prompt pour générer des claims
        claims = []

        # Pattern: TLS version
        if "tls" in prompt.lower() or "encryption" in prompt.lower():
            claims.append({
                "claim_text": "TLS 1.2 or higher is required for all connections",
                "claim_type": "PRESCRIPTIVE",
                "unit_id": "U1",
                "confidence": 0.9,
                "scope": {"version": None, "region": None, "edition": None, "conditions": []}
            })

        # Pattern: backup
        if "backup" in prompt.lower():
            claims.append({
                "claim_text": "Daily backups are performed automatically",
                "claim_type": "FACTUAL",
                "unit_id": "U1",
                "confidence": 0.85,
                "scope": {"version": None, "region": None, "edition": None, "conditions": []}
            })

        return json.dumps(claims)


__all__ = [
    "ClaimExtractor",
    "MockLLMClient",
    "build_claim_extraction_prompt",
    "CANONICAL_PREDICATES",
    "normalize_predicate",
]
