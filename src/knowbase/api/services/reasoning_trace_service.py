"""
Reasoning Trace Service - OSMOSE Answer+Proof Bloc C

Genere le chemin de preuve narratif pour une reponse.
Montre POURQUOI la reponse tient en affichant les relations KG utilisees.

Approche hybride:
- KG pour les supports (relations) - fiable, auditable
- LLM uniquement pour le "statement" narratif de chaque etape
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import asyncio

from knowbase.config.settings import Settings
from knowbase.common.logging import setup_logging

_settings = Settings()
logger = setup_logging(_settings.logs_dir, "reasoning_trace_service.log")


@dataclass
class ReasoningSupport:
    """Une relation KG qui soutient une etape du raisonnement."""
    relation_type: str                    # "REQUIRES", "CAUSES", etc.
    source_concept_id: str                # UUID du concept source
    source_concept_name: str              # Nom lisible
    target_concept_id: str                # UUID du concept cible
    target_concept_name: str              # Nom lisible
    edge_confidence: float                # Confiance de la relation
    canonical_relation_id: Optional[str] = None  # Pour tracabilite
    source_refs: List[str] = field(default_factory=list)  # ["doc1.pptx:slide12"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relation_type": self.relation_type,
            "source_concept_id": self.source_concept_id,
            "source_concept_name": self.source_concept_name,
            "target_concept_id": self.target_concept_id,
            "target_concept_name": self.target_concept_name,
            "edge_confidence": self.edge_confidence,
            "canonical_relation_id": self.canonical_relation_id,
            "source_refs": self.source_refs,
        }


@dataclass
class ReasoningStep:
    """Une etape dans le chemin de raisonnement."""
    step_number: int
    statement: str                        # Phrase narrative (LLM ou template)
    supports: List[ReasoningSupport] = field(default_factory=list)
    has_kg_support: bool = True           # True si au moins 1 support KG
    is_conflict: bool = False             # True si CONFLICTS_WITH detecte
    source_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step_number,
            "statement": self.statement,
            "has_kg_support": self.has_kg_support,
            "is_conflict": self.is_conflict,
            "supports": [s.to_dict() for s in self.supports],
            "source_refs": self.source_refs,
        }


@dataclass
class ReasoningTrace:
    """Trace complete du raisonnement (Bloc C)."""
    steps: List[ReasoningStep] = field(default_factory=list)
    coherence_status: str = "coherent"    # "coherent", "partial_conflict", "conflict"
    coherence_message: str = ""
    unsupported_steps_count: int = 0      # Nombre d'etapes sans support KG

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coherence_status": self.coherence_status,
            "coherence_message": self.coherence_message,
            "unsupported_steps_count": self.unsupported_steps_count,
            "steps": [s.to_dict() for s in self.steps],
        }


# Note: Les phrases sont générées par LLM dans la langue de la question.
# Pas de templates hardcodés pour supporter le multilingue.


class ReasoningTraceService:
    """Service pour construire la Trace de Raisonnement (Bloc C)."""

    def __init__(self, neo4j_driver=None, use_llm: bool = True):
        """
        Initialise le service.

        Args:
            neo4j_driver: Driver Neo4j optionnel
            use_llm: Si True, utilise le LLM pour narrativiser (active par defaut)
        """
        self._neo4j_driver = neo4j_driver
        self._use_llm = use_llm

    def _get_neo4j_driver(self):
        """Recupere le driver Neo4j (lazy loading)."""
        if self._neo4j_driver is None:
            try:
                from knowbase.common.clients.neo4j_client import get_neo4j_client
                self._neo4j_driver = get_neo4j_client().driver
            except Exception as e:
                logger.warning(f"Could not get Neo4j driver: {e}")
                return None
        return self._neo4j_driver

    async def build_reasoning_trace(
        self,
        query: str,
        answer: str,
        focus_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
        tenant_id: str = "default",
    ) -> ReasoningTrace:
        """
        Construit le chemin de raisonnement.

        Args:
            query: Question de l'utilisateur
            answer: Reponse synthetisee
            focus_concepts: Concepts principaux de la question
            related_concepts: Relations du graph_context
            tenant_id: Tenant ID

        Returns:
            ReasoningTrace
        """
        # Etape 1: Extraire les chemins depuis le KG
        paths = await self._extract_kg_paths(focus_concepts, tenant_id)

        # Etape 2: Si pas de chemins Neo4j, fallback sur related_concepts
        if not paths:
            paths = self._build_paths_from_context(focus_concepts, related_concepts)

        # Etape 3: Convertir les chemins en etapes de raisonnement
        steps = self._paths_to_steps(paths)

        # Etape 4: Optionnel - enrichir avec LLM
        if self._use_llm and steps:
            steps = await self._enrich_with_llm(query, answer, steps)

        # Etape 5: Calculer le statut de coherence
        coherence_status, coherence_message = self._compute_coherence(steps)

        # Etape 6: Compter les etapes non supportees
        unsupported = sum(1 for s in steps if not s.has_kg_support)

        return ReasoningTrace(
            steps=steps,
            coherence_status=coherence_status,
            coherence_message=coherence_message,
            unsupported_steps_count=unsupported,
        )

    async def _extract_kg_paths(
        self,
        concept_names: List[str],
        tenant_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Extrait les chemins de relations depuis Neo4j.

        Suit les relations typees (pas ASSOCIATED_WITH) depuis les concepts.
        """
        driver = self._get_neo4j_driver()
        if not driver or not concept_names:
            return []

        try:
            cypher = """
            UNWIND $concepts AS concept_name
            MATCH (c:CanonicalConcept {tenant_id: $tid})
            WHERE toLower(c.canonical_name) = toLower(concept_name)

            // Suivre les relations typees (profondeur 1-2)
            MATCH path = (c)-[r:REQUIRES|CAUSES|ENABLES|PART_OF|SUBTYPE_OF|CONFLICTS_WITH*1..2]->(target:CanonicalConcept {tenant_id: $tid})

            UNWIND relationships(path) AS rel
            WITH c, target, rel, startNode(rel) AS src, endNode(rel) AS tgt

            RETURN DISTINCT
                src.canonical_id AS source_id,
                src.canonical_name AS source_name,
                tgt.canonical_id AS target_id,
                tgt.canonical_name AS target_name,
                type(rel) AS relation_type,
                rel.confidence AS confidence,
                rel.canonical_relation_id AS relation_id
            ORDER BY confidence DESC
            LIMIT 20
            """

            paths = []
            with driver.session() as session:
                result = session.run(cypher, {
                    "concepts": concept_names,
                    "tid": tenant_id,
                })
                for record in result:
                    paths.append({
                        "source_id": record["source_id"],
                        "source_name": record["source_name"],
                        "target_id": record["target_id"],
                        "target_name": record["target_name"],
                        "relation_type": record["relation_type"],
                        "confidence": record["confidence"] or 0.0,
                        "relation_id": record["relation_id"],
                    })

            return paths

        except Exception as e:
            logger.warning(f"Neo4j path extraction failed: {e}")
            return []

    def _build_paths_from_context(
        self,
        focus_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Construit les chemins depuis les donnees du graph_context.

        Fallback quand Neo4j n'est pas disponible.

        Note: On accepte TOUTES les relations (y compris ASSOCIATED_WITH)
        car c'est souvent le seul type disponible dans un KG naissant.
        """
        # Separer les relations typees des ASSOCIATED_WITH
        typed_paths = []
        associated_paths = []

        for rel in related_concepts:
            relation_type = rel.get("relation", "")
            source = rel.get("source", "")
            target = rel.get("concept", "")

            if not source or not target or not relation_type:
                continue

            path = {
                "source_id": "",  # Pas disponible
                "source_name": source,
                "target_id": "",
                "target_name": target,
                "relation_type": relation_type,
                "confidence": rel.get("confidence", 0.0),
                "relation_id": None,
            }

            if relation_type == "ASSOCIATED_WITH":
                associated_paths.append(path)
            else:
                typed_paths.append(path)

        # Privilegier les relations typees, sinon fallback sur ASSOCIATED_WITH
        if typed_paths:
            return typed_paths
        return associated_paths

    def _paths_to_steps(self, paths: List[Dict[str, Any]]) -> List[ReasoningStep]:
        """
        Convertit les chemins KG en etapes de raisonnement.

        Groupe par concept source pour eviter les repetitions.
        """
        if not paths:
            return []

        # Grouper par source
        by_source: Dict[str, List[Dict]] = {}
        for path in paths:
            source = path["source_name"]
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(path)

        # Creer les etapes
        steps = []
        step_num = 1

        for source_name, source_paths in by_source.items():
            # Creer les supports
            supports = []
            is_conflict = False

            for p in source_paths:
                if p["relation_type"] == "CONFLICTS_WITH":
                    is_conflict = True

                supports.append(ReasoningSupport(
                    relation_type=p["relation_type"],
                    source_concept_id=p.get("source_id", ""),
                    source_concept_name=p["source_name"],
                    target_concept_id=p.get("target_id", ""),
                    target_concept_name=p["target_name"],
                    edge_confidence=p.get("confidence", 0.0),
                    canonical_relation_id=p.get("relation_id"),
                    source_refs=[],
                ))

            # Generer le statement placeholder (sera enrichi par LLM)
            statement = self._generate_statement_placeholder(source_name, source_paths)

            steps.append(ReasoningStep(
                step_number=step_num,
                statement=statement,
                supports=supports,
                has_kg_support=len(supports) > 0,
                is_conflict=is_conflict,
                source_refs=[],
            ))

            step_num += 1

        return steps

    def _generate_statement_placeholder(
        self,
        source_name: str,
        paths: List[Dict[str, Any]],
    ) -> str:
        """
        Genere un statement placeholder depuis les relations.

        Ce placeholder sera remplace par le LLM pour une phrase naturelle.
        Utilise uniquement en fallback si LLM echoue.
        """
        if not paths:
            return f"{source_name}"

        # Format simple: source -> relation -> target
        first = paths[0]
        relation_type = first["relation_type"]
        target_name = first["target_name"]

        # Placeholder minimal (sera remplace par LLM)
        statement = f"{source_name} [{relation_type}] {target_name}"

        if len(paths) > 1:
            statement += f" (+{len(paths)-1})"

        return statement

    async def _enrich_with_llm(
        self,
        query: str,
        answer: str,
        steps: List[ReasoningStep],
    ) -> List[ReasoningStep]:
        """
        Enrichit les statements avec un LLM pour des phrases naturelles.

        Detecte la langue de la question et genere dans la meme langue.
        """
        if not steps:
            return steps

        try:
            from knowbase.common.llm_router import get_llm_router, TaskType
            # Note: Use KNOWLEDGE_EXTRACTION for structured JSON extraction

            # Construire la liste des triplets pour le prompt
            triplets_text = []
            for i, step in enumerate(steps):
                step_triplets = []
                for support in step.supports:
                    triplet = f"  - {support.source_concept_name} --[{support.relation_type}]--> {support.target_concept_name}"
                    if support.edge_confidence > 0:
                        triplet += f" (confidence: {support.edge_confidence:.0%})"
                    step_triplets.append(triplet)

                if step_triplets:
                    triplets_text.append(f"Step {i + 1}:\n" + "\n".join(step_triplets))

            if not triplets_text:
                return steps

            prompt = f"""You are helping explain WHY an answer is supported by a knowledge graph.

User question: "{query}"

Here are the knowledge graph relationships that support the answer:
{chr(10).join(triplets_text)}

Generate a natural language explanation for each step.
IMPORTANT: Detect the language of the user question and generate ALL explanations in that SAME language.

For each step, write a clear, concise sentence that explains the relationship in natural language.
Focus on explaining the logical connection, not just stating the relationship.

Return JSON format:
{{
  "statements": [
    {{"step": 1, "statement": "Natural explanation for step 1"}},
    {{"step": 2, "statement": "Natural explanation for step 2"}}
  ]
}}

Only return valid JSON, no markdown."""

            router = get_llm_router()
            response = router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
            )

            # Parser la reponse JSON
            import json
            import re

            # router.complete() retourne une string directement
            content = response if isinstance(response, str) else str(response)

            # Nettoyer les balises markdown si presentes
            content = re.sub(r"```json\s*", "", content)
            content = re.sub(r"```\s*", "", content)
            content = content.strip()

            data = json.loads(content)
            statements_list = data.get("statements", [])

            # Creer un mapping step -> statement
            statements_map = {s["step"]: s["statement"] for s in statements_list}

            # Mettre a jour les steps
            for step in steps:
                if step.step_number in statements_map:
                    step.statement = statements_map[step.step_number]

            logger.info(f"Enriched {len(statements_map)} reasoning steps with LLM")

        except Exception as e:
            logger.warning(f"LLM enrichment failed, keeping placeholders: {e}")
            # En cas d'erreur, on garde les placeholders

        return steps

    def _compute_coherence(
        self,
        steps: List[ReasoningStep],
    ) -> tuple[str, str]:
        """
        Calcule le statut de coherence global.

        Returns:
            (status, message) - message is empty, frontend renders based on status
        """
        if not steps:
            return "incomplete", ""

        # Verifier les conflits
        conflict_count = sum(1 for s in steps if s.is_conflict)

        if conflict_count > 1:
            return "conflict", ""
        elif conflict_count == 1:
            return "partial_conflict", ""

        # Verifier les etapes non supportees
        unsupported = sum(1 for s in steps if not s.has_kg_support)
        if unsupported > 0:
            return "partial_conflict", ""

        return "coherent", ""


# === Fonction synchrone wrapper ===

def build_reasoning_trace_sync(
    query: str,
    answer: str,
    focus_concepts: List[str],
    related_concepts: List[Dict[str, Any]],
    tenant_id: str = "default",
) -> ReasoningTrace:
    """
    Version synchrone de build_reasoning_trace.

    Utilise pour l'integration dans search.py (synchrone).
    """
    service = get_reasoning_trace_service()

    # Executer dans une boucle async
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            service.build_reasoning_trace(
                query=query,
                answer=answer,
                focus_concepts=focus_concepts,
                related_concepts=related_concepts,
                tenant_id=tenant_id,
            )
        )
    finally:
        loop.close()


# === Singleton ===

_reasoning_trace_service: Optional[ReasoningTraceService] = None


def get_reasoning_trace_service() -> ReasoningTraceService:
    """Retourne l'instance singleton du ReasoningTraceService."""
    global _reasoning_trace_service
    if _reasoning_trace_service is None:
        _reasoning_trace_service = ReasoningTraceService()
    return _reasoning_trace_service


__all__ = [
    "ReasoningSupport",
    "ReasoningStep",
    "ReasoningTrace",
    "ReasoningTraceService",
    "get_reasoning_trace_service",
    "build_reasoning_trace_sync",
]
