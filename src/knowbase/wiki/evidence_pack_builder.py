"""
EvidencePackBuilder — Construit un EvidencePack en 8 étapes.

Pipeline déterministe (pas de LLM) :
  0. Pré-chargement scope (DocumentContext)
  1. Claims structurants → EvidenceUnits
  2. Chunks définitoires → EvidenceUnits
  3. Plafonnement par document (double cap 40%)
  4. Évolution temporelle (CHAINS_TO)
  5. Contradictions 2 niveaux (INCOMPATIBLE / NEED_LLM)
  6. Concepts liés (co-occurrence)
  7. Quality signals
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from knowbase.wiki.models import (
    CandidateTension,
    ConfirmedConflict,
    EvidencePack,
    EvidenceUnit,
    QualitySignals,
    RelatedConcept,
    ResolvedConcept,
    ScopeSignature,
    SourceEntry,
    TemporalEvolution,
    TemporalStep,
)

logger = logging.getLogger(__name__)

# Mapping claim_type → rhetorical_role
CLAIM_TYPE_TO_ROLE = {
    "DEFINITIONAL": "definition",
    "PRESCRIPTIVE": "rule",
    "PERMISSIVE": "rule",
    "FACTUAL": "mention",
    "COMPARATIVE": "context",
}

# Priorité des rôles pour le tri (plus haut = plus structurant)
ROLE_PRIORITY = {
    "definition": 4,
    "rule": 3,
    "exception": 2,
    "mention": 1,
    "context": 0,
}

# Patrons linguistiques pour l'heuristique definitionality
DEFINITION_PATTERNS = [
    r"\bis defined as\b",
    r"\brefers to\b",
    r"\bmeans\b",
    r"\bis understood as\b",
    r"\bshall mean\b",
]

QDRANT_COLLECTION = "knowbase_chunks_v2"


class EvidencePackBuilder:
    """Construit un EvidencePack à partir du KG (Neo4j) et du store vectoriel (Qdrant)."""

    DOC_CAP_PCT = 0.40  # max 40% d'un doc

    def __init__(self, neo4j_driver, qdrant_client, embedding_manager):
        self._driver = neo4j_driver
        self._qdrant = qdrant_client
        self._embeddings = embedding_manager

    def build(self, concept: ResolvedConcept, tenant_id: str = "default") -> EvidencePack:
        """Pipeline 8 étapes → EvidencePack."""
        logger.info(
            f"[OSMOSE:EvidencePackBuilder] Construction du pack pour '{concept.canonical_name}'"
        )

        # Étape 0 : Pré-chargement scope (DocumentContext)
        scope_cache = self._load_scope_cache(concept.doc_ids, tenant_id)
        # Pré-charger les titres de documents
        doc_titles = self._load_doc_titles(concept.doc_ids, tenant_id)

        # Étape 1 : Claims structurants → EvidenceUnits
        claim_units, claims_raw = self._step1_claims(concept, tenant_id, scope_cache, doc_titles)
        logger.info(f"[OSMOSE:EvidencePackBuilder] Étape 1 : {len(claim_units)} claim units")

        # Étape 2 : Chunks définitoires → EvidenceUnits
        chunk_units = self._step2_chunks(concept, tenant_id, scope_cache, doc_titles, claim_units)
        logger.info(f"[OSMOSE:EvidencePackBuilder] Étape 2 : {len(chunk_units)} chunk units")

        all_units = claim_units + chunk_units

        # Étape 3 : Plafonnement par document
        all_units = self._step3_doc_cap(all_units)
        logger.info(f"[OSMOSE:EvidencePackBuilder] Étape 3 : {len(all_units)} units après cap")

        # Étape 4 : Évolution temporelle
        temporal = self._step4_temporal(concept, tenant_id, all_units)

        # Étape 5 : Contradictions
        conflicts, tensions = self._step5_contradictions(claims_raw, concept, tenant_id)

        # Étape 6 : Concepts liés
        related = self._step6_related(concept, tenant_id, all_units)

        # Étape 7 : Quality signals
        quality = self._step7_quality(
            all_units, temporal, conflicts, tensions, concept
        )

        # Construire source_index
        source_index = self._build_source_index(all_units, scope_cache, doc_titles)

        return EvidencePack(
            concept=concept,
            units=all_units,
            temporal_evolution=temporal,
            confirmed_conflicts=conflicts,
            candidate_tensions=tensions,
            related_concepts=related,
            source_index=source_index,
            quality_signals=quality,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── Étape 0 : Pré-chargement scope ──────────────────────────────────

    def _load_scope_cache(
        self, doc_ids: List[str], tenant_id: str
    ) -> Dict[str, ScopeSignature]:
        """Charge les ScopeSignatures depuis les nœuds DocumentContext."""
        if not doc_ids:
            return {}

        query = """
        MATCH (dc:DocumentContext)
        WHERE dc.doc_id IN $doc_ids AND dc.tenant_id = $tenant_id
        RETURN dc.doc_id AS doc_id, dc.document_type AS document_type,
               dc.temporal_scope AS temporal_scope,
               dc.primary_subject AS primary_subject,
               dc.qualifiers_json AS qualifiers_json
        """
        cache: Dict[str, ScopeSignature] = {}
        with self._driver.session() as session:
            result = session.run(query, doc_ids=doc_ids, tenant_id=tenant_id)
            for r in result:
                doc_id = r["doc_id"]
                doc_type = r.get("document_type") or None
                temporal = r.get("temporal_scope") or None

                # Déterminer temporal_scope_kind
                temporal_kind = "timeless"
                axis_values: Dict[str, str] = {}
                if temporal:
                    temporal_kind = "versioned"
                    axis_values["temporal_scope"] = temporal

                cache[doc_id] = ScopeSignature(
                    doc_type=doc_type,
                    axis_values=axis_values,
                    generality_level=self._infer_generality(doc_type),
                    temporal_scope_kind=temporal_kind,
                )

        logger.info(f"[OSMOSE:EvidencePackBuilder] Scope cache : {len(cache)}/{len(doc_ids)} docs")
        return cache

    def _load_doc_titles(self, doc_ids: List[str], tenant_id: str) -> Dict[str, str]:
        """Charge les titres des documents depuis DocumentContext ou Document."""
        if not doc_ids:
            return {}

        query = """
        MATCH (dc:DocumentContext)
        WHERE dc.doc_id IN $doc_ids AND dc.tenant_id = $tenant_id
        RETURN dc.doc_id AS doc_id, dc.primary_subject AS title
        """
        titles: Dict[str, str] = {}
        with self._driver.session() as session:
            result = session.run(query, doc_ids=doc_ids, tenant_id=tenant_id)
            for r in result:
                if r["title"]:
                    titles[r["doc_id"]] = r["title"]
        return titles

    @staticmethod
    def _infer_generality(doc_type: Optional[str]) -> str:
        """Infère le niveau de généralité depuis le type de document."""
        if not doc_type:
            return "universal"
        lower = doc_type.lower()
        if lower in ("regulation", "standard", "legal_term"):
            return "universal"
        if lower in ("guideline", "annual_report"):
            return "regional"
        return "local"

    # ── Étape 1 : Claims structurants ────────────────────────────────────

    def _step1_claims(
        self,
        concept: ResolvedConcept,
        tenant_id: str,
        scope_cache: Dict[str, ScopeSignature],
        doc_titles: Dict[str, str],
    ) -> Tuple[List[EvidenceUnit], List[dict]]:
        """Convertit les claims liés au concept en EvidenceUnits."""
        query = """
        MATCH (c:Claim)-[:ABOUT]->(e:Entity)
        WHERE e.entity_id IN $entity_ids AND c.tenant_id = $tenant_id
        OPTIONAL MATCH (c)-[q:QUALIFIES]->(:Claim)
        WITH c, q IS NOT NULL AS is_qualifier
        OPTIONAL MATCH (c)-[:BELONGS_TO_FACET]->(f:Facet)
        RETURN c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id,
               c.claim_type AS claim_type, c.structured_form AS structured_form,
               c.confidence AS confidence,
               c.chunk_ids AS chunk_ids,
               is_qualifier,
               collect(DISTINCT f.domain) AS facet_domains
        """
        units: List[EvidenceUnit] = []
        claims_raw: List[dict] = []

        with self._driver.session() as session:
            result = session.run(
                query, entity_ids=concept.entity_ids, tenant_id=tenant_id
            )
            for r in result:
                claim_id = r["claim_id"]
                claim_type = r["claim_type"]
                is_qualifier = r["is_qualifier"]

                # Déterminer le rôle rhétorique
                if is_qualifier:
                    role = "exception"
                elif claim_type and claim_type in CLAIM_TYPE_TO_ROLE:
                    role = CLAIM_TYPE_TO_ROLE[claim_type]
                else:
                    role = "mention"

                scope = scope_cache.get(r["doc_id"], ScopeSignature())
                facets = [d for d in (r["facet_domains"] or []) if d]

                chunk_ids = r.get("chunk_ids") or []

                unit = EvidenceUnit(
                    unit_id=f"eu_{uuid.uuid4().hex[:8]}",
                    source_type="claim",
                    source_id=claim_id,
                    text=r["text"] or "",
                    doc_id=r["doc_id"] or "",
                    doc_title=doc_titles.get(r["doc_id"], ""),
                    rhetorical_role=role,
                    claim_type=claim_type,
                    scope_signature=scope,
                    weight=1.0,
                    facet_domains=facets,
                    chunk_id=chunk_ids[0] if chunk_ids else None,
                )
                units.append(unit)

                # Garder les claims bruts pour l'étape 5 (contradictions)
                claims_raw.append({
                    "claim_id": claim_id,
                    "text": r["text"],
                    "claim_type": claim_type,
                    "doc_id": r["doc_id"],
                    "structured_form": r["structured_form"],
                })

        return units, claims_raw

    # ── Étape 2 : Chunks définitoires ────────────────────────────────────

    def _step2_chunks(
        self,
        concept: ResolvedConcept,
        tenant_id: str,
        scope_cache: Dict[str, ScopeSignature],
        doc_titles: Dict[str, str],
        claim_units: List[EvidenceUnit],
    ) -> List[EvidenceUnit]:
        """Récupère les chunks Qdrant définitoires et les convertit en EvidenceUnits."""
        if not concept.doc_ids:
            return []

        # Embedding de la requête
        search_text = f"{concept.canonical_name} definition role scope"
        try:
            query_vector = self._embeddings.encode([search_text])[0].tolist()
        except Exception as e:
            logger.error(f"[OSMOSE:EvidencePackBuilder] Erreur embedding : {e}")
            return []

        # Filtrer par doc_ids du concept + tenant_id
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

        search_filter = Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                FieldCondition(key="doc_id", match=MatchAny(any=concept.doc_ids)),
            ]
        )

        try:
            hits = self._qdrant.search(
                collection_name=QDRANT_COLLECTION,
                query_vector=query_vector,
                query_filter=search_filter,
                limit=15,
                score_threshold=0.3,
            )
        except Exception as e:
            logger.error(f"[OSMOSE:EvidencePackBuilder] Erreur Qdrant : {e}")
            return []

        # Vérifier s'il y a des claims DEFINITIONAL
        has_definitional = any(
            u.rhetorical_role == "definition" for u in claim_units
        )

        units: List[EvidenceUnit] = []
        for hit in hits:
            payload = hit.payload or {}
            text = payload.get("text", "")
            doc_id = payload.get("doc_id", "")
            chunk_id = str(hit.id)

            # Scoring definitionality (Amendement A3)
            def_score = self._compute_definitionality(
                text, concept.canonical_name, payload, has_definitional, doc_id
            )

            # Déterminer le rôle
            if def_score >= 0.40:
                role = "definition"
            else:
                role = "context"

            scope = scope_cache.get(doc_id, ScopeSignature())
            # Enrichir scope avec les axis du payload Qdrant
            axis_release = payload.get("axis_release_id")
            if axis_release and "temporal_scope" not in scope.axis_values:
                scope = scope.model_copy(
                    update={
                        "axis_values": {**scope.axis_values, "release_id": str(axis_release)},
                        "temporal_scope_kind": "versioned",
                    }
                )

            flags: List[str] = []
            if def_score < 0.40:
                flags.append(f"low_definitionality:{def_score:.2f}")
            if not scope_cache.get(doc_id):
                flags.append("scope_inferred")

            unit = EvidenceUnit(
                unit_id=f"eu_{uuid.uuid4().hex[:8]}",
                source_type="chunk",
                source_id=chunk_id,
                text=text,
                doc_id=doc_id,
                doc_title=doc_titles.get(doc_id, payload.get("doc_title", "")),
                rhetorical_role=role,
                claim_type=None,
                scope_signature=scope,
                weight=0.8,
                facet_domains=[],
                diagnostic_flags=flags,
            )
            units.append(unit)

        return units

    def _compute_definitionality(
        self,
        text: str,
        concept_name: str,
        payload: dict,
        has_definitional_claims: bool,
        doc_id: str,
    ) -> float:
        """
        Heuristique definitionality_score (Amendement A3).

        5 signaux, score 0-1 :
          +0.30 : concept dans les 2 premières phrases
          +0.25 : patrons linguistiques (is defined as, refers to, means)
          +0.10 : chunk de type NARRATIVE_TEXT
          +0.15 : section introductive (page ≤ 3 ou section contient intro/overview)
          +0.20 : proximité d'un claim DEFINITIONAL dans le même doc
        """
        score = 0.0
        text_lower = text.lower()
        concept_lower = concept_name.lower()

        # Signal 1 : concept dans les 2 premières phrases
        sentences = re.split(r"[.!?]\s+", text, maxsplit=2)
        first_two = " ".join(sentences[:2]).lower()
        if concept_lower in first_two:
            score += 0.30

        # Signal 2 : patrons linguistiques
        for pattern in DEFINITION_PATTERNS:
            if re.search(pattern, text_lower):
                score += 0.25
                break

        # Signal 3 : type NARRATIVE_TEXT
        kind = payload.get("kind", "")
        if kind == "NARRATIVE_TEXT" or not kind:
            score += 0.10

        # Signal 4 : section introductive
        page_no = payload.get("page_no")
        section_id = payload.get("section_id", "") or ""
        if (page_no is not None and page_no <= 3) or any(
            kw in section_id.lower() for kw in ("intro", "overview", "summary")
        ):
            score += 0.15

        # Signal 5 : proximité claim DEFINITIONAL dans le même doc
        if has_definitional_claims:
            score += 0.20

        return min(score, 1.0)

    # ── Étape 3 : Plafonnement par document ──────────────────────────────

    def _step3_doc_cap(self, units: List[EvidenceUnit]) -> List[EvidenceUnit]:
        """
        Double cap par document (Amendement A2) :
          1. Cap sur unités brutes (max 40%)
          2. Cap sur poids pondéré
          - Les unités "definition" du doc dominant ne sont jamais exclues
        """
        if not units:
            return units

        total = len(units)
        max_units_per_doc = max(int(total * self.DOC_CAP_PCT), 1)

        # Grouper par doc_id
        by_doc: Dict[str, List[EvidenceUnit]] = defaultdict(list)
        for u in units:
            by_doc[u.doc_id].append(u)

        retained: List[EvidenceUnit] = []
        for doc_id, doc_units in by_doc.items():
            if len(doc_units) <= max_units_per_doc:
                retained.extend(doc_units)
                continue

            # Trier par priorité de rôle (garder les plus structurants)
            doc_units.sort(
                key=lambda u: ROLE_PRIORITY.get(u.rhetorical_role, 0), reverse=True
            )

            kept = []
            for u in doc_units:
                if len(kept) < max_units_per_doc:
                    kept.append(u)
                elif u.rhetorical_role == "definition":
                    # Les définitions ne sont jamais exclues
                    kept.append(u)
                else:
                    u_flagged = u.model_copy(
                        update={"diagnostic_flags": u.diagnostic_flags + ["downweighted_by_doc_cap"]}
                    )
                    logger.debug(
                        f"[OSMOSE:EvidencePackBuilder] Exclu par cap doc : {u_flagged.unit_id}"
                    )

            # Marquer les unités du doc dominant
            if len(doc_units) > max_units_per_doc:
                for u in kept:
                    if "dominant_doc" not in u.diagnostic_flags:
                        kept[kept.index(u)] = u.model_copy(
                            update={"diagnostic_flags": u.diagnostic_flags + ["dominant_doc"]}
                        )

            retained.extend(kept)

        # Passe 2 : Cap sur poids pondéré
        total_weight = sum(u.weight for u in retained)
        if total_weight > 0:
            by_doc_weights: Dict[str, float] = defaultdict(float)
            for u in retained:
                by_doc_weights[u.doc_id] += u.weight

            for doc_id, doc_weight in by_doc_weights.items():
                pct = doc_weight / total_weight
                if pct > self.DOC_CAP_PCT:
                    reduction = self.DOC_CAP_PCT / pct
                    for i, u in enumerate(retained):
                        if u.doc_id == doc_id and u.rhetorical_role != "definition":
                            retained[i] = u.model_copy(
                                update={"weight": round(u.weight * reduction, 3)}
                            )

        return retained

    # ── Étape 4 : Évolution temporelle ───────────────────────────────────

    def _step4_temporal(
        self,
        concept: ResolvedConcept,
        tenant_id: str,
        units: List[EvidenceUnit],
    ) -> Optional[TemporalEvolution]:
        """Détecte l'évolution temporelle via CHAINS_TO entre claims du concept."""
        # Chercher les chaînes temporelles
        query = """
        MATCH (c1:Claim)-[r:CHAINS_TO]->(c2:Claim)
        WHERE (c1.claim_id IN $claim_ids OR c2.claim_id IN $claim_ids)
              AND c1.tenant_id = $tenant_id
        RETURN c1.claim_id AS from_id, c2.claim_id AS to_id,
               r.change_type AS change_type
        """
        claim_ids = [u.source_id for u in units if u.source_type == "claim"]
        if not claim_ids:
            return None

        chains: List[dict] = []
        with self._driver.session() as session:
            result = session.run(query, claim_ids=claim_ids, tenant_id=tenant_id)
            chains = [dict(r) for r in result]

        if not chains:
            return None

        # Index unit_id par source_id (claim_id)
        claim_to_unit: Dict[str, str] = {}
        claim_to_scope: Dict[str, ScopeSignature] = {}
        for u in units:
            if u.source_type == "claim":
                claim_to_unit[u.source_id] = u.unit_id
                claim_to_scope[u.source_id] = u.scope_signature

        # Grouper par axis_value (temporal_scope dans le scope_signature)
        axis_groups: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for chain in chains:
            from_id = chain["from_id"]
            to_id = chain["to_id"]
            change_type = chain.get("change_type", "MODIFIED") or "MODIFIED"

            # Extraire l'axis_value du claim cible
            scope = claim_to_scope.get(to_id, ScopeSignature())
            axis_val = (
                scope.axis_values.get("temporal_scope")
                or scope.axis_values.get("release_id")
                or "unknown"
            )
            unit_id = claim_to_unit.get(to_id, to_id)
            axis_groups[axis_val].append((unit_id, change_type))

        # Construire la timeline (exclure les steps sans axis_value réelle)
        timeline: List[TemporalStep] = []
        for axis_val in sorted(axis_groups.keys()):
            if axis_val == "unknown":
                logger.info(
                    f"[OSMOSE:EvidencePackBuilder] Temporal step 'unknown' ignoré "
                    f"({len(axis_groups[axis_val])} chains sans scope temporel)"
                )
                continue
            entries = axis_groups[axis_val]
            unit_ids = [e[0] for e in entries]
            # Prendre le change_type dominant
            types = [e[1] for e in entries]
            dominant_type = Counter(types).most_common(1)[0][0]
            timeline.append(
                TemporalStep(
                    axis_value=axis_val,
                    change_type=dominant_type,
                    unit_ids=unit_ids,
                )
            )

        if not timeline:
            return None

        return TemporalEvolution(axis_name="temporal_scope", timeline=timeline)

    # ── Étape 5 : Contradictions ─────────────────────────────────────────

    def _step5_contradictions(
        self,
        claims_raw: List[dict],
        concept: ResolvedConcept,
        tenant_id: str,
    ) -> Tuple[List[ConfirmedConflict], List[CandidateTension]]:
        """Détecte les contradictions entre claims via detect_value_contradictions."""
        if len(claims_raw) < 2:
            return [], []

        try:
            from knowbase.claimfirst.clustering.value_contradicts import (
                detect_value_contradictions,
            )
        except ImportError:
            logger.warning(
                "[OSMOSE:EvidencePackBuilder] value_contradicts non disponible"
            )
            return [], []

        # Construire les paires de claims (objets simples avec les attributs requis)
        class _ClaimStub:
            def __init__(self, d: dict):
                self.claim_id = d["claim_id"]
                self.text = d["text"]
                self.claim_type = d["claim_type"]
                self.doc_id = d["doc_id"]
                sf = d.get("structured_form")
                if isinstance(sf, str):
                    import json
                    try:
                        sf = json.loads(sf)
                    except (json.JSONDecodeError, TypeError):
                        sf = {}
                self.structured_form = sf or {}

        stubs = [_ClaimStub(c) for c in claims_raw]
        pairs = []
        for i in range(len(stubs)):
            for j in range(i + 1, len(stubs)):
                pairs.append((stubs[i], stubs[j]))

        if not pairs:
            return [], []

        formal_results, need_llm_pairs, stats = detect_value_contradictions(
            claim_pairs=pairs
        )
        logger.info(
            f"[OSMOSE:EvidencePackBuilder] Contradictions : {stats}"
        )

        # Séparer confirmed (INCOMPATIBLE) et candidate (NEED_LLM)
        # Note : detect_value_contradictions retourne COMPATIBLE ou INCOMPARABLE,
        # jamais directement INCOMPATIBLE. Les NEED_LLM sont les tensions.
        conflicts: List[ConfirmedConflict] = []
        for cid1, cid2, result in formal_results:
            if result.verdict.value == "incomparable":
                conflicts.append(
                    ConfirmedConflict(
                        unit_id_a=cid1,
                        unit_id_b=cid2,
                        conflict_type="INCOMPATIBLE",
                        description=result.basis,
                    )
                )

        tensions: List[CandidateTension] = []
        for c1, c2 in need_llm_pairs:
            tensions.append(
                CandidateTension(
                    unit_id_a=c1.claim_id,
                    unit_id_b=c2.claim_id,
                    tension_type="NEED_LLM",
                    description="Tension possible — nécessite arbitrage humain ou LLM",
                )
            )

        return conflicts, tensions

    # ── Étape 6 : Concepts liés ──────────────────────────────────────────

    def _step6_related(
        self,
        concept: ResolvedConcept,
        tenant_id: str,
        units: List[EvidenceUnit],
    ) -> List[RelatedConcept]:
        """Trouve les entités co-mentionnées dans les mêmes claims (top 10)."""
        query = """
        MATCH (c:Claim)-[:ABOUT]->(e1:Entity),
              (c)-[:ABOUT]->(e2:Entity)
        WHERE e1.entity_id IN $entity_ids
              AND NOT e2.entity_id IN $entity_ids
              AND c.tenant_id = $tenant_id
        WITH e2.name AS name, e2.entity_type AS etype,
             count(DISTINCT c) AS co_count,
             collect(DISTINCT c.claim_id) AS claim_ids
        ORDER BY co_count DESC
        LIMIT 10
        RETURN name, etype, co_count, claim_ids
        """
        # Index unit_id par claim_id
        claim_to_unit: Dict[str, str] = {
            u.source_id: u.unit_id for u in units if u.source_type == "claim"
        }

        related: List[RelatedConcept] = []
        with self._driver.session() as session:
            result = session.run(
                query, entity_ids=concept.entity_ids, tenant_id=tenant_id
            )
            for r in result:
                supporting = [
                    claim_to_unit[cid]
                    for cid in (r["claim_ids"] or [])
                    if cid in claim_to_unit
                ]
                related.append(
                    RelatedConcept(
                        entity_name=r["name"],
                        entity_type=r["etype"] or "concept",
                        co_occurrence_count=r["co_count"],
                        supporting_unit_ids=supporting,
                    )
                )

        return related

    # ── Étape 7 : Quality signals ────────────────────────────────────────

    def _step7_quality(
        self,
        units: List[EvidenceUnit],
        temporal: Optional[TemporalEvolution],
        conflicts: List[ConfirmedConflict],
        tensions: List[CandidateTension],
        concept: ResolvedConcept,
    ) -> QualitySignals:
        """Calcule les signaux de qualité du pack."""
        claim_units = [u for u in units if u.source_type == "claim"]
        chunk_units = [u for u in units if u.source_type == "chunk"]
        doc_ids = set(u.doc_id for u in units)
        roles = set(u.rhetorical_role for u in units)
        has_def = "definition" in roles
        has_temporal = temporal is not None and len(temporal.timeline) > 0

        # Coverage score (0-1)
        coverage = self._compute_coverage(
            len(units), len(doc_ids), len(roles), has_def, has_temporal
        )

        # Coherence risk score (0-1)
        risk, risk_factors = self._compute_coherence_risk(
            units, doc_ids, tensions, conflicts
        )

        # Scope diversity score
        scope_diversity = self._compute_scope_diversity(units)

        return QualitySignals(
            total_units=len(units),
            claim_units=len(claim_units),
            chunk_units=len(chunk_units),
            doc_count=len(doc_ids),
            type_diversity=len(roles),
            has_definition=has_def,
            has_temporal_data=has_temporal,
            confirmed_conflict_count=len(conflicts),
            candidate_tension_count=len(tensions),
            coverage_score=round(coverage, 2),
            coherence_risk_score=round(risk, 2),
            scope_diversity_score=round(scope_diversity, 2),
            coherence_risk_factors=risk_factors,
        )

    @staticmethod
    def _compute_coverage(
        total_units: int,
        doc_count: int,
        type_diversity: int,
        has_definition: bool,
        has_temporal: bool,
    ) -> float:
        """Coverage = richesse du pack (0-1)."""
        score = 0.0
        # Nb units (cap à 50)
        score += min(total_units / 50, 1.0) * 0.30
        # Nb docs (cap à 5)
        score += min(doc_count / 5, 1.0) * 0.25
        # Diversité de types (cap à 4)
        score += min(type_diversity / 4, 1.0) * 0.20
        # Présence définition
        if has_definition:
            score += 0.15
        # Données temporelles
        if has_temporal:
            score += 0.10
        return min(score, 1.0)

    @staticmethod
    def _compute_coherence_risk(
        units: List[EvidenceUnit],
        doc_ids: Set[str],
        tensions: List[CandidateTension],
        conflicts: List[ConfirmedConflict],
    ) -> Tuple[float, List[str]]:
        """Coherence risk = risque de synthèse bancale (0-1, haut = mauvais)."""
        risk = 0.0
        factors: List[str] = []

        if not units:
            return 0.0, []

        # Dominance d'un doc (max pct)
        doc_counts = Counter(u.doc_id for u in units)
        max_pct = max(doc_counts.values()) / len(units)
        if max_pct > 0.50:
            risk += 0.30
            factors.append(f"doc_dominance:{max_pct:.2f}")
        elif max_pct > 0.35:
            risk += 0.15
            factors.append(f"doc_dominance:{max_pct:.2f}")

        # Faible diversité de types
        roles = set(u.rhetorical_role for u in units)
        if len(roles) <= 2:
            risk += 0.20
            factors.append("low_type_diversity")

        # Tensions non résolues
        if tensions:
            risk += min(len(tensions) * 0.10, 0.30)
            factors.append(f"unresolved_tensions:{len(tensions)}")

        # Conflits confirmés
        if conflicts:
            risk += min(len(conflicts) * 0.05, 0.15)
            factors.append(f"confirmed_conflicts:{len(conflicts)}")

        return min(risk, 1.0), factors

    @staticmethod
    def _compute_scope_diversity(units: List[EvidenceUnit]) -> float:
        """Diversité des scope_signatures (0-1, haut = bonne diversité)."""
        if not units:
            return 0.0

        scope_keys = set()
        for u in units:
            s = u.scope_signature
            key = f"{s.doc_type}|{s.generality_level}|{s.temporal_scope_kind}"
            scope_keys.add(key)

        # Score basé sur le nb de scopes distincts (cap à 5)
        return min(len(scope_keys) / 5, 1.0)

    # ── Source index ─────────────────────────────────────────────────────

    @staticmethod
    def _build_source_index(
        units: List[EvidenceUnit],
        scope_cache: Dict[str, ScopeSignature],
        doc_titles: Dict[str, str],
    ) -> List[SourceEntry]:
        """Construit l'index des sources avec contribution_pct."""
        doc_counts: Dict[str, int] = Counter(u.doc_id for u in units)
        total = len(units) if units else 1

        entries: List[SourceEntry] = []
        for doc_id, count in doc_counts.most_common():
            scope = scope_cache.get(doc_id, ScopeSignature())
            entries.append(
                SourceEntry(
                    doc_id=doc_id,
                    doc_title=doc_titles.get(doc_id, ""),
                    unit_count=count,
                    doc_type=scope.doc_type,
                    contribution_pct=round(count / total, 2),
                )
            )
        return entries
