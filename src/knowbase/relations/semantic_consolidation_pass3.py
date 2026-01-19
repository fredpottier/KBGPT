"""
OSMOSE Pass 3: Semantic Consolidation

ADR_GRAPH_FIRST_ARCHITECTURE - Phase B.3

Pass 3 est la SEULE source de relations sémantiques prouvées.
Chaque relation DOIT avoir:
- evidence_context_ids[] non vide
- Quote extractive du texte source
- Confidence basée sur récurrence + qualité quote

Pipeline:
1. Candidate Generation: co-présence Topic/Section, récurrence ≥2
2. Extractive Verification: LLM cite le passage exact ou ABSTAIN
3. Relation Writing: persiste uniquement si preuve valide

IMPORTANT - Règles critiques:
- JAMAIS de relation sans evidence_context_ids
- ABSTAIN préféré à relation douteuse
- Multi-evidence requis pour sources faibles

Date: 2026-01-06
"""

import asyncio
import logging
import re
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class VerificationResult(str, Enum):
    """Résultat de la vérification extractive."""
    VERIFIED = "verified"      # Quote trouvée, relation confirmée
    ABSTAIN = "abstain"        # Pas de quote fiable, on s'abstient
    CONTRADICTED = "contradicted"  # Evidence contradictoire trouvée


@dataclass
class RelationCandidate:
    """
    Candidat de relation à vérifier.

    Généré par co-présence dans Topic/Section.

    V2 (2026-01-16): Ajout surface_forms et anchor_items pour
    vérification extractive basée sur les formes attestées dans le texte
    (pas les labels canoniques).
    """
    subject_concept_id: str
    subject_name: str                # Label canonique (pour identification)
    object_concept_id: str
    object_name: str                 # Label canonique (pour identification)

    # Co-présence
    shared_sections: List[str]       # section_ids des sections communes
    shared_topics: List[str]         # topic_ids des topics communs
    co_occurrence_count: int         # Nombre de co-occurrences

    # Scores de candidature
    candidate_score: float = 0.0
    recurrence_score: float = 0.0    # Basé sur ≥2 sections

    # === V2: Surface forms et anchors pour vérification extractive ===
    # Surface forms = concept_name des ProtoConcepts (formes attestées dans le texte)
    subject_surface_forms: List[str] = field(default_factory=list)  # top-k concept_name
    object_surface_forms: List[str] = field(default_factory=list)

    # Anchor items = DocItems où les concepts sont ancrés (via ANCHORED_IN)
    subject_anchor_items: List[str] = field(default_factory=list)   # item_id des DocItems
    object_anchor_items: List[str] = field(default_factory=list)

    # Sections des anchors (pour debug/traçabilité)
    subject_section_ids: List[str] = field(default_factory=list)
    object_section_ids: List[str] = field(default_factory=list)


@dataclass
class VerifiedRelation:
    """
    Relation vérifiée avec preuve extractive.

    Prête à être persistée dans Neo4j.
    """
    subject_concept_id: str
    object_concept_id: str
    predicate: str

    # Preuve extractive (obligatoire)
    evidence_quote: str              # Citation exacte du texte
    evidence_context_ids: List[str]  # Sections où la preuve existe

    # Métadonnées
    confidence: float
    verification_result: VerificationResult
    extraction_model: str = "gpt-4o-mini"
    verified_at: datetime = field(default_factory=datetime.now)


@dataclass
class Pass3Stats:
    """Statistiques Pass 3."""
    candidates_generated: int = 0
    candidates_verified: int = 0
    relations_created: int = 0
    abstained: int = 0
    contradicted: int = 0
    processing_time_ms: float = 0.0


class CandidateGenerator:
    """
    Génère des candidats de relations basés sur co-présence.

    Critères:
    1. Co-présence dans le même Topic ou Section
    2. Récurrence dans ≥2 sections (pour filtrer le bruit)
    3. Exclusion des paires déjà dans le KG (optionnel)
    """

    # Seuil minimum de co-occurrences
    MIN_CO_OCCURRENCES = 2

    # Score minimum pour être candidat
    MIN_CANDIDATE_SCORE = 0.3

    def __init__(
        self,
        neo4j_client,
        tenant_id: str = "default"
    ):
        """
        Initialise le générateur.

        Args:
            neo4j_client: Client Neo4j connecté
            tenant_id: ID du tenant
        """
        self.neo4j = neo4j_client
        self.tenant_id = tenant_id

        self._stats = {
            "concepts_analyzed": 0,
            "pairs_evaluated": 0,
            "candidates_generated": 0
        }

    def generate_candidates(
        self,
        document_id: str,
        max_candidates: int = 100
    ) -> List[RelationCandidate]:
        """
        Génère des candidats de relations pour un document.

        Phase 1 (Agnostique):
        - Filtre sections par relation_likelihood_tier (HIGH/MEDIUM only)
        - Exclut les concepts HUB
        - Exclut les paires déjà reliées (avec evidence)
        - Score basé sur recurrence + avg_relation_likelihood

        Args:
            document_id: ID du document source
            max_candidates: Nombre max de candidats à générer

        Returns:
            Liste de RelationCandidate triés par score
        """
        logger.info(f"[OSMOSE:Pass3] Generating candidates for {document_id}")

        # ADR_STRUCTURAL_CONTEXT_ALIGNMENT (2026-01-11) + Option C (2026-01-16):
        # Utiliser section_id en priorité, context_id en fallback
        # pour trouver les paires de concepts co-localisés dans la même section
        co_presence_query = """
        // Phase 1: Trouver paires de CanonicalConcepts via leurs ProtoConcepts
        // qui partagent le même section_id structurel dans le document
        MATCH (p1:ProtoConcept {tenant_id: $tenant_id, doc_id: $document_id})
              -[:INSTANCE_OF]->(c1:CanonicalConcept {tenant_id: $tenant_id})
        MATCH (p2:ProtoConcept {tenant_id: $tenant_id, doc_id: $document_id})
              -[:INSTANCE_OF]->(c2:CanonicalConcept {tenant_id: $tenant_id})

        // Calculer l'identifiant de section: section_id en priorité, context_id en fallback
        WITH p1, p2, c1, c2,
             COALESCE(p1.section_id, p1.context_id) AS p1_section,
             COALESCE(p2.section_id, p2.context_id) AS p2_section

        WHERE c1.canonical_id < c2.canonical_id  // Anti-doublon
          AND p1_section = p2_section            // Même section structurelle
          AND p1_section IS NOT NULL             // Exclure protos sans section
          AND coalesce(c1.concept_type, '') <> 'TOPIC'
          AND coalesce(c2.concept_type, '') <> 'TOPIC'
          // Filtre HUB: exclure si les deux concepts sont HUB
          AND NOT (coalesce(c1.is_hub, false) = true AND coalesce(c2.is_hub, false) = true)

        // Agréger sections communes
        WITH c1, c2, collect(DISTINCT p1_section) AS shared_sections

        // Filtre minimum co-occurrences
        WHERE size(shared_sections) >= $min_co_occurrences

        // Exclure paires déjà reliées (avec evidence)
        // Direction c1 -> c2
        OPTIONAL MATCH (c1)-[r1]->(c2)
        WHERE type(r1) <> 'MENTIONED_IN'
          AND type(r1) <> 'CO_OCCURS_IN_CORPUS'
          AND r1.evidence_context_ids IS NOT NULL
          AND size(r1.evidence_context_ids) > 0
        WITH c1, c2, shared_sections, count(r1) AS existing_forward

        // Direction c2 -> c1
        OPTIONAL MATCH (c2)-[r2]->(c1)
        WHERE type(r2) <> 'MENTIONED_IN'
          AND type(r2) <> 'CO_OCCURS_IN_CORPUS'
          AND r2.evidence_context_ids IS NOT NULL
          AND size(r2.evidence_context_ids) > 0
        WITH c1, c2, shared_sections,
             existing_forward, count(r2) AS existing_backward

        // Garder uniquement les paires sans relation prouvée
        WHERE existing_forward = 0 AND existing_backward = 0

        RETURN c1.canonical_id AS subject_id,
               c1.canonical_name AS subject_name,
               coalesce(c1.is_hub, false) AS subject_is_hub,
               c2.canonical_id AS object_id,
               c2.canonical_name AS object_name,
               coalesce(c2.is_hub, false) AS object_is_hub,
               shared_sections,
               size(shared_sections) AS co_occurrence_count,
               0.5 AS avg_relation_likelihood  // Default, tier not available via ProtoConcepts
        ORDER BY co_occurrence_count DESC
        LIMIT $max_candidates
        """

        candidates = []
        stats_before_filter = 0

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    co_presence_query,
                    document_id=document_id,
                    tenant_id=self.tenant_id,
                    min_co_occurrences=self.MIN_CO_OCCURRENCES,
                    max_candidates=max_candidates * 2  # Marge pour filtres Python
                )

                for record in result:
                    stats_before_filter += 1

                    co_occurrence_count = record["co_occurrence_count"]
                    avg_rl = record["avg_relation_likelihood"] or 0.5
                    subject_is_hub = record["subject_is_hub"]
                    object_is_hub = record["object_is_hub"]

                    # Score Phase 1 (agnostique): recurrence + avg_relation_likelihood
                    recurrence_score = min(1.0, co_occurrence_count / 5.0)
                    candidate_score = (
                        0.7 * recurrence_score +
                        0.3 * avg_rl
                    )

                    # Filtre score minimum
                    if candidate_score < self.MIN_CANDIDATE_SCORE:
                        continue

                    # Filtre HUB additionnel: si un seul est HUB, on tolère
                    # mais on baisse le score
                    if subject_is_hub or object_is_hub:
                        candidate_score *= 0.7  # Pénalité HUB

                    candidate = RelationCandidate(
                        subject_concept_id=record["subject_id"],
                        subject_name=record["subject_name"],
                        object_concept_id=record["object_id"],
                        object_name=record["object_name"],
                        shared_sections=record["shared_sections"],
                        shared_topics=[],  # Pas utilisé en Phase 1
                        co_occurrence_count=co_occurrence_count,
                        candidate_score=candidate_score,
                        recurrence_score=recurrence_score
                    )

                    candidates.append(candidate)
                    self._stats["candidates_generated"] += 1

                self._stats["pairs_evaluated"] = stats_before_filter

        except Exception as e:
            logger.error(f"[OSMOSE:Pass3] Candidate generation failed: {e}")

        # Trier et limiter
        candidates.sort(key=lambda c: (c.co_occurrence_count, c.candidate_score), reverse=True)
        candidates = candidates[:max_candidates]

        # KPIs Phase 1
        logger.info(
            f"[OSMOSE:Pass3] Generated {len(candidates)} candidates "
            f"(from {stats_before_filter} pairs, "
            f"min_co_occurrences={self.MIN_CO_OCCURRENCES}, "
            f"tier_filter=HIGH/MEDIUM/NULL)"
        )

        # V2: Enrichir les candidats avec surface_forms et anchor_items
        if candidates:
            logger.info(f"[OSMOSE:Pass3] Enriching {len(candidates)} candidates with surface forms...")
            candidates = self._enrich_candidates_with_surface_forms(candidates, document_id)

        return candidates

    def _enrich_candidates_with_surface_forms(
        self,
        candidates: List[RelationCandidate],
        document_id: str,
        top_k: int = 5
    ) -> List[RelationCandidate]:
        """
        Enrichit les candidats avec les surface forms et anchor items.

        Pour chaque CanonicalConcept dans un candidat, récupère:
        - top-k surface forms (concept_name des ProtoConcepts, dédupliqués)
        - anchor items (item_id des DocItems via ANCHORED_IN)
        - section_ids des anchors

        Args:
            candidates: Liste de candidats à enrichir
            document_id: ID du document
            top_k: Nombre max de surface forms par concept

        Returns:
            Liste de candidats enrichis
        """
        # Collecter tous les canonical_ids uniques
        cc_ids = set()
        for c in candidates:
            cc_ids.add(c.subject_concept_id)
            cc_ids.add(c.object_concept_id)

        # Récupérer surface forms et anchors pour tous les concepts en une requête
        surface_forms_query = """
        // Récupérer surface forms et anchors pour les CanonicalConcepts
        UNWIND $cc_ids AS cc_id

        MATCH (p:ProtoConcept {tenant_id: $tenant_id, doc_id: $document_id})
              -[:INSTANCE_OF]->(c:CanonicalConcept {canonical_id: cc_id, tenant_id: $tenant_id})

        // Récupérer les DocItems ancrés (Option C)
        OPTIONAL MATCH (p)-[:ANCHORED_IN]->(d:DocItem)

        WITH cc_id, p.concept_name AS surface_form, p.section_id AS proto_section,
             d.item_id AS anchor_item, d.section_id AS anchor_section

        // Agréger par canonical_id
        WITH cc_id,
             collect(DISTINCT surface_form) AS all_surface_forms,
             collect(DISTINCT anchor_item) AS all_anchor_items,
             collect(DISTINCT proto_section) AS all_sections

        // Filtrer surface forms (top-k, non vides, longueur > 2)
        WITH cc_id,
             [sf IN all_surface_forms WHERE sf IS NOT NULL AND size(sf) > 2][0..$top_k] AS surface_forms,
             [ai IN all_anchor_items WHERE ai IS NOT NULL] AS anchor_items,
             [s IN all_sections WHERE s IS NOT NULL] AS section_ids

        RETURN cc_id, surface_forms, anchor_items, section_ids
        """

        # Cache pour les résultats
        cc_data: Dict[str, Dict] = {}

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    surface_forms_query,
                    cc_ids=list(cc_ids),
                    document_id=document_id,
                    tenant_id=self.tenant_id,
                    top_k=top_k
                )

                for record in result:
                    cc_id = record["cc_id"]
                    cc_data[cc_id] = {
                        "surface_forms": record["surface_forms"] or [],
                        "anchor_items": record["anchor_items"] or [],
                        "section_ids": record["section_ids"] or []
                    }

        except Exception as e:
            logger.error(f"[OSMOSE:Pass3] Failed to get surface forms: {e}")
            return candidates  # Retourner candidats non enrichis

        # Enrichir chaque candidat
        for candidate in candidates:
            subj_data = cc_data.get(candidate.subject_concept_id, {})
            obj_data = cc_data.get(candidate.object_concept_id, {})

            candidate.subject_surface_forms = subj_data.get("surface_forms", [])
            candidate.object_surface_forms = obj_data.get("surface_forms", [])
            candidate.subject_anchor_items = subj_data.get("anchor_items", [])
            candidate.object_anchor_items = obj_data.get("anchor_items", [])
            candidate.subject_section_ids = subj_data.get("section_ids", [])
            candidate.object_section_ids = obj_data.get("section_ids", [])

        # Stats
        enriched_count = sum(
            1 for c in candidates
            if c.subject_surface_forms and c.object_surface_forms
        )
        logger.info(
            f"[OSMOSE:Pass3] Enriched {enriched_count}/{len(candidates)} candidates "
            f"with surface forms"
        )

        return candidates


class ExtractiveVerifier:
    """
    Vérifie les candidats avec extraction de preuve.

    Principe:
    - Le LLM doit citer le passage EXACT qui prouve la relation
    - Si pas de citation trouvable → ABSTAIN
    - La citation doit être vérifiable dans le texte source

    C'est la garde-fou principale contre les hallucinations.
    """

    # =========================================================================
    # PREDICATS AGNOSTIQUES - Invariants structurels du langage documentaire
    # =========================================================================
    # Ces prédicats ne portent aucune sémantique métier, uniquement des
    # relations logiques universelles observables dans des textes.
    # Validé: Claude + ChatGPT consensus (2026-01-07)
    # =========================================================================

    VALID_PREDICATES = {
        # --- Dépendances (contraintes fonctionnelles) ---
        "REQUIRES",           # A nécessite B (hard dependency)
        "USES",               # A utilise B (soft dependency)

        # --- Hiérarchie / Composition (taxonomies) ---
        "PART_OF",            # A est composant de B
        "SUBTYPE_OF",         # A est un sous-type de B
        "EXTENDS",            # A étend B (héritage, extension)

        # --- Implémentation / Conformité (abstrait → concret) ---
        "IMPLEMENTS",         # A est une réalisation concrète de B
        "COMPLIES_WITH",      # A est conforme à B (relation normative)

        # --- Capacités / Compatibilité (relations systémiques) ---
        "ENABLES",            # A rend possible B
        "SUPPORTS",           # A est compatible avec B
        "INTEGRATES_WITH",    # A s'intègre avec B (bidirectionnel)

        # --- Cycle de vie (temporel) ---
        "REPLACES",           # A remplace B
        "VERSION_OF",         # A est une version de B

        # --- Causalité (avec preuve obligatoire) ---
        "CAUSES",             # A cause B
        "PREVENTS",           # A empêche B

        # --- Scope / Applicabilité ---
        "APPLIES_TO",         # A s'applique à B (périmètre, conditions)
    }
    # NOTE: ASSOCIATED_WITH supprimé volontairement (fallback générique = poison pour KG agnostique)

    # Mapping des variantes linguistiques vers les prédicats canoniques
    PREDICATE_ALIASES = {
        # Variantes de REQUIRES
        "REQUIRE": "REQUIRES",
        "REQUIRING": "REQUIRES",
        "NEEDS": "REQUIRES",
        "DEPENDS_ON": "REQUIRES",
        "DEPENDS": "REQUIRES",
        "DEPENDENT_ON": "REQUIRES",

        # Variantes de USES
        "USE": "USES",
        "USING": "USES",
        "UTILIZES": "USES",
        "EMPLOYS": "USES",
        "LEVERAGES": "USES",

        # Variantes de PART_OF
        "INCLUDES": "PART_OF",
        "INCLUDE": "PART_OF",
        "CONTAINS": "PART_OF",
        "IS_PART_OF": "PART_OF",
        "COMPONENT_OF": "PART_OF",
        "BELONGS_TO": "PART_OF",

        # Variantes de SUBTYPE_OF
        "IS_A": "SUBTYPE_OF",
        "TYPE_OF": "SUBTYPE_OF",
        "KIND_OF": "SUBTYPE_OF",
        "INSTANCE_OF": "SUBTYPE_OF",
        "SPECIALIZES": "SUBTYPE_OF",

        # Variantes de EXTENDS
        "EXTEND": "EXTENDS",
        "EXTENDING": "EXTENDS",
        "AUGMENTS": "EXTENDS",
        "ENHANCES": "EXTENDS",

        # Variantes de IMPLEMENTS
        "IMPLEMENT": "IMPLEMENTS",
        "IMPLEMENTING": "IMPLEMENTS",
        "REALIZES": "IMPLEMENTS",
        "REALISES": "IMPLEMENTS",
        "PROVIDES": "IMPLEMENTS",  # "provides capability" = implements
        "PROVIDE": "IMPLEMENTS",

        # Variantes de COMPLIES_WITH
        "COMPLIES": "COMPLIES_WITH",
        "CONFORMS_TO": "COMPLIES_WITH",
        "ADHERES_TO": "COMPLIES_WITH",
        "FOLLOWS": "COMPLIES_WITH",
        "MEETS": "COMPLIES_WITH",

        # Variantes de ENABLES
        "ENABLE": "ENABLES",
        "ENABLING": "ENABLES",
        "ALLOWS": "ENABLES",
        "PERMITS": "ENABLES",
        "MAKES_POSSIBLE": "ENABLES",

        # Variantes de SUPPORTS
        "SUPPORT": "SUPPORTS",
        "SUPPORTING": "SUPPORTS",
        "COMPATIBLE_WITH": "SUPPORTS",
        "WORKS_WITH": "SUPPORTS",

        # Variantes de INTEGRATES_WITH
        "INTEGRATES": "INTEGRATES_WITH",
        "INTEGRATE": "INTEGRATES_WITH",
        "CONNECTS_TO": "INTEGRATES_WITH",
        "INTERFACES_WITH": "INTEGRATES_WITH",

        # Variantes de REPLACES
        "REPLACE": "REPLACES",
        "REPLACING": "REPLACES",
        "SUPERSEDES": "REPLACES",
        "OBSOLETES": "REPLACES",
        "DEPRECATES": "REPLACES",

        # Variantes de VERSION_OF
        "VERSION": "VERSION_OF",
        "VARIANT_OF": "VERSION_OF",
        "EDITION_OF": "VERSION_OF",
        "RELEASE_OF": "VERSION_OF",

        # Variantes de CAUSES
        "CAUSE": "CAUSES",
        "CAUSING": "CAUSES",
        "LEADS_TO": "CAUSES",
        "RESULTS_IN": "CAUSES",
        "TRIGGERS": "CAUSES",

        # Variantes de PREVENTS
        "PREVENT": "PREVENTS",
        "PREVENTING": "PREVENTS",
        "BLOCKS": "PREVENTS",
        "MITIGATES": "PREVENTS",
        "AVOIDS": "PREVENTS",

        # Variantes de APPLIES_TO
        "APPLIES": "APPLIES_TO",
        "APPLY": "APPLIES_TO",
        "RELEVANT_TO": "APPLIES_TO",
        "TARGETS": "APPLIES_TO",
        "CONCERNS": "APPLIES_TO",
    }

    def __init__(
        self,
        llm_router,
        tenant_id: str = "default"
    ):
        """
        Initialise le vérificateur.

        Args:
            llm_router: Router LLM pour appels extractifs
            tenant_id: ID du tenant
        """
        self.llm = llm_router
        self.tenant_id = tenant_id

        self._stats = {
            "verified": 0,
            "abstained": 0,
            "contradicted": 0
        }

    async def verify_candidate(
        self,
        candidate: RelationCandidate,
        context_texts: Dict[str, str],
        text_window: Optional["TextWindow"] = None
    ) -> Optional[VerifiedRelation]:
        """
        Vérifie un candidat de relation.

        V2 (2026-01-16): Utilise TextWindow avec surface forms.
        L'escalade est gérée par verify_candidate_with_escalation().

        Args:
            candidate: Candidat à vérifier
            context_texts: {context_id: text} des sections (fallback si pas de window)
            text_window: Fenêtre de texte construite par TextWindowBuilder

        Returns:
            VerifiedRelation si vérifié, None si ABSTAIN
        """
        # Utiliser text_window si disponible, sinon fallback sur context_texts
        if text_window and text_window.text:
            combined_text = text_window.text
            logger.debug(
                f"[OSMOSE:Pass3] Using TextWindow level {text_window.escalation_level} "
                f"({text_window.char_count} chars, {len(text_window.item_ids)} items)"
            )
        elif context_texts:
            combined_text = "\n\n---\n\n".join([
                f"[Section: {ctx_id}]\n{text}"
                for ctx_id, text in context_texts.items()
            ])
        else:
            logger.debug(f"[OSMOSE:Pass3] No context for candidate, abstaining")
            self._stats["abstained"] += 1
            return None

        # Limiter la taille du texte
        MAX_TEXT_CHARS = 6000  # Réduit pour fenêtre ciblée
        if len(combined_text) > MAX_TEXT_CHARS:
            combined_text = combined_text[:MAX_TEXT_CHARS]

        # Prompt extractif avec surface forms
        prompt = self._build_extractive_prompt(candidate, combined_text)

        try:
            from knowbase.common.llm_router import TaskType

            response = await self.llm.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[
                    {"role": "system", "content": EXTRACTIVE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,  # Déterministe
                max_tokens=500,
                response_format={"type": "json_object"}
            )

            # Parser la réponse - retourne (result, abstain_reason)
            # Passer les section_ids de la TextWindow comme fallback pour evidence_context_ids
            fallback_context_ids = text_window.section_ids if text_window else []
            result, abstain_reason = self._parse_verification_response(
                response, candidate, context_texts or {}, combined_text, fallback_context_ids
            )

            if result:
                self._stats["verified"] += 1
                return result
            else:
                self._stats["abstained"] += 1
                # Stocker la raison pour l'escalade (attribut dynamique sur le dataclass)
                candidate._last_abstain_reason = abstain_reason
                logger.debug(f"[OSMOSE:Pass3] Stored abstain_reason: {abstain_reason}")
                return None

        except Exception as e:
            logger.error(f"[OSMOSE:Pass3] Verification failed: {e}")
            self._stats["abstained"] += 1
            return None

    async def verify_candidate_with_escalation(
        self,
        candidate: RelationCandidate,
        document_id: str,
        window_builder: "TextWindowBuilder"
    ) -> Tuple[Optional[VerifiedRelation], int, Optional[str]]:
        """
        Vérifie un candidat avec escalade automatique de la fenêtre de texte.

        Stratégie:
        - Niveau 1 (±1 voisin): essai initial
        - Niveau 2 (±3 voisins): si ABSTAIN reason = "no_single_sentence_mentions_both"
        - Niveau 3 (sections entières): si toujours ABSTAIN même raison

        Args:
            candidate: Candidat à vérifier
            document_id: ID du document
            window_builder: Builder pour construire les fenêtres

        Returns:
            Tuple (VerifiedRelation ou None, niveau utilisé, raison d'abstention)
        """
        max_escalation = 3
        escalation_trigger_reasons = {
            "no_single_sentence_mentions_both",
            "quote_missing_surface_forms",
            "offset_out_of_bounds"
        }

        for level in range(1, max_escalation + 1):
            # Construire la fenêtre de texte
            window = window_builder.build_window(candidate, document_id, escalation_level=level)

            if not window:
                logger.debug(f"[OSMOSE:Pass3] Could not build window level {level}")
                continue

            # Vérifier
            result = await self.verify_candidate(candidate, {}, text_window=window)

            if result:
                logger.info(f"[OSMOSE:Pass3] ✓ Verified at escalation level {level}")
                return result, level, None

            # Récupérer la raison d'abstention
            abstain_reason = getattr(candidate, '_last_abstain_reason', 'unknown')
            logger.debug(f"[OSMOSE:Pass3] Level {level} returned: abstain_reason={abstain_reason}")

            # Décider si on escalade
            if level < max_escalation and abstain_reason in escalation_trigger_reasons:
                logger.info(
                    f"[OSMOSE:Pass3] ↗ Escalating from level {level} to {level + 1} "
                    f"(reason: {abstain_reason})"
                )
                continue
            else:
                # Pas d'escalade (raison différente ou max atteint)
                if level == max_escalation:
                    logger.debug(f"[OSMOSE:Pass3] Max escalation reached at level {level}")
                else:
                    logger.debug(f"[OSMOSE:Pass3] No escalation: reason '{abstain_reason}' not in triggers")
                break

        return None, level, abstain_reason

    def _build_extractive_prompt(
        self,
        candidate: RelationCandidate,
        combined_text: str
    ) -> str:
        """
        Construit le prompt de vérification extractive.

        V2 (2026-01-16): Utilise surface_forms (formes attestées) au lieu
        des labels canoniques pour trouver les mentions dans le texte.
        """
        text_marker = "=== TEXT START ==="
        text_end_marker = "=== TEXT END ==="

        # Préparer les surface forms (ou fallback sur le label canonique)
        subject_forms = candidate.subject_surface_forms or [candidate.subject_name]
        object_forms = candidate.object_surface_forms or [candidate.object_name]

        # Limiter à 8 surface forms max
        subject_forms = subject_forms[:8]
        object_forms = object_forms[:8]

        return f"""Find if there is an EXPLICIT relationship between concept A and concept B in the text.

## Concept A
- canonical_label: {candidate.subject_name}
- surface_forms (look for THESE in the text): {subject_forms}

## Concept B
- canonical_label: {candidate.object_name}
- surface_forms (look for THESE in the text): {object_forms}

{text_marker}
{combined_text}
{text_end_marker}

## TASK
1. Find a SINGLE sentence that contains at least one surface_form of A AND one surface_form of B
2. Check if there is an EXPLICIT relationship stated (not just co-occurrence)
3. Return character offsets (0-based, relative to TEXT START marker) of the evidence sentence

## VALID RELATION TYPES
REQUIRES, USES, PART_OF, SUBTYPE_OF, EXTENDS, IMPLEMENTS, COMPLIES_WITH, ENABLES, SUPPORTS, INTEGRATES_WITH, REPLACES, VERSION_OF, CAUSES, PREVENTS, APPLIES_TO

## OUTPUT (JSON only)

If relation found:
{{"decision": "RELATION", "relation_type": "TYPE", "evidence_start": N, "evidence_end": M, "matched_surface_form_A": "exact form found", "matched_surface_form_B": "exact form found", "confidence": 0.0-1.0}}

If no relation:
{{"decision": "ABSTAIN", "reason": "no_single_sentence_mentions_both|mentions_both_but_no_linking_claim", "evidence_start": 0, "evidence_end": 0, "confidence": 0.0}}"""

    def _parse_verification_response(
        self,
        response: str,
        candidate: RelationCandidate,
        context_texts: Dict[str, str],
        combined_text: str,
        fallback_context_ids: Optional[List[str]] = None
    ) -> Tuple[Optional[VerifiedRelation], Optional[str]]:
        """
        Parse et valide la réponse du LLM.

        V2 (2026-01-16): Gère le nouveau format avec decision/relation_type
        et valide que la quote contient les surface forms.

        Returns:
            Tuple (VerifiedRelation ou None, reason d'abstention ou None)
        """
        import json

        try:
            # DEBUG - voir réponse brute
            logger.info(f"[OSMOSE:Pass3:RAW] Response: {response[:300] if response else 'None'}")

            # Extraire JSON
            text = response.strip()
            json_match = re.search(r'\{.*\}', text, re.DOTALL)

            if not json_match:
                logger.warning("[OSMOSE:Pass3] No JSON in LLM response")
                return None, "parse_error"

            data = json.loads(json_match.group(0))

            # V2: Gérer nouveau format (decision) et ancien format (relation)
            decision = data.get("decision", "").upper().strip()
            relation_type = data.get("relation_type", data.get("relation", "")).upper().strip()

            # ABSTAIN = pas de relation trouvée
            if decision == "ABSTAIN" or relation_type == "ABSTAIN" or not relation_type:
                reason = data.get("reason", "unknown")
                logger.debug(f"[OSMOSE:Pass3] LLM abstained: {reason}")
                return None, reason

            # Normaliser prédicat via aliases
            predicate = self.PREDICATE_ALIASES.get(relation_type, relation_type)

            # Valider prédicat
            if predicate not in self.VALID_PREDICATES:
                logger.debug(f"[OSMOSE:Pass3] Invalid predicate: {relation_type}")
                return None, "invalid_predicate"

            # === OFFSET-BASED EXTRACTION ===
            evidence_start = data.get("evidence_start", 0)
            evidence_end = data.get("evidence_end", 0)
            confidence = float(data.get("confidence", 0.7))

            # Récupérer les matched surface forms du LLM
            matched_form_a = data.get("matched_surface_form_A", "")
            matched_form_b = data.get("matched_surface_form_B", "")

            # Valider offsets
            if not isinstance(evidence_start, int) or not isinstance(evidence_end, int):
                logger.debug(f"[OSMOSE:Pass3] Invalid offset types")
                return None, "invalid_offsets"

            if evidence_start < 0 or evidence_end <= evidence_start:
                logger.debug(f"[OSMOSE:Pass3] Invalid offsets: start={evidence_start}, end={evidence_end}")
                return None, "invalid_offsets"

            if evidence_end > len(combined_text):
                logger.debug(f"[OSMOSE:Pass3] Offset out of bounds: end={evidence_end}, text_len={len(combined_text)}")
                return None, "offset_out_of_bounds"

            # === SENTENCE BOUNDARY EXTENSION ===
            sentence_delimiters = '.!?\n'

            extended_start = evidence_start
            while extended_start > 0 and combined_text[extended_start - 1] not in sentence_delimiters:
                extended_start -= 1
            while extended_start < evidence_start and combined_text[extended_start] in ' \t\n':
                extended_start += 1

            extended_end = evidence_end
            while extended_end < len(combined_text) and combined_text[extended_end] not in sentence_delimiters:
                extended_end += 1
            if extended_end < len(combined_text):
                extended_end += 1

            if (extended_end - extended_start) <= 500:
                evidence_start = extended_start
                evidence_end = extended_end

            # Extraire la quote (verbatim garanti)
            quote = combined_text[evidence_start:evidence_end].strip()

            # Valider longueur
            if len(quote) < 10:
                logger.debug(f"[OSMOSE:Pass3] Quote too short: {len(quote)} chars")
                return None, "quote_too_short"

            if len(quote) > 500:
                last_delim = max(quote.rfind('.'), quote.rfind('!'), quote.rfind('?'))
                if last_delim > 50:
                    quote = quote[:last_delim + 1]
                else:
                    quote = quote[:500]

            # === VALIDATION DÉTERMINISTE: Quote contient surface forms A ET B ===
            quote_has_a, quote_has_b = self._validate_quote_contains_surface_forms(
                quote, candidate, matched_form_a, matched_form_b
            )

            if not quote_has_a or not quote_has_b:
                missing = []
                if not quote_has_a:
                    missing.append("A")
                if not quote_has_b:
                    missing.append("B")
                logger.debug(
                    f"[OSMOSE:Pass3] Quote missing surface forms for: {missing}. "
                    f"Rejecting (deterministic validation)."
                )
                return None, "quote_missing_surface_forms"

            # Identifier les context_ids où la quote apparaît
            evidence_context_ids = []
            quote_normalized = self._normalize_for_matching(quote)
            for ctx_id, ctx_text in context_texts.items():
                text_normalized = self._normalize_for_matching(ctx_text)
                if quote_normalized in text_normalized:
                    evidence_context_ids.append(ctx_id)

            if not evidence_context_ids and context_texts:
                evidence_context_ids = [list(context_texts.keys())[0]]

            # V2: Fallback sur les section_ids de la TextWindow
            if not evidence_context_ids and fallback_context_ids:
                evidence_context_ids = fallback_context_ids
                logger.debug(f"[OSMOSE:Pass3] Using fallback_context_ids: {evidence_context_ids}")

            logger.info(
                f"[OSMOSE:Pass3] ✓ Verified: {predicate} "
                f"(matched: '{matched_form_a}' / '{matched_form_b}', quote: {quote[:50]}...)"
            )

            # Créer relation vérifiée
            return VerifiedRelation(
                subject_concept_id=candidate.subject_concept_id,
                object_concept_id=candidate.object_concept_id,
                predicate=predicate,
                evidence_quote=quote,
                evidence_context_ids=evidence_context_ids,
                confidence=confidence,
                verification_result=VerificationResult.VERIFIED
            ), None

        except json.JSONDecodeError as e:
            logger.warning(f"[OSMOSE:Pass3] JSON parse error: {e}")
            return None, "json_parse_error"
        except Exception as e:
            logger.error(f"[OSMOSE:Pass3] Parse error: {e}")
            return None, "parse_error"

    def _validate_quote_contains_surface_forms(
        self,
        quote: str,
        candidate: RelationCandidate,
        matched_form_a: str,
        matched_form_b: str
    ) -> Tuple[bool, bool]:
        """
        Validation déterministe: la quote doit contenir une surface form de A ET de B.

        Args:
            quote: Citation extraite
            candidate: Candidat avec surface_forms
            matched_form_a: Surface form de A rapportée par le LLM
            matched_form_b: Surface form de B rapportée par le LLM

        Returns:
            Tuple (A trouvé, B trouvé)
        """
        quote_lower = quote.lower()

        # Vérifier surface form A
        found_a = False
        forms_a = candidate.subject_surface_forms or [candidate.subject_name]

        # D'abord vérifier la forme rapportée par le LLM
        if matched_form_a and matched_form_a.lower() in quote_lower:
            found_a = True
        else:
            # Sinon vérifier toutes les surface forms
            for form in forms_a:
                if form and form.lower() in quote_lower:
                    found_a = True
                    break
            # Fallback: keywords du label canonique
            if not found_a:
                keywords = self._extract_concept_keywords(candidate.subject_name)
                found_a = any(kw in quote_lower for kw in keywords if len(kw) > 3)

        # Vérifier surface form B
        found_b = False
        forms_b = candidate.object_surface_forms or [candidate.object_name]

        if matched_form_b and matched_form_b.lower() in quote_lower:
            found_b = True
        else:
            for form in forms_b:
                if form and form.lower() in quote_lower:
                    found_b = True
                    break
            if not found_b:
                keywords = self._extract_concept_keywords(candidate.object_name)
                found_b = any(kw in quote_lower for kw in keywords if len(kw) > 3)

        return found_a, found_b

    def _normalize_for_matching(self, text: str) -> str:
        """Normalise le texte pour matching de quote."""
        # Lowercase, collapse espaces, supprimer ponctuation non-significative
        normalized = text.lower()
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = re.sub(r'[^\w\s]', '', normalized)
        return normalized.strip()

    def _quote_mentions_concepts(
        self,
        quote: str,
        candidate: "RelationCandidate"
    ) -> bool:
        """
        Vérifie que la quote mentionne au moins un des concepts.

        Évite les hallucinations où le LLM cite un passage réel
        mais sans rapport avec les concepts demandés.

        Args:
            quote: Citation extraite par le LLM
            candidate: Candidat avec les noms des concepts

        Returns:
            True si au moins un concept est mentionné dans la quote
        """
        quote_lower = quote.lower()

        # Extraire les mots-clés significatifs de chaque concept
        subject_keywords = self._extract_concept_keywords(candidate.subject_name)
        object_keywords = self._extract_concept_keywords(candidate.object_name)

        # Vérifier si au moins un mot-clé de chaque concept est présent
        subject_found = any(kw in quote_lower for kw in subject_keywords)
        object_found = any(kw in quote_lower for kw in object_keywords)

        # On exige qu'AU MOINS UN des deux concepts soit mentionné
        # (idéalement les deux, mais on tolère un seul pour éviter faux négatifs)
        return subject_found or object_found

    def _extract_concept_keywords(self, concept_name: str) -> list:
        """
        Extrait les mots-clés significatifs d'un nom de concept.

        Ex: "Software Update Manager (SUM)" → ["software", "update", "manager", "sum"]
        Ex: "SAP S/4HANA" → ["sap", "s4hana", "s/4hana"]

        Args:
            concept_name: Nom du concept

        Returns:
            Liste de mots-clés en lowercase
        """
        if not concept_name:
            return []

        # Mots à ignorer (stop words techniques)
        stop_words = {
            "the", "a", "an", "and", "or", "for", "of", "in", "to", "with",
            "sap", "system", "management", "service", "services"
        }

        # Normaliser et extraire les mots
        name_lower = concept_name.lower()

        # Extraire acronymes entre parenthèses : "Software Update Manager (SUM)" → "sum"
        acronyms = re.findall(r'\(([^)]+)\)', name_lower)

        # Supprimer parenthèses et normaliser
        name_clean = re.sub(r'\([^)]*\)', '', name_lower)
        name_clean = re.sub(r'[^\w\s/]', ' ', name_clean)

        # Extraire tous les mots
        words = name_clean.split()

        # Filtrer les stop words et mots trop courts
        keywords = [w for w in words if w not in stop_words and len(w) > 2]

        # Ajouter les acronymes
        keywords.extend(acronyms)

        # Ajouter variantes pour les noms composés (S/4HANA → s4hana)
        for word in list(keywords):
            if '/' in word:
                keywords.append(word.replace('/', ''))

        return keywords


class Pass3SemanticWriter:
    """
    Écrit les relations vérifiées dans Neo4j.

    Garanties:
    - TOUTE relation a evidence_context_ids non vide
    - TOUTE relation a une evidence_quote
    - Relations marquées comme source="pass3_extractive"
    """

    def __init__(
        self,
        neo4j_client,
        tenant_id: str = "default"
    ):
        """
        Initialise le writer.

        Args:
            neo4j_client: Client Neo4j connecté
            tenant_id: ID du tenant
        """
        self.neo4j = neo4j_client
        self.tenant_id = tenant_id

        self._stats = {
            "written": 0,
            "merged": 0,
            "skipped": 0
        }

    def write_verified_relation(
        self,
        relation: VerifiedRelation,
        document_id: str
    ) -> bool:
        """
        Écrit une relation vérifiée dans Neo4j.

        Args:
            relation: Relation vérifiée à persister
            document_id: ID du document source

        Returns:
            True si écrit, False sinon
        """
        # Vérification obligatoire: evidence_context_ids non vide
        if not relation.evidence_context_ids:
            logger.warning(
                f"[OSMOSE:Pass3] Refusing to write relation without evidence_context_ids"
            )
            self._stats["skipped"] += 1
            return False

        # Vérification obligatoire: quote non vide
        if not relation.evidence_quote:
            logger.warning(
                f"[OSMOSE:Pass3] Refusing to write relation without evidence_quote"
            )
            self._stats["skipped"] += 1
            return False

        query = f"""
        MATCH (s:CanonicalConcept {{canonical_id: $subject_id, tenant_id: $tenant_id}})
        MATCH (o:CanonicalConcept {{canonical_id: $object_id, tenant_id: $tenant_id}})

        MERGE (s)-[r:{relation.predicate}]->(o)
        ON CREATE SET
            r.source = 'pass3_extractive',
            r.confidence = $confidence,
            r.evidence_quote = $evidence_quote,
            r.evidence_context_ids = $evidence_context_ids,
            r.document_id = $document_id,
            r.extraction_model = $extraction_model,
            r.created_at = datetime(),
            r.verified = true
        ON MATCH SET
            r.confidence = CASE WHEN $confidence > r.confidence THEN $confidence ELSE r.confidence END,
            r.evidence_context_ids = CASE
                WHEN r.evidence_context_ids IS NULL THEN $evidence_context_ids
                ELSE r.evidence_context_ids + [x IN $evidence_context_ids WHERE NOT x IN r.evidence_context_ids]
            END,
            r.evidence_quote = CASE WHEN r.evidence_quote IS NULL THEN $evidence_quote ELSE r.evidence_quote END,
            r.updated_at = datetime(),
            r.multi_evidence = true

        RETURN type(r) AS rel_type,
               CASE WHEN r.created_at = r.updated_at THEN true ELSE false END AS created
        """

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    subject_id=relation.subject_concept_id,
                    object_id=relation.object_concept_id,
                    tenant_id=self.tenant_id,
                    confidence=relation.confidence,
                    evidence_quote=relation.evidence_quote,
                    evidence_context_ids=relation.evidence_context_ids,
                    document_id=document_id,
                    extraction_model=relation.extraction_model
                )

                record = result.single()
                if record:
                    if record.get("created", False):
                        self._stats["written"] += 1
                    else:
                        self._stats["merged"] += 1
                    return True

        except Exception as e:
            logger.error(f"[OSMOSE:Pass3] Write failed: {e}")
            self._stats["skipped"] += 1

        return False

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques d'écriture."""
        return self._stats.copy()


# ========================================================================
# TEXT WINDOW BUILDER (Option C / DocItems)
# ========================================================================

@dataclass
class TextWindow:
    """Fenêtre de texte pour vérification extractive."""
    text: str                           # Texte concaténé
    item_ids: List[str]                 # DocItems inclus
    section_ids: List[str]              # Sections couvertes
    char_count: int                     # Taille en caractères
    escalation_level: int               # 1=±1, 2=±3, 3=section
    item_offsets: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # item_id -> (start, end)


class TextWindowBuilder:
    """
    Construit des fenêtres de texte à partir des DocItems ancrés.

    Utilise reading_order_index et section_id pour reconstruire
    la séquence de DocItems sans prev/next explicites.

    Stratégie d'escalade:
    - Niveau 1: DocItems ancrés ± 1 voisin
    - Niveau 2: DocItems ancrés ± 3 voisins
    - Niveau 3: Sections entières des anchors (capées)
    """

    # Paramètres par défaut
    MAX_ITEMS = 40
    MAX_CHARS = 6000  # ~1500 tokens
    NEIGHBOR_LEVEL_1 = 1  # ±1
    NEIGHBOR_LEVEL_2 = 3  # ±3

    def __init__(self, neo4j_client, tenant_id: str = "default"):
        """
        Initialise le builder.

        Args:
            neo4j_client: Client Neo4j
            tenant_id: ID du tenant
        """
        self.neo4j = neo4j_client
        self.tenant_id = tenant_id
        self._docitems_cache: Dict[str, List[Dict]] = {}  # doc_id -> items

    def build_window(
        self,
        candidate: RelationCandidate,
        document_id: str,
        escalation_level: int = 1
    ) -> Optional[TextWindow]:
        """
        Construit une fenêtre de texte pour un candidat.

        Args:
            candidate: Candidat avec anchor_items
            document_id: ID du document
            escalation_level: 1=±1, 2=±3, 3=section

        Returns:
            TextWindow ou None si échec
        """
        # Charger les DocItems du document (avec cache)
        docitems = self._get_docitems_for_document(document_id)
        if not docitems:
            logger.warning(f"[OSMOSE:Pass3:Window] No DocItems for {document_id}")
            return None

        # Indexer par section et position
        by_section = self._index_by_section(docitems)

        # V2 FIX: Rechercher d'abord les DocItems contenant les surface_forms
        # Car les ANCHORED_IN peuvent être incorrects
        seed_items = self._find_items_with_surface_forms(
            docitems, candidate, candidate.shared_sections
        )

        # Fallback sur anchor_items si aucun DocItem avec surface_forms
        if not seed_items:
            seed_items = set(candidate.subject_anchor_items + candidate.object_anchor_items)
            if seed_items:
                logger.debug(
                    f"[OSMOSE:Pass3:Window] No DocItems with surface_forms, "
                    f"using {len(seed_items)} anchor_items as fallback"
                )

        if not seed_items:
            logger.debug(f"[OSMOSE:Pass3:Window] No seed items for candidate")
            return None

        # Déterminer les items à inclure selon le niveau d'escalade
        if escalation_level == 1:
            selected_items = self._select_with_neighbors(
                seed_items, by_section, neighbors=self.NEIGHBOR_LEVEL_1
            )
        elif escalation_level == 2:
            selected_items = self._select_with_neighbors(
                seed_items, by_section, neighbors=self.NEIGHBOR_LEVEL_2
            )
        else:  # niveau 3 = sections entières
            selected_items = self._select_full_sections(
                seed_items, by_section, candidate.shared_sections
            )

        if not selected_items:
            return None

        # Trier par ordre de lecture global
        sorted_items = sorted(
            selected_items,
            key=lambda x: (x.get("page_no", 0), x.get("reading_order_index", 0))
        )

        # Capper et construire le texte
        return self._build_text_from_items(sorted_items, escalation_level)

    def _find_items_with_surface_forms(
        self,
        docitems: List[Dict],
        candidate: RelationCandidate,
        priority_sections: List[str]
    ) -> set:
        """
        Recherche les DocItems contenant les surface_forms du candidat.

        Priorité:
        1. DocItems dans les sections partagées
        2. DocItems dans les mêmes sections que les anchors

        Args:
            docitems: Liste de tous les DocItems
            candidate: Candidat avec surface_forms
            priority_sections: Sections prioritaires

        Returns:
            Set d'item_ids contenant au moins une surface_form
        """
        subject_forms = [f.lower() for f in (candidate.subject_surface_forms or [candidate.subject_name])]
        object_forms = [f.lower() for f in (candidate.object_surface_forms or [candidate.object_name])]

        items_with_subject = set()
        items_with_object = set()

        # Filtrer d'abord par sections prioritaires
        priority_set = set(priority_sections)
        filtered_items = [
            item for item in docitems
            if item.get("section_id") in priority_set
        ] if priority_set else docitems

        for item in filtered_items:
            text_lower = (item.get("text") or "").lower()
            item_id = item["item_id"]

            # Chercher surface_forms du subject
            for form in subject_forms:
                if form in text_lower:
                    items_with_subject.add(item_id)
                    break

            # Chercher surface_forms de l'object
            for form in object_forms:
                if form in text_lower:
                    items_with_object.add(item_id)
                    break

        # Idéalement on veut des items qui ont les DEUX
        items_with_both = items_with_subject & items_with_object
        if items_with_both:
            logger.debug(
                f"[OSMOSE:Pass3:Window] Found {len(items_with_both)} DocItems "
                f"with BOTH surface_forms"
            )
            return items_with_both

        # Sinon retourner l'union
        all_found = items_with_subject | items_with_object
        if all_found:
            logger.debug(
                f"[OSMOSE:Pass3:Window] Found {len(items_with_subject)} items with subject, "
                f"{len(items_with_object)} with object"
            )
        return all_found

    def _get_docitems_for_document(self, document_id: str) -> List[Dict]:
        """Récupère les DocItems d'un document (avec cache)."""
        if document_id in self._docitems_cache:
            return self._docitems_cache[document_id]

        query = """
        MATCH (d:DocItem {tenant_id: $tenant_id, doc_id: $document_id})
        WHERE d.text IS NOT NULL AND size(d.text) > 0
        RETURN d.item_id AS item_id,
               d.section_id AS section_id,
               d.text AS text,
               d.reading_order_index AS reading_order_index,
               d.page_no AS page_no,
               d.charspan_start_docwide AS charspan_start
        ORDER BY d.page_no, d.reading_order_index
        """

        items = []
        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    document_id=document_id,
                    tenant_id=self.tenant_id
                )
                for record in result:
                    items.append({
                        "item_id": record["item_id"],
                        "section_id": record["section_id"],
                        "text": record["text"],
                        "reading_order_index": record["reading_order_index"] or 0,
                        "page_no": record["page_no"] or 0,
                        "charspan_start": record["charspan_start"] or 0
                    })

            self._docitems_cache[document_id] = items
            logger.debug(f"[OSMOSE:Pass3:Window] Loaded {len(items)} DocItems for {document_id}")

        except Exception as e:
            logger.error(f"[OSMOSE:Pass3:Window] Failed to load DocItems: {e}")

        return items

    def _index_by_section(self, docitems: List[Dict]) -> Dict[str, List[Dict]]:
        """Indexe les DocItems par section_id, triés par reading_order_index."""
        by_section: Dict[str, List[Dict]] = {}
        for item in docitems:
            section = item.get("section_id") or "unknown"
            if section not in by_section:
                by_section[section] = []
            by_section[section].append(item)

        # Trier chaque section par reading_order_index
        for section in by_section:
            by_section[section].sort(key=lambda x: x.get("reading_order_index", 0))

        return by_section

    def _select_with_neighbors(
        self,
        seed_item_ids: set,
        by_section: Dict[str, List[Dict]],
        neighbors: int
    ) -> List[Dict]:
        """Sélectionne les seeds + N voisins de chaque côté."""
        selected = []
        selected_ids = set()

        for section_id, items in by_section.items():
            # Créer index position -> item
            item_positions = {item["item_id"]: i for i, item in enumerate(items)}

            for item_id in seed_item_ids:
                if item_id not in item_positions:
                    continue

                pos = item_positions[item_id]
                start = max(0, pos - neighbors)
                end = min(len(items), pos + neighbors + 1)

                for i in range(start, end):
                    item = items[i]
                    if item["item_id"] not in selected_ids:
                        selected.append(item)
                        selected_ids.add(item["item_id"])

        return selected

    def _select_full_sections(
        self,
        seed_item_ids: set,
        by_section: Dict[str, List[Dict]],
        shared_sections: List[str]
    ) -> List[Dict]:
        """Sélectionne tous les items des sections pertinentes."""
        selected = []
        selected_ids = set()

        # Sections prioritaires: celles des seeds, puis shared_sections
        priority_sections = set()
        for item_id in seed_item_ids:
            for section_id, items in by_section.items():
                if any(item["item_id"] == item_id for item in items):
                    priority_sections.add(section_id)

        priority_sections.update(shared_sections)

        for section_id in priority_sections:
            if section_id not in by_section:
                continue

            for item in by_section[section_id]:
                if item["item_id"] not in selected_ids:
                    selected.append(item)
                    selected_ids.add(item["item_id"])

                # Cap pour éviter des sections trop longues
                if len(selected) >= self.MAX_ITEMS:
                    break

            if len(selected) >= self.MAX_ITEMS:
                break

        return selected

    def _build_text_from_items(
        self,
        items: List[Dict],
        escalation_level: int
    ) -> Optional[TextWindow]:
        """Construit le TextWindow à partir des items sélectionnés."""
        if not items:
            return None

        # Capper le nombre d'items
        items = items[:self.MAX_ITEMS]

        # Construire le texte avec tracking des offsets
        text_parts = []
        item_offsets = {}
        current_offset = 0
        section_ids = set()

        for item in items:
            item_text = item.get("text", "").strip()
            if not item_text:
                continue

            start = current_offset
            text_parts.append(item_text)
            current_offset += len(item_text) + 1  # +1 pour le \n
            item_offsets[item["item_id"]] = (start, current_offset - 1)
            section_ids.add(item.get("section_id", "unknown"))

        combined_text = "\n".join(text_parts)

        # Capper la taille
        if len(combined_text) > self.MAX_CHARS:
            combined_text = combined_text[:self.MAX_CHARS]
            logger.debug(f"[OSMOSE:Pass3:Window] Text truncated to {self.MAX_CHARS} chars")

        return TextWindow(
            text=combined_text,
            item_ids=[item["item_id"] for item in items],
            section_ids=list(section_ids),
            char_count=len(combined_text),
            escalation_level=escalation_level,
            item_offsets=item_offsets
        )


# ========================================================================
# PROMPTS
# ========================================================================

EXTRACTIVE_SYSTEM_PROMPT = """You are OSMOSE Pass 3 Extractive Verifier.

Your task is to find EXPLICIT relationships between concepts in text using their SURFACE FORMS (actual text mentions).

## IMPORTANT: Surface Forms vs Canonical Labels

- canonical_label = normalized identifier (for reference only)
- surface_forms = actual strings that appear in the text (USE THESE TO FIND MENTIONS)

## Task

1. Find a SINGLE sentence in the text that:
   - Contains at least ONE surface form of concept A
   - Contains at least ONE surface form of concept B
   - Shows an EXPLICIT relationship between them (not just co-occurrence)

2. Return the character offsets (0-based) pointing to that sentence

3. Report which surface forms you matched

## What is NOT valid evidence

- Two concepts listed together without linking language (e.g., "A, B, C are features")
- Implicit or inferred relationships
- Concepts mentioned in different sentences

## ABSTAIN reasons

- no_single_sentence_mentions_both: Could not find a sentence with both A and B
- mentions_both_but_no_linking_claim: Found both but no explicit relation stated
- ambiguous_referent: Unclear which concept is referenced

## Output JSON format

If RELATION found:
{"decision": "RELATION", "relation_type": "REQUIRES|USES|PART_OF|SUBTYPE_OF|EXTENDS|IMPLEMENTS|COMPLIES_WITH|ENABLES|SUPPORTS|INTEGRATES_WITH|REPLACES|VERSION_OF|CAUSES|PREVENTS|APPLIES_TO", "evidence_start": 123, "evidence_end": 456, "matched_surface_form_A": "...", "matched_surface_form_B": "...", "confidence": 0.9}

If ABSTAIN:
{"decision": "ABSTAIN", "reason": "no_single_sentence_mentions_both|mentions_both_but_no_linking_claim|ambiguous_referent", "evidence_start": 0, "evidence_end": 0, "confidence": 0.0}"""


# ========================================================================
# MAIN ORCHESTRATION
# ========================================================================

async def run_pass3_consolidation(
    document_id: str,
    neo4j_client,
    llm_router,
    tenant_id: str = "default",
    max_candidates: int = 50
) -> Pass3Stats:
    """
    Exécute Pass 3 pour un document.

    Pipeline:
    1. Génère candidats via co-présence
    2. Vérifie chaque candidat avec LLM extractif
    3. Persiste les relations vérifiées

    Args:
        document_id: ID du document
        neo4j_client: Client Neo4j
        llm_router: Router LLM
        tenant_id: ID du tenant
        max_candidates: Nombre max de candidats

    Returns:
        Pass3Stats avec résultats
    """
    start_time = datetime.now()
    stats = Pass3Stats()

    logger.info(f"[OSMOSE:Pass3] Starting consolidation for {document_id}")

    # 1. Générer candidats
    generator = CandidateGenerator(neo4j_client, tenant_id)
    candidates = generator.generate_candidates(document_id, max_candidates)
    stats.candidates_generated = len(candidates)

    if not candidates:
        logger.info(f"[OSMOSE:Pass3] No candidates for {document_id}")
        stats.processing_time_ms = (datetime.now() - start_time).total_seconds() * 1000
        return stats

    # 2. V2: Créer le TextWindowBuilder pour fenêtres ciblées
    window_builder = TextWindowBuilder(neo4j_client, tenant_id)

    # 3. Vérifier les candidats EN PARALLÈLE avec escalade
    verifier = ExtractiveVerifier(llm_router, tenant_id)
    writer = Pass3SemanticWriter(neo4j_client, tenant_id)

    # Stats par raison d'abstention
    abstain_reasons: Dict[str, int] = {}

    max_concurrent = 8
    semaphore = asyncio.Semaphore(max_concurrent)

    async def verify_single_candidate(candidate: RelationCandidate):
        """Vérifie un candidat avec contrôle de concurrence et escalade."""
        async with semaphore:
            # V2: Utiliser escalade automatique avec TextWindowBuilder
            verified, level, abstain_reason = await verifier.verify_candidate_with_escalation(
                candidate, document_id, window_builder
            )

            return {
                "verified": verified,
                "abstained": verified is None,
                "escalation_level": level,
                "abstain_reason": abstain_reason
            }

    logger.info(
        f"[OSMOSE:Pass3] Verifying {len(candidates)} candidates (max_concurrent={max_concurrent})"
    )

    # Lancer toutes les vérifications en parallèle
    tasks = [verify_single_candidate(c) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Agréger les résultats et persister
    escalation_stats = {1: 0, 2: 0, 3: 0}  # Relations par niveau d'escalade

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[OSMOSE:Pass3] Candidate verification error: {result}")
            stats.abstained += 1
            abstain_reasons["exception"] = abstain_reasons.get("exception", 0) + 1
            continue

        stats.candidates_verified += 1

        if result["abstained"]:
            stats.abstained += 1
            reason = result.get("abstain_reason", "unknown")
            abstain_reasons[reason] = abstain_reasons.get(reason, 0) + 1
        elif result["verified"]:
            # Persister
            if writer.write_verified_relation(result["verified"], document_id):
                stats.relations_created += 1
                level = result.get("escalation_level", 1)
                escalation_stats[level] = escalation_stats.get(level, 0) + 1

    stats.processing_time_ms = (datetime.now() - start_time).total_seconds() * 1000

    # Log détaillé avec stats d'abstention
    logger.info(
        f"[OSMOSE:Pass3] Consolidation complete: "
        f"{stats.candidates_generated} candidates, "
        f"{stats.relations_created} relations created, "
        f"{stats.abstained} abstained, "
        f"in {stats.processing_time_ms:.0f}ms"
    )

    if stats.relations_created > 0:
        logger.info(f"[OSMOSE:Pass3] Escalation stats: {escalation_stats}")

    if abstain_reasons:
        logger.info(f"[OSMOSE:Pass3] Abstain reasons: {abstain_reasons}")

    return stats


async def _get_section_texts(
    neo4j_client,
    document_id: str,
    tenant_id: str
) -> Dict[str, str]:
    """
    Récupère les textes des sections d'un document.

    Utilise Qdrant pour récupérer le texte complet des chunks,
    groupés par context_id (pont Neo4j ↔ Qdrant établi en Phase 0).

    Returns:
        {context_id: text}
    """
    from knowbase.common.clients.qdrant_client import get_qdrant_client
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    texts = {}

    try:
        # 1. D'abord récupérer les context_ids des sections du document
        query = """
        MATCH (ctx:SectionContext {tenant_id: $tenant_id})
        WHERE ctx.doc_id = $document_id
        RETURN ctx.context_id AS context_id, ctx.section_path AS section_path
        """

        context_ids = []
        with neo4j_client.driver.session(database=neo4j_client.database) as session:
            result = session.run(
                query,
                document_id=document_id,
                tenant_id=tenant_id
            )
            context_ids = [r["context_id"] for r in result if r.get("context_id")]

        if not context_ids:
            logger.debug(f"[OSMOSE:Pass3] No SectionContext found for {document_id}")
            return texts

        # 2. Récupérer les chunks depuis Qdrant filtrés par context_id
        qdrant = get_qdrant_client()
        collection_name = "knowbase"

        for ctx_id in context_ids:
            try:
                # Scroll pour récupérer tous les chunks de cette section
                scroll_result = qdrant.scroll(
                    collection_name=collection_name,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="context_id",
                                match=MatchValue(value=ctx_id)
                            ),
                            FieldCondition(
                                key="tenant_id",
                                match=MatchValue(value=tenant_id)
                            )
                        ]
                    ),
                    limit=50,  # Max chunks par section
                    with_payload=True,
                    with_vectors=False
                )

                # Concaténer les textes des chunks
                chunk_texts = []
                if scroll_result and scroll_result[0]:
                    for point in scroll_result[0]:
                        if point.payload and point.payload.get("text"):
                            chunk_texts.append(point.payload["text"])

                if chunk_texts:
                    texts[ctx_id] = "\n\n".join(chunk_texts)

            except Exception as e:
                logger.debug(f"[OSMOSE:Pass3] Failed to get chunks for {ctx_id}: {e}")
                continue

        # 3. Fallback: si Qdrant n'a pas les context_id, utiliser document_id
        if not texts:
            logger.debug(f"[OSMOSE:Pass3] Fallback to document_id filter for {document_id}")
            try:
                scroll_result = qdrant.scroll(
                    collection_name=collection_name,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="document_id",
                                match=MatchValue(value=document_id)
                            ),
                            FieldCondition(
                                key="tenant_id",
                                match=MatchValue(value=tenant_id)
                            )
                        ]
                    ),
                    limit=100,
                    with_payload=True,
                    with_vectors=False
                )

                if scroll_result and scroll_result[0]:
                    # Grouper par context_id si disponible, sinon utiliser un ID générique
                    for point in scroll_result[0]:
                        if point.payload:
                            ctx_id = point.payload.get("context_id", f"doc:{document_id}")
                            text = point.payload.get("text", "")
                            if text:
                                if ctx_id in texts:
                                    texts[ctx_id] += "\n\n" + text
                                else:
                                    texts[ctx_id] = text

            except Exception as e:
                logger.error(f"[OSMOSE:Pass3] Fallback also failed: {e}")

    except Exception as e:
        logger.error(f"[OSMOSE:Pass3] Failed to get section texts: {e}")

    logger.debug(f"[OSMOSE:Pass3] Retrieved texts for {len(texts)} sections")
    return texts
