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

import logging
import hashlib
import re
from typing import List, Dict, Optional, Any, Tuple, Set
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
    """
    subject_concept_id: str
    subject_name: str
    object_concept_id: str
    object_name: str

    # Co-présence
    shared_sections: List[str]       # context_ids des sections communes
    shared_topics: List[str]         # topic_ids des topics communs
    co_occurrence_count: int         # Nombre de co-occurrences

    # Scores de candidature
    candidate_score: float = 0.0
    recurrence_score: float = 0.0    # Basé sur ≥2 sections


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

        Utilise les MENTIONED_IN et COVERS pour trouver les co-présences.

        Args:
            document_id: ID du document source
            max_candidates: Nombre max de candidats à générer

        Returns:
            Liste de RelationCandidate triés par score
        """
        logger.info(f"[OSMOSE:Pass3] Generating candidates for {document_id}")

        # 1. Trouver toutes les paires de concepts co-présents
        co_presence_query = """
        // Trouver concepts du document via MENTIONED_IN
        MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})
              -[m1:MENTIONED_IN]->(ctx:SectionContext {document_id: $document_id, tenant_id: $tenant_id})
              <-[m2:MENTIONED_IN]-(c2:CanonicalConcept {tenant_id: $tenant_id})
        WHERE c1.canonical_id < c2.canonical_id  // Éviter doublons
          AND c1.concept_type <> 'TOPIC'         // Exclure Topics
          AND c2.concept_type <> 'TOPIC'

        // Compter co-occurrences
        WITH c1, c2, collect(DISTINCT ctx.context_id) AS shared_sections
        WHERE size(shared_sections) >= $min_co_occurrences

        // Récupérer topics communs
        OPTIONAL MATCH (t:CanonicalConcept {concept_type: 'TOPIC', tenant_id: $tenant_id})
                       -[:COVERS]->(c1)
        OPTIONAL MATCH (t)-[:COVERS]->(c2)
        WITH c1, c2, shared_sections,
             collect(DISTINCT t.canonical_id) AS shared_topics

        // Vérifier qu'il n'y a pas déjà de relation
        OPTIONAL MATCH (c1)-[existing]->(c2)
        WHERE type(existing) IN ['REQUIRES', 'ENABLES', 'USES', 'PART_OF', 'APPLIES_TO']

        WITH c1, c2, shared_sections, shared_topics,
             CASE WHEN existing IS NULL THEN true ELSE false END AS no_existing_relation
        WHERE no_existing_relation

        RETURN c1.canonical_id AS subject_id,
               c1.canonical_name AS subject_name,
               c2.canonical_id AS object_id,
               c2.canonical_name AS object_name,
               shared_sections,
               shared_topics,
               size(shared_sections) AS co_occurrence_count
        ORDER BY co_occurrence_count DESC
        LIMIT $max_candidates
        """

        candidates = []

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    co_presence_query,
                    document_id=document_id,
                    tenant_id=self.tenant_id,
                    min_co_occurrences=self.MIN_CO_OCCURRENCES,
                    max_candidates=max_candidates
                )

                for record in result:
                    # Calculer scores
                    co_occurrence_count = record["co_occurrence_count"]
                    shared_topics = record["shared_topics"] or []

                    # Score de récurrence (bonus si >2 sections)
                    recurrence_score = min(1.0, co_occurrence_count / 5.0)

                    # Score de candidature
                    candidate_score = (
                        recurrence_score * 0.6 +
                        (len(shared_topics) > 0) * 0.4
                    )

                    if candidate_score < self.MIN_CANDIDATE_SCORE:
                        continue

                    candidate = RelationCandidate(
                        subject_concept_id=record["subject_id"],
                        subject_name=record["subject_name"],
                        object_concept_id=record["object_id"],
                        object_name=record["object_name"],
                        shared_sections=record["shared_sections"],
                        shared_topics=shared_topics,
                        co_occurrence_count=co_occurrence_count,
                        candidate_score=candidate_score,
                        recurrence_score=recurrence_score
                    )

                    candidates.append(candidate)
                    self._stats["candidates_generated"] += 1

                self._stats["pairs_evaluated"] = len(candidates)

        except Exception as e:
            logger.error(f"[OSMOSE:Pass3] Candidate generation failed: {e}")

        logger.info(
            f"[OSMOSE:Pass3] Generated {len(candidates)} candidates "
            f"(min_co_occurrences={self.MIN_CO_OCCURRENCES})"
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

    # Prédicats du set fermé
    VALID_PREDICATES = {
        "REQUIRES", "ENABLES", "USES", "INTEGRATES_WITH",
        "APPLIES_TO", "PART_OF", "SUBTYPE_OF", "CAUSES",
        "PREVENTS", "REPLACES", "VERSION_OF", "ASSOCIATED_WITH"
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
        context_texts: Dict[str, str]
    ) -> Optional[VerifiedRelation]:
        """
        Vérifie un candidat de relation.

        Args:
            candidate: Candidat à vérifier
            context_texts: {context_id: text} des sections partagées

        Returns:
            VerifiedRelation si vérifié, None si ABSTAIN
        """
        if not context_texts:
            logger.debug(f"[OSMOSE:Pass3] No context for candidate, abstaining")
            self._stats["abstained"] += 1
            return None

        # Construire le texte combiné des sections
        combined_text = "\n\n---\n\n".join([
            f"[Section: {ctx_id}]\n{text}"
            for ctx_id, text in context_texts.items()
        ])

        # Prompt extractif strict
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
                response_format={"type": "json_object"}
            )

            # Parser la réponse
            result = self._parse_verification_response(response, candidate, context_texts)

            if result:
                self._stats["verified"] += 1
            else:
                self._stats["abstained"] += 1

            return result

        except Exception as e:
            logger.error(f"[OSMOSE:Pass3] Verification failed: {e}")
            self._stats["abstained"] += 1
            return None

    def _build_extractive_prompt(
        self,
        candidate: RelationCandidate,
        combined_text: str
    ) -> str:
        """Construit le prompt de vérification extractive."""
        return f"""## Concepts à analyser
- **Concept A**: {candidate.subject_name}
- **Concept B**: {candidate.object_name}

## Texte source (sections où les concepts co-apparaissent)
{combined_text}

## Instructions
1. Cherche dans le texte un passage qui établit une relation EXPLICITE entre "{candidate.subject_name}" et "{candidate.object_name}"
2. Le passage doit EXPLICITEMENT mentionner les deux concepts et leur relation
3. Si tu trouves un tel passage:
   - Cite-le EXACTEMENT (copier-coller)
   - Identifie le type de relation
4. Si tu ne trouves PAS de passage explicite → ABSTAIN

## Types de relations valides
REQUIRES, ENABLES, USES, INTEGRATES_WITH, APPLIES_TO, PART_OF, SUBTYPE_OF, CAUSES, PREVENTS, REPLACES, VERSION_OF

## Format de réponse JSON
```json
{{
  "result": "VERIFIED" | "ABSTAIN",
  "predicate": "REQUIRES" | ... | null,
  "quote": "passage exact du texte" | null,
  "quote_section": "context_id de la section" | null,
  "confidence": 0.0-1.0,
  "reasoning": "explication courte"
}}
```"""

    def _parse_verification_response(
        self,
        response: str,
        candidate: RelationCandidate,
        context_texts: Dict[str, str]
    ) -> Optional[VerifiedRelation]:
        """Parse et valide la réponse du LLM."""
        import json

        try:
            # Extraire JSON
            text = response.strip()
            json_match = re.search(r'\{.*\}', text, re.DOTALL)

            if not json_match:
                logger.warning("[OSMOSE:Pass3] No JSON in LLM response")
                return None

            data = json.loads(json_match.group(0))

            # Vérifier résultat
            result = data.get("result", "").upper()

            if result != "VERIFIED":
                logger.debug(f"[OSMOSE:Pass3] LLM abstained: {data.get('reasoning', 'no reason')}")
                return None

            # Extraire données
            predicate = data.get("predicate", "").upper()
            quote = data.get("quote", "")
            quote_section = data.get("quote_section", "")
            confidence = float(data.get("confidence", 0.5))

            # Valider prédicat
            if predicate not in self.VALID_PREDICATES:
                logger.debug(f"[OSMOSE:Pass3] Invalid predicate: {predicate}")
                return None

            # Valider quote (doit exister dans le texte source)
            if not quote or len(quote) < 10:
                logger.debug("[OSMOSE:Pass3] Quote too short or missing")
                return None

            # Vérifier que la quote existe dans au moins une section
            quote_found = False
            evidence_context_ids = []

            quote_normalized = self._normalize_for_matching(quote)

            for ctx_id, text in context_texts.items():
                text_normalized = self._normalize_for_matching(text)
                if quote_normalized in text_normalized:
                    quote_found = True
                    evidence_context_ids.append(ctx_id)

            if not quote_found:
                logger.debug("[OSMOSE:Pass3] Quote not found in source text, abstaining")
                return None

            # Créer relation vérifiée
            return VerifiedRelation(
                subject_concept_id=candidate.subject_concept_id,
                object_concept_id=candidate.object_concept_id,
                predicate=predicate,
                evidence_quote=quote,
                evidence_context_ids=evidence_context_ids,
                confidence=confidence,
                verification_result=VerificationResult.VERIFIED
            )

        except json.JSONDecodeError as e:
            logger.warning(f"[OSMOSE:Pass3] JSON parse error: {e}")
            return None
        except Exception as e:
            logger.error(f"[OSMOSE:Pass3] Parse error: {e}")
            return None

    def _normalize_for_matching(self, text: str) -> str:
        """Normalise le texte pour matching de quote."""
        # Lowercase, collapse espaces, supprimer ponctuation non-significative
        normalized = text.lower()
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = re.sub(r'[^\w\s]', '', normalized)
        return normalized.strip()


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
# PROMPTS
# ========================================================================

EXTRACTIVE_SYSTEM_PROMPT = """Tu es OSMOSE Pass 3 Extractive Verifier.

Ta mission est de VÉRIFIER si une relation existe EXPLICITEMENT dans le texte source.

## Règles STRICTES

1. **Citation obligatoire**: Tu dois citer le passage EXACT du texte qui prouve la relation
2. **ABSTAIN si doute**: En cas de doute, retourne ABSTAIN. Mieux vaut s'abstenir qu'halluciner.
3. **Explicit only**: La relation doit être EXPLICITE dans le texte, pas déduite ou implicite
4. **Vérifiable**: La citation doit être vérifiable (copier-coller du texte source)

## Ce qui n'est PAS une preuve valide

- Deux concepts mentionnés dans la même phrase sans relation explicite
- Une relation implicite ou supposée
- Une interprétation ou déduction
- Un résumé ou paraphrase

## Exemple de preuve VALIDE

Texte: "DORA requires financial institutions to implement ICT risk management frameworks."
Concepts: DORA, ICT risk management
→ VERIFIED, predicate=REQUIRES, quote="DORA requires financial institutions to implement ICT risk management frameworks"

## Exemple d'ABSTAIN

Texte: "The company implemented DORA compliance. They also have ICT risk management."
Concepts: DORA, ICT risk management
→ ABSTAIN (mentionnés ensemble mais pas de relation explicite)"""


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

    # 2. Récupérer les textes des sections
    context_texts = await _get_section_texts(neo4j_client, document_id, tenant_id)

    if not context_texts:
        logger.warning(f"[OSMOSE:Pass3] No section texts for {document_id}")
        stats.processing_time_ms = (datetime.now() - start_time).total_seconds() * 1000
        return stats

    # 3. Vérifier chaque candidat
    verifier = ExtractiveVerifier(llm_router, tenant_id)
    writer = Pass3SemanticWriter(neo4j_client, tenant_id)

    for candidate in candidates:
        # Filtrer les textes pour ce candidat
        candidate_contexts = {
            ctx_id: text
            for ctx_id, text in context_texts.items()
            if ctx_id in candidate.shared_sections
        }

        if not candidate_contexts:
            stats.abstained += 1
            continue

        # Vérifier
        verified = await verifier.verify_candidate(candidate, candidate_contexts)
        stats.candidates_verified += 1

        if verified:
            # Persister
            if writer.write_verified_relation(verified, document_id):
                stats.relations_created += 1
        else:
            stats.abstained += 1

    stats.processing_time_ms = (datetime.now() - start_time).total_seconds() * 1000

    logger.info(
        f"[OSMOSE:Pass3] Consolidation complete: "
        f"{stats.candidates_generated} candidates, "
        f"{stats.relations_created} relations created, "
        f"{stats.abstained} abstained, "
        f"in {stats.processing_time_ms:.0f}ms"
    )

    return stats


async def _get_section_texts(
    neo4j_client,
    document_id: str,
    tenant_id: str
) -> Dict[str, str]:
    """
    Récupère les textes des sections d'un document.

    Returns:
        {context_id: text}
    """
    query = """
    MATCH (ctx:SectionContext {document_id: $document_id, tenant_id: $tenant_id})
    OPTIONAL MATCH (dc:DocumentChunk {document_id: $document_id, tenant_id: $tenant_id})
    WHERE ctx.context_id CONTAINS dc.section_id OR ctx.section_path = dc.section_path

    RETURN ctx.context_id AS context_id,
           coalesce(ctx.text_preview, collect(dc.text_preview)[0]) AS text
    """

    texts = {}

    try:
        with neo4j_client.driver.session(database=neo4j_client.database) as session:
            result = session.run(
                query,
                document_id=document_id,
                tenant_id=tenant_id
            )

            for record in result:
                ctx_id = record["context_id"]
                text = record["text"]
                if ctx_id and text:
                    texts[ctx_id] = text

    except Exception as e:
        logger.error(f"[OSMOSE:Pass3] Failed to get section texts: {e}")

    return texts
