"""
🌊 OSMOSE Research Axes Engine v2 - Phase 3.5+

Service qui génère des axes de recherche contextuels et diversifiés
en explorant le Knowledge Graph à partir des focus_concepts.

Architecture v2 (validée):
- FocusConcepts avec canonical_id et origine (question/answer/chunks)
- Requête Cypher UNWIND batch avec CALL wrapper
- Scoring 3-critères: confidence + anchor_bonus + role_bonus - degree_penalty
- Sélection 2-pass pour diversification réelle par rôle
- Templates FR avec short_label, full_question et explainer_trace
- Cache degree threshold pour éviter les hubs

Roles des axes:
- ACTIONNABLE: Relations REQUIRES, ENABLES (actions à entreprendre)
- RISK: Relations CAUSES, CONFLICTS_WITH (risques à considérer)
- STRUCTURE: Relations PART_OF, SUBTYPE_OF (comprendre le contexte)
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Enums et Constantes
# =============================================================================

class AxisRole(str, Enum):
    """Rôles fonctionnels des axes de recherche."""
    ACTIONNABLE = "actionnable"  # REQUIRES, ENABLES -> actions
    RISK = "risk"                # CAUSES, CONFLICTS_WITH -> risques
    STRUCTURE = "structure"      # PART_OF, SUBTYPE_OF -> contexte


class FocusOrigin(str, Enum):
    """Origine d'un focus concept (pour scoring anchor)."""
    QUESTION = "question"        # Extrait de la question -> poids fort
    EARLY_ANSWER = "early_answer"  # Début de la synthèse -> poids moyen
    CHUNKS = "chunks"            # Chunks sources -> poids faible


# Mapping relation_type -> role
RELATION_TO_ROLE: Dict[str, AxisRole] = {
    # Actionnable: ce qu'il faut pour agir
    "REQUIRES": AxisRole.ACTIONNABLE,
    "ENABLES": AxisRole.ACTIONNABLE,
    "DEPENDS_ON": AxisRole.ACTIONNABLE,
    "IMPLEMENTS": AxisRole.ACTIONNABLE,

    # Risk: ce qui peut mal tourner
    "CAUSES": AxisRole.RISK,
    "CONFLICTS_WITH": AxisRole.RISK,
    "CONTRADICTS": AxisRole.RISK,
    "THREATENS": AxisRole.RISK,
    "AFFECTS": AxisRole.RISK,

    # Structure: comprendre le contexte
    "PART_OF": AxisRole.STRUCTURE,
    "SUBTYPE_OF": AxisRole.STRUCTURE,
    "BELONGS_TO": AxisRole.STRUCTURE,
    "COMPONENT_OF": AxisRole.STRUCTURE,
    "INSTANCE_OF": AxisRole.STRUCTURE,
    "CATEGORIZED_AS": AxisRole.STRUCTURE,
}

# Relations autorisées pour la recherche (typed edges)
ALLOWED_RELATIONS = list(RELATION_TO_ROLE.keys()) + ["RELATED_TO"]

# Nombre d'axes par rôle pour la diversification
AXES_PER_ROLE = {
    AxisRole.ACTIONNABLE: 1,
    AxisRole.RISK: 1,
    AxisRole.STRUCTURE: 1,
}

# Bonus de scoring par origine
ANCHOR_BONUS = {
    FocusOrigin.QUESTION: 0.3,
    FocusOrigin.EARLY_ANSWER: 0.15,
    FocusOrigin.CHUNKS: 0.0,
}

# Note: Les questions sont générées dynamiquement par LLM dans la langue
# de la question originale. Pas de templates hardcodés.


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class FocusConcept:
    """Concept focus avec canonical_id pour les requêtes KG."""
    canonical_id: str
    name: str
    weight: float = 1.0
    origin: FocusOrigin = FocusOrigin.CHUNKS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "name": self.name,
            "weight": self.weight,
            "origin": self.origin.value,
        }


@dataclass
class ResearchAxisCandidate:
    """Candidat intermédiaire pour le scoring avant sélection."""
    # Identifiant unique: source_id|relation_type|target_id|direction
    candidate_key: str

    # Données de base
    source_id: str
    source_name: str
    target_id: str
    target_name: str
    relation_type: str
    relation_id: str
    direction: str  # 'outgoing' ou 'incoming'

    # Scoring
    confidence: float
    focus_weight: float
    focus_origin: FocusOrigin
    role: AxisRole

    # Score calculé
    score: float = 0.0

    # Pour l'explainer
    trace: str = ""


@dataclass
class ResearchAxis:
    """Axe de recherche final avec question contextuelle."""

    axis_id: str
    role: AxisRole

    # Labels générés
    short_label: str
    full_question: str

    # Concepts impliqués
    source_concept: str
    target_concept: str
    relation_type: str

    # Scoring et métadonnées
    relevance_score: float
    confidence: float

    # Explainer: trace du chemin KG
    explainer_trace: str

    # Pour la recherche
    search_query: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "axis_id": self.axis_id,
            "role": self.role.value,
            "short_label": self.short_label,
            "full_question": self.full_question,
            "source_concept": self.source_concept,
            "target_concept": self.target_concept,
            "relation_type": self.relation_type,
            "relevance_score": self.relevance_score,
            "confidence": self.confidence,
            "explainer_trace": self.explainer_trace,
            "search_query": self.search_query,
        }


@dataclass
class ResearchAxesResult:
    """Résultat complet du Research Axes Engine."""

    axes: List[ResearchAxis] = field(default_factory=list)

    # Contexte
    query_context: str = ""
    focus_concepts_count: int = 0

    # Métriques
    processing_time_ms: float = 0.0
    candidates_found: int = 0
    roles_distribution: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "axes": [a.to_dict() for a in self.axes],
            "query_context": self.query_context,
            "focus_concepts_count": self.focus_concepts_count,
            "processing_time_ms": self.processing_time_ms,
            "candidates_found": self.candidates_found,
            "roles_distribution": self.roles_distribution,
        }


# =============================================================================
# Research Axes Engine v2
# =============================================================================

class ResearchAxesEngine:
    """
    🌊 Moteur de génération d'axes de recherche v2.

    Utilise les focus_concepts avec canonical_id pour explorer
    le Knowledge Graph et générer des suggestions contextuelles
    et diversifiées par rôle (actionnable, risk, structure).
    """

    def __init__(
        self,
        max_axes: int = 3,
        min_confidence: float = 0.3,
        degree_penalty_percentile: float = 0.95,  # Top 5% = hubs
    ):
        self._neo4j_client = None
        self.max_axes = max_axes
        self.min_confidence = min_confidence
        self.degree_penalty_percentile = degree_penalty_percentile

        # Cache pour le degree threshold
        self._degree_threshold_cache: Dict[str, Tuple[int, float]] = {}
        self._degree_cache_ttl = 300  # 5 minutes

        self._axis_counter = 0

        logger.info("[OSMOSE] ResearchAxesEngine v2 initialized")

    @property
    def neo4j_client(self):
        """Lazy loading du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.neo4j_custom.client import get_neo4j_client
            self._neo4j_client = get_neo4j_client()
        return self._neo4j_client

    def _generate_axis_id(self, role: AxisRole) -> str:
        """Génère un ID unique pour un axe."""
        self._axis_counter += 1
        return f"axis_{role.value[:4]}_{self._axis_counter:04d}"

    # -------------------------------------------------------------------------
    # Extraction des Focus Concepts
    # -------------------------------------------------------------------------

    async def extract_focus_concepts(
        self,
        query_concepts: List[str],
        graph_context: Dict[str, Any],
        synthesis_answer: str = "",
        chunks: List[Dict[str, Any]] = None,
        tenant_id: str = "default",
    ) -> List[FocusConcept]:
        """
        Extrait les focus concepts avec leurs canonical_id et origine.

        Sources:
        1. query_concepts -> origine QUESTION (poids fort)
        2. concepts du début de la réponse -> origine EARLY_ANSWER (poids moyen)
        3. concepts des chunks -> origine CHUNKS (poids faible)
        """
        focus_concepts: Dict[str, FocusConcept] = {}

        # 1. Query concepts (origine QUESTION)
        # Récupérer les canonical_id depuis Neo4j
        if query_concepts:
            query_ids = await self._get_canonical_ids(query_concepts, tenant_id)
            for name, cid in query_ids.items():
                focus_concepts[cid] = FocusConcept(
                    canonical_id=cid,
                    name=name,
                    weight=1.0,
                    origin=FocusOrigin.QUESTION,
                )

        # 2. Related concepts du graph_context (origine EARLY_ANSWER)
        related = graph_context.get("related_concepts", [])
        if related:
            related_names = [r.get("concept", "") for r in related[:5] if r.get("concept")]
            related_ids = await self._get_canonical_ids(related_names, tenant_id)
            for name, cid in related_ids.items():
                if cid not in focus_concepts:
                    focus_concepts[cid] = FocusConcept(
                        canonical_id=cid,
                        name=name,
                        weight=0.7,
                        origin=FocusOrigin.EARLY_ANSWER,
                    )

        # 3. Concepts des chunks (origine CHUNKS) - optionnel
        if chunks:
            chunk_concepts = set()
            for chunk in chunks[:5]:
                payload = chunk.get("payload", chunk)
                concepts = payload.get("concepts", [])
                if isinstance(concepts, list):
                    chunk_concepts.update(concepts[:3])

            if chunk_concepts:
                chunk_ids = await self._get_canonical_ids(list(chunk_concepts), tenant_id)
                for name, cid in chunk_ids.items():
                    if cid not in focus_concepts:
                        focus_concepts[cid] = FocusConcept(
                            canonical_id=cid,
                            name=name,
                            weight=0.5,
                            origin=FocusOrigin.CHUNKS,
                        )

        result = list(focus_concepts.values())
        logger.info(
            f"[OSMOSE] Extracted {len(result)} focus concepts: "
            f"{sum(1 for f in result if f.origin == FocusOrigin.QUESTION)} question, "
            f"{sum(1 for f in result if f.origin == FocusOrigin.EARLY_ANSWER)} early_answer, "
            f"{sum(1 for f in result if f.origin == FocusOrigin.CHUNKS)} chunks"
        )

        return result

    async def _get_canonical_ids(
        self,
        concept_names: List[str],
        tenant_id: str
    ) -> Dict[str, str]:
        """Récupère les canonical_id pour une liste de noms de concepts."""
        if not concept_names:
            return {}

        cypher = """
        UNWIND $names AS name
        MATCH (c:CanonicalConcept {tenant_id: $tid})
        WHERE c.canonical_name = name OR toLower(c.canonical_name) = toLower(name)
        RETURN c.canonical_name AS name, c.canonical_id AS id
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "names": concept_names,
                "tid": tenant_id,
            })

            return {r["name"]: r["id"] for r in results if r.get("id")}

        except Exception as e:
            logger.warning(f"[OSMOSE] Failed to get canonical IDs: {e}")
            return {}

    # -------------------------------------------------------------------------
    # Requête Cypher UNWIND avec CALL wrapper
    # -------------------------------------------------------------------------

    async def query_kg_relations(
        self,
        focus_concepts: List[FocusConcept],
        tenant_id: str,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Exécute la requête UNWIND batch avec CALL wrapper.

        Récupère les relations sortantes (concept -> target) et entrantes
        (target -> concept) pour les relations structurelles (PART_OF, SUBTYPE_OF).
        """
        if not focus_concepts:
            return []

        # Préparer les paramètres
        focus_params = [
            {
                "id": f.canonical_id,
                "weight": f.weight,
                "origin": f.origin.value,
            }
            for f in focus_concepts
        ]

        # Requête avec CALL wrapper pour UNION + ORDER BY/LIMIT
        cypher = """
        CALL {
            UNWIND $focus AS f
            MATCH (c:CanonicalConcept {tenant_id: $tid, canonical_id: f.id})-[r]->(t:CanonicalConcept)
            WHERE type(r) IN $allowed_rels AND coalesce(r.confidence, 0.5) >= $min_conf
            RETURN
                f.id AS source_id,
                c.canonical_name AS source_name,
                t.canonical_id AS target_id,
                t.canonical_name AS target_name,
                type(r) AS rel,
                coalesce(r.confidence, 0.5) AS conf,
                coalesce(r.canonical_relation_id, '') AS rel_id,
                f.weight AS focus_weight,
                f.origin AS focus_origin,
                'outgoing' AS direction

            UNION ALL

            UNWIND $focus AS f
            MATCH (t:CanonicalConcept)-[r]->(c:CanonicalConcept {tenant_id: $tid, canonical_id: f.id})
            WHERE type(r) IN ['PART_OF', 'SUBTYPE_OF', 'BELONGS_TO', 'COMPONENT_OF']
              AND coalesce(r.confidence, 0.5) >= $min_conf
            RETURN
                f.id AS source_id,
                c.canonical_name AS source_name,
                t.canonical_id AS target_id,
                t.canonical_name AS target_name,
                type(r) AS rel,
                coalesce(r.confidence, 0.5) AS conf,
                coalesce(r.canonical_relation_id, '') AS rel_id,
                f.weight AS focus_weight,
                f.origin AS focus_origin,
                'incoming' AS direction
        }
        RETURN * ORDER BY conf DESC LIMIT $limit
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "focus": focus_params,
                "tid": tenant_id,
                "allowed_rels": ALLOWED_RELATIONS,
                "min_conf": self.min_confidence,
                "limit": limit,
            })

            logger.info(f"[OSMOSE] KG query returned {len(results)} relations")
            return results

        except Exception as e:
            logger.error(f"[OSMOSE] KG query failed: {e}")
            return []

    # -------------------------------------------------------------------------
    # Scoring des candidats
    # -------------------------------------------------------------------------

    async def score_candidates(
        self,
        raw_relations: List[Dict[str, Any]],
        focus_concepts: List[FocusConcept],
        tenant_id: str,
    ) -> List[ResearchAxisCandidate]:
        """
        Score les relations avec les 3 critères:
        - confidence * 2
        - anchor_bonus (selon origine)
        - role_bonus (pour diversité)
        - degree_penalty (pour éviter hubs)

        Utilise une clé unique pour dédupliquer.
        """
        if not raw_relations:
            return []

        # Récupérer le threshold de degree pour pénaliser les hubs
        degree_threshold = await self._get_degree_threshold(tenant_id)

        # Index des focus concepts par ID
        focus_index = {f.canonical_id: f for f in focus_concepts}

        # Dédupliquer par clé unique et scorer
        candidates_by_key: Dict[str, ResearchAxisCandidate] = {}

        for rel in raw_relations:
            source_id = rel.get("source_id", "")
            target_id = rel.get("target_id", "")
            relation_type = rel.get("rel", "RELATED_TO")
            direction = rel.get("direction", "outgoing")

            # Clé unique
            candidate_key = f"{source_id}|{relation_type}|{target_id}|{direction}"

            if candidate_key in candidates_by_key:
                continue

            # Déterminer le rôle
            role = RELATION_TO_ROLE.get(relation_type, AxisRole.STRUCTURE)

            # Récupérer l'origine du focus
            focus_origin_str = rel.get("focus_origin", "chunks")
            try:
                focus_origin = FocusOrigin(focus_origin_str)
            except ValueError:
                focus_origin = FocusOrigin.CHUNKS

            confidence = rel.get("conf", 0.5)
            focus_weight = rel.get("focus_weight", 1.0)

            # Calculer le score
            score = (
                confidence * 2.0  # Confidence pondérée
                + ANCHOR_BONUS.get(focus_origin, 0.0)  # Bonus anchor
                + 0.1 * focus_weight  # Poids du focus
            )

            # TODO: Ajouter degree_penalty quand on a la métrique degree sur les nœuds
            # Pour l'instant, on ne pénalise pas les hubs

            # Trace pour l'explainer
            source_name = rel.get("source_name", "")
            target_name = rel.get("target_name", "")
            trace = f"{source_name} --[{relation_type}]--> {target_name}"
            if direction == "incoming":
                trace = f"{target_name} --[{relation_type}]--> {source_name}"

            candidate = ResearchAxisCandidate(
                candidate_key=candidate_key,
                source_id=source_id,
                source_name=source_name,
                target_id=target_id,
                target_name=target_name,
                relation_type=relation_type,
                relation_id=rel.get("rel_id", ""),
                direction=direction,
                confidence=confidence,
                focus_weight=focus_weight,
                focus_origin=focus_origin,
                role=role,
                score=score,
                trace=trace,
            )

            candidates_by_key[candidate_key] = candidate

        candidates = list(candidates_by_key.values())
        logger.info(f"[OSMOSE] Scored {len(candidates)} unique candidates")

        return candidates

    async def _get_degree_threshold(self, tenant_id: str) -> int:
        """
        Récupère le threshold de degree (95e percentile) pour pénaliser les hubs.
        Utilise un cache de 5 minutes.
        """
        now = time.time()

        # Vérifier le cache
        if tenant_id in self._degree_threshold_cache:
            cached_threshold, cached_time = self._degree_threshold_cache[tenant_id]
            if now - cached_time < self._degree_cache_ttl:
                return cached_threshold

        # Calculer le threshold
        cypher = """
        MATCH (c:CanonicalConcept {tenant_id: $tid})
        WITH c, size((c)--()) AS degree
        RETURN percentileCont(degree, $percentile) AS threshold
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "tid": tenant_id,
                "percentile": self.degree_penalty_percentile,
            })

            threshold = int(results[0].get("threshold", 100)) if results else 100
            self._degree_threshold_cache[tenant_id] = (threshold, now)

            logger.debug(f"[OSMOSE] Degree threshold for {tenant_id}: {threshold}")
            return threshold

        except Exception as e:
            logger.warning(f"[OSMOSE] Failed to get degree threshold: {e}")
            return 100  # Default

    # -------------------------------------------------------------------------
    # Sélection 2-pass par rôle
    # -------------------------------------------------------------------------

    def select_diverse_axes(
        self,
        candidates: List[ResearchAxisCandidate],
    ) -> List[ResearchAxisCandidate]:
        """
        Sélection 2-pass pour garantir la diversification par rôle.

        Pass 1: Prendre le meilleur candidat de chaque rôle
        Pass 2: Compléter avec les meilleurs restants si < max_axes
        """
        if not candidates:
            return []

        # Trier par score décroissant
        sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)

        selected: List[ResearchAxisCandidate] = []
        used_keys: Set[str] = set()

        # Pass 1: Un par rôle
        for role in [AxisRole.ACTIONNABLE, AxisRole.RISK, AxisRole.STRUCTURE]:
            quota = AXES_PER_ROLE.get(role, 1)
            count = 0

            for candidate in sorted_candidates:
                if candidate.role == role and candidate.candidate_key not in used_keys:
                    selected.append(candidate)
                    used_keys.add(candidate.candidate_key)
                    count += 1
                    if count >= quota:
                        break

        # Pass 2: Compléter si nécessaire
        if len(selected) < self.max_axes:
            for candidate in sorted_candidates:
                if candidate.candidate_key not in used_keys:
                    selected.append(candidate)
                    used_keys.add(candidate.candidate_key)
                    if len(selected) >= self.max_axes:
                        break

        logger.info(
            f"[OSMOSE] Selected {len(selected)} axes: "
            f"actionnable={sum(1 for s in selected if s.role == AxisRole.ACTIONNABLE)}, "
            f"risk={sum(1 for s in selected if s.role == AxisRole.RISK)}, "
            f"structure={sum(1 for s in selected if s.role == AxisRole.STRUCTURE)}"
        )

        return selected

    # -------------------------------------------------------------------------
    # Génération des axes finaux avec LLM (multilingue)
    # -------------------------------------------------------------------------

    async def generate_axes(
        self,
        selected_candidates: List[ResearchAxisCandidate],
        original_query: str = "",
    ) -> List[ResearchAxis]:
        """
        Génère les axes finaux avec des questions générées par LLM.

        Le LLM détecte la langue de la query originale et génère
        les questions dans cette langue.
        """
        if not selected_candidates:
            return []

        # Générer les questions via LLM
        questions = await self._generate_questions_with_llm(
            candidates=selected_candidates,
            original_query=original_query,
        )

        axes = []
        for i, candidate in enumerate(selected_candidates):
            # Récupérer les questions générées ou fallback
            q = questions.get(i, {})
            short_label = q.get("short", f"{candidate.source_name} → {candidate.target_name}")
            full_question = q.get("full", short_label)

            # Search query (concepts bruts, pas de langue)
            search_query = f"{candidate.source_name} {candidate.target_name}"

            axis = ResearchAxis(
                axis_id=self._generate_axis_id(candidate.role),
                role=candidate.role,
                short_label=short_label,
                full_question=full_question,
                source_concept=candidate.source_name,
                target_concept=candidate.target_name,
                relation_type=candidate.relation_type,
                relevance_score=min(candidate.score / 3.0, 1.0),
                confidence=candidate.confidence,
                explainer_trace=candidate.trace,
                search_query=search_query,
            )

            axes.append(axis)

        return axes

    async def _generate_questions_with_llm(
        self,
        candidates: List[ResearchAxisCandidate],
        original_query: str,
    ) -> Dict[int, Dict[str, str]]:
        """
        Génère les questions via LLM dans la langue de la query.

        Fait UN appel batch pour tous les candidats.

        Returns:
            Dict[index, {"short": "...", "full": "..."}]
        """
        if not candidates:
            return {}

        try:
            from knowbase.common.llm_router import get_llm_router, TaskType

            # Construire le prompt batch
            relations_desc = []
            for i, c in enumerate(candidates):
                role_desc = {
                    AxisRole.ACTIONNABLE: "action/prerequisite",
                    AxisRole.RISK: "risk/impact",
                    AxisRole.STRUCTURE: "context/structure",
                }.get(c.role, "general")

                relations_desc.append(
                    f"{i}. [{role_desc}] {c.source_name} --[{c.relation_type}]--> {c.target_name}"
                )

            prompt = f"""Based on this user question: "{original_query}"

Generate follow-up questions for these knowledge graph relations.
IMPORTANT: Detect the language of the user question and generate ALL questions in that SAME language.

Relations to convert into questions:
{chr(10).join(relations_desc)}

For each relation, generate:
- "short": A concise question (max 50 chars) that a user might ask
- "full": A complete, natural question for deeper exploration

Output format (JSON array, same order as input):
[
  {{"short": "...", "full": "..."}},
  ...
]

Rules:
- Questions must be in the SAME language as the user question
- Questions should be natural and contextual, not robotic
- Focus on what would help the user explore further
- For action relations: ask about requirements, steps, how-to
- For risk relations: ask about impacts, mitigation, concerns
- For structure relations: ask about context, components, categories

Output ONLY the JSON array, no explanation."""

            router = get_llm_router()
            response = router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000,
            )

            # Parser la réponse JSON
            import json
            # Nettoyer la réponse (enlever markdown si présent)
            content = response.get("content", "") if isinstance(response, dict) else str(response)
            clean_response = content.strip()
            if clean_response.startswith("```"):
                clean_response = clean_response.split("```")[1]
                if clean_response.startswith("json"):
                    clean_response = clean_response[4:]

            questions_list = json.loads(clean_response)

            # Convertir en dict indexé
            result = {}
            for i, q in enumerate(questions_list):
                if isinstance(q, dict):
                    result[i] = {
                        "short": q.get("short", ""),
                        "full": q.get("full", ""),
                    }

            logger.info(f"[OSMOSE] LLM generated {len(result)} questions for research axes")
            # Debug: afficher les questions générées
            for idx, q in result.items():
                logger.debug(f"[OSMOSE] Axis {idx}: short='{q.get('short', '')[:50]}...'")
            return result

        except Exception as e:
            logger.warning(f"[OSMOSE] LLM question generation failed: {e}, using fallback")
            # Fallback: questions basiques (relation brute)
            return {
                i: {
                    "short": f"{c.source_name} → {c.target_name}?",
                    "full": f"{c.source_name} {c.relation_type} {c.target_name}",
                }
                for i, c in enumerate(candidates)
            }

    # -------------------------------------------------------------------------
    # Point d'entrée principal
    # -------------------------------------------------------------------------

    async def generate_research_axes(
        self,
        query: str,
        synthesis_answer: str,
        query_concepts: List[str],
        graph_context: Dict[str, Any],
        chunks: List[Dict[str, Any]] = None,
        tenant_id: str = "default",
    ) -> ResearchAxesResult:
        """
        Génère des axes de recherche contextuels et diversifiés.

        Args:
            query: Question de l'utilisateur
            synthesis_answer: Réponse synthétisée
            query_concepts: Concepts identifiés dans la query
            graph_context: Contexte KG (related_concepts, etc.)
            chunks: Chunks utilisés pour la réponse
            tenant_id: Tenant ID

        Returns:
            ResearchAxesResult avec les axes générés
        """
        start_time = time.time()

        result = ResearchAxesResult(
            query_context=query[:200],
        )

        try:
            # 1. Extraire les focus concepts avec canonical_id
            focus_concepts = await self.extract_focus_concepts(
                query_concepts=query_concepts,
                graph_context=graph_context,
                synthesis_answer=synthesis_answer,
                chunks=chunks,
                tenant_id=tenant_id,
            )

            result.focus_concepts_count = len(focus_concepts)

            if not focus_concepts:
                logger.info("[OSMOSE] No focus concepts found, returning empty result")
                result.processing_time_ms = (time.time() - start_time) * 1000
                return result

            # 2. Requête KG batch avec UNWIND
            raw_relations = await self.query_kg_relations(
                focus_concepts=focus_concepts,
                tenant_id=tenant_id,
            )

            if not raw_relations:
                logger.info("[OSMOSE] No relations found in KG")
                result.processing_time_ms = (time.time() - start_time) * 1000
                return result

            # 3. Scorer les candidats
            candidates = await self.score_candidates(
                raw_relations=raw_relations,
                focus_concepts=focus_concepts,
                tenant_id=tenant_id,
            )

            result.candidates_found = len(candidates)

            # 4. Sélection 2-pass diversifiée
            selected = self.select_diverse_axes(candidates)

            # 5. Générer les axes finaux (avec LLM pour questions multilingues)
            result.axes = await self.generate_axes(selected, original_query=query)

            # Métriques
            result.roles_distribution = {
                "actionnable": sum(1 for a in result.axes if a.role == AxisRole.ACTIONNABLE),
                "risk": sum(1 for a in result.axes if a.role == AxisRole.RISK),
                "structure": sum(1 for a in result.axes if a.role == AxisRole.STRUCTURE),
            }

        except Exception as e:
            logger.error(f"[OSMOSE] Research axes generation failed: {e}", exc_info=True)

        result.processing_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"[OSMOSE] Generated {len(result.axes)} research axes "
            f"({result.processing_time_ms:.1f}ms)"
        )

        return result


# =============================================================================
# Singleton
# =============================================================================

_engine_instance: Optional[ResearchAxesEngine] = None


def get_research_axes_engine() -> ResearchAxesEngine:
    """Retourne l'instance singleton du ResearchAxesEngine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ResearchAxesEngine()
    return _engine_instance


__all__ = [
    "ResearchAxesEngine",
    "ResearchAxesResult",
    "ResearchAxis",
    "ResearchAxisCandidate",
    "FocusConcept",
    "AxisRole",
    "FocusOrigin",
    "get_research_axes_engine",
]
