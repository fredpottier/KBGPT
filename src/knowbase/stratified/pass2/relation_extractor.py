"""
OSMOSE Pipeline V2 - Pass 2 Relation Extractor
===============================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Extraction des relations inter-concepts:
- Types: REQUIRES, ENABLES, CONSTRAINS, DEPENDS_ON, RELATED_TO
- Maximum 3 relations par concept (garde-fou)
- Evidence rattachée à chaque relation

Pass 2 enrichit le graphe sémantique créé par Pass 1.
"""

import json
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import yaml
import uuid

from knowbase.stratified.models import (
    Concept,
    Information,
)

logger = logging.getLogger(__name__)


# ============================================================================
# TYPES DE RELATIONS
# ============================================================================

class RelationType:
    """Types de relations entre concepts."""
    REQUIRES = "REQUIRES"           # A nécessite B
    ENABLES = "ENABLES"             # A permet B
    CONSTRAINS = "CONSTRAINS"       # A contraint B
    DEPENDS_ON = "DEPENDS_ON"       # A dépend de B
    RELATED_TO = "RELATED_TO"       # A est lié à B (générique)
    SPECIALIZES = "SPECIALIZES"     # A est une spécialisation de B
    PART_OF = "PART_OF"             # A fait partie de B
    CONTRADICTS = "CONTRADICTS"     # A contredit B


VALID_RELATION_TYPES = [
    RelationType.REQUIRES,
    RelationType.ENABLES,
    RelationType.CONSTRAINS,
    RelationType.DEPENDS_ON,
    RelationType.RELATED_TO,
    RelationType.SPECIALIZES,
    RelationType.PART_OF,
    RelationType.CONTRADICTS,
]


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ConceptRelation:
    """Relation entre deux concepts."""
    relation_id: str
    source_concept_id: str
    target_concept_id: str
    relation_type: str
    confidence: float
    evidence_info_ids: List[str] = field(default_factory=list)
    justification: str = ""

    def __post_init__(self):
        if not self.relation_id:
            self.relation_id = f"rel_{uuid.uuid4().hex[:8]}"


@dataclass
class Pass2Stats:
    """Statistiques Pass 2."""
    concepts_processed: int = 0
    relations_extracted: int = 0
    relations_filtered: int = 0  # Rejetées par garde-fou
    avg_relations_per_concept: float = 0.0


@dataclass
class Pass2Result:
    """Résultat Pass 2."""
    doc_id: str
    relations: List[ConceptRelation] = field(default_factory=list)
    stats: Pass2Stats = field(default_factory=Pass2Stats)


# ============================================================================
# EXTRACTOR
# ============================================================================

class RelationExtractorV2:
    """
    Extracteur de relations inter-concepts pour Pipeline V2.

    GARDE-FOU: Maximum 3 relations par concept source.
    Évite l'explosion combinatoire.
    """

    MAX_RELATIONS_PER_CONCEPT = 3

    def __init__(
        self,
        llm_client=None,
        prompts_path: Optional[Path] = None,
        allow_fallback: bool = False
    ):
        """
        Args:
            llm_client: Client LLM compatible
            prompts_path: Chemin vers prompts YAML
            allow_fallback: Autorise fallback heuristique
        """
        self.llm_client = llm_client
        self.prompts = self._load_prompts(prompts_path)
        self.allow_fallback = allow_fallback

    def _load_prompts(self, prompts_path: Optional[Path]) -> Dict:
        """Charge les prompts depuis le fichier YAML."""
        if prompts_path is None:
            prompts_path = Path(__file__).parent.parent / "prompts" / "pass2_prompts.yaml"

        if not prompts_path.exists():
            return {}

        with open(prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    def extract_relations(
        self,
        doc_id: str,
        concepts: List[Concept],
        informations: List[Information]
    ) -> Pass2Result:
        """
        Extrait les relations entre concepts.

        Args:
            doc_id: Identifiant du document
            concepts: Liste des concepts (de Pass 1)
            informations: Liste des informations (de Pass 1)

        Returns:
            Pass2Result avec les relations extraites
        """
        if not concepts:
            return Pass2Result(doc_id=doc_id)

        logger.info(f"[OSMOSE:Pass2] Extraction relations pour {len(concepts)} concepts")

        # Construire l'index concept_id → informations
        concept_to_infos = self._build_concept_info_index(concepts, informations)

        # Extraire les relations
        if self.llm_client:
            all_relations = self._extract_via_llm(concepts, informations, concept_to_infos)
        elif self.allow_fallback:
            logger.warning("[OSMOSE:Pass2] Mode fallback - résultats non fiables")
            all_relations = self._extract_heuristic(concepts, informations, concept_to_infos)
        else:
            raise RuntimeError("LLM non disponible et fallback non autorisé")

        # Appliquer garde-fou: max 3 relations par concept source
        filtered_relations, rejected_count = self._apply_relation_limit(all_relations)

        # Calculer stats
        stats = Pass2Stats(
            concepts_processed=len(concepts),
            relations_extracted=len(filtered_relations),
            relations_filtered=rejected_count,
            avg_relations_per_concept=len(filtered_relations) / len(concepts) if concepts else 0
        )

        logger.info(
            f"[OSMOSE:Pass2] {stats.relations_extracted} relations extraites "
            f"({stats.relations_filtered} filtrées par garde-fou)"
        )

        return Pass2Result(
            doc_id=doc_id,
            relations=filtered_relations,
            stats=stats
        )

    def _build_concept_info_index(
        self,
        concepts: List[Concept],
        informations: List[Information]
    ) -> Dict[str, List[Information]]:
        """Construit l'index concept_id → informations."""
        index = {c.concept_id: [] for c in concepts}
        for info in informations:
            if info.concept_id in index:
                index[info.concept_id].append(info)
        return index

    # Nombre max de concepts par batch LLM (évite prompt trop long pour Qwen 14B)
    BATCH_SIZE = 15

    def _extract_via_llm(
        self,
        concepts: List[Concept],
        informations: List[Information],
        concept_to_infos: Dict[str, List[Information]]
    ) -> List[ConceptRelation]:
        """Extraction via LLM par batches de concepts."""
        # Filtrer les concepts sans informations (inutiles pour les relations)
        active_concepts = [c for c in concepts if concept_to_infos.get(c.concept_id)]
        # Exclure le SINK
        active_concepts = [c for c in active_concepts if c.role.value != "SINK"]

        if not active_concepts:
            logger.warning("[OSMOSE:Pass2] Aucun concept actif avec informations")
            return self._extract_heuristic(concepts, informations, concept_to_infos)

        logger.info(
            f"[OSMOSE:Pass2] {len(active_concepts)} concepts actifs "
            f"(sur {len(concepts)} total, excl. SINK et vides)"
        )

        # Découper en batches
        all_relations: List[ConceptRelation] = []
        n_batches = (len(active_concepts) + self.BATCH_SIZE - 1) // self.BATCH_SIZE

        for batch_idx in range(n_batches):
            start = batch_idx * self.BATCH_SIZE
            end = min(start + self.BATCH_SIZE, len(active_concepts))
            batch_concepts = active_concepts[start:end]

            # Inclure aussi les concepts hors-batch comme cibles potentielles
            # (on ne les détaille pas, juste leurs noms)
            other_concepts = [c for c in active_concepts if c not in batch_concepts]

            relations = self._extract_batch_via_llm(
                batch_concepts, other_concepts, informations, concept_to_infos
            )
            all_relations.extend(relations)

            logger.info(
                f"[OSMOSE:Pass2] Batch {batch_idx + 1}/{n_batches}: "
                f"{len(relations)} relations extraites"
            )

        return all_relations

    def _extract_batch_via_llm(
        self,
        batch_concepts: List[Concept],
        other_concepts: List[Concept],
        informations: List[Information],
        concept_to_infos: Dict[str, List[Information]]
    ) -> List[ConceptRelation]:
        """Extrait les relations pour un batch de concepts."""
        prompt_config = self.prompts.get("relation_extraction", {})
        system_prompt = prompt_config.get("system", self._default_system_prompt())

        # Formater les concepts du batch (détaillés)
        concepts_text = self._format_concepts_for_prompt(batch_concepts, concept_to_infos)

        # Ajouter les autres concepts comme cibles possibles (noms seulement)
        if other_concepts:
            other_names = "\n".join(
                f"  [{c.concept_id}] {c.name}" for c in other_concepts
            )
            concepts_text += f"\n\nOTHER CONCEPTS (available as relation targets):\n{other_names}\n"

        user_prompt = f"""Identify the semantic RELATIONS between these concepts.

DETAILED CONCEPTS (with informations):
{concepts_text}

VALID RELATION TYPES: {", ".join(VALID_RELATION_TYPES)}

RULES:
- Only create relations with clear evidence from the informations
- Maximum 3 relations per source concept
- Source MUST be one of the detailed concepts above
- Target can be any concept (detailed or other)
- Include a brief justification for each relation

Reply ONLY with this JSON:
```json
{{
  "relations": [
    {{
      "source_concept_id": "concept_xxx",
      "target_concept_id": "concept_yyy",
      "relation_type": "REQUIRES",
      "confidence": 0.85,
      "justification": "Why this relation exists"
    }}
  ]
}}
```"""

        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2000
            )

            if not response or not response.strip():
                logger.warning("[OSMOSE:Pass2] Réponse LLM vide pour ce batch")
                return []

            return self._parse_relations_response(response, batch_concepts + other_concepts, informations)
        except Exception as e:
            logger.warning(f"[OSMOSE:Pass2] Extraction LLM échouée pour batch: {e}")
            return []

    def _extract_heuristic(
        self,
        concepts: List[Concept],
        informations: List[Information],
        concept_to_infos: Dict[str, List[Information]]
    ) -> List[ConceptRelation]:
        """Extraction heuristique sans LLM."""
        relations = []
        concept_ids = [c.concept_id for c in concepts]

        for concept in concepts:
            infos = concept_to_infos.get(concept.concept_id, [])

            for info in infos:
                # Chercher des mentions d'autres concepts dans les informations
                for other_concept in concepts:
                    if other_concept.concept_id == concept.concept_id:
                        continue

                    # Vérifier si l'autre concept est mentionné
                    if self._concept_mentioned_in_text(other_concept, info.text):
                        # Inférer le type de relation
                        rel_type = self._infer_relation_type(info.text, concept, other_concept)

                        relations.append(ConceptRelation(
                            relation_id=f"rel_{uuid.uuid4().hex[:8]}",
                            source_concept_id=concept.concept_id,
                            target_concept_id=other_concept.concept_id,
                            relation_type=rel_type,
                            confidence=0.6,
                            evidence_info_ids=[info.info_id],
                            justification=f"Co-occurrence dans: {info.text[:100]}..."
                        ))

        return relations

    def _concept_mentioned_in_text(self, concept: Concept, text: str) -> bool:
        """Vérifie si un concept est mentionné dans le texte."""
        text_lower = text.lower()

        # Vérifier le nom et les variantes
        names_to_check = [concept.name] + concept.variants
        for name in names_to_check:
            if name.lower() in text_lower:
                return True

        return False

    def _infer_relation_type(
        self,
        text: str,
        source: Concept,
        target: Concept
    ) -> str:
        """Infère le type de relation depuis le contexte textuel."""
        text_lower = text.lower()

        # Patterns pour chaque type
        if any(p in text_lower for p in ['requires', 'nécessite', 'need', 'must have']):
            return RelationType.REQUIRES
        if any(p in text_lower for p in ['enables', 'permet', 'allows', 'makes possible']):
            return RelationType.ENABLES
        if any(p in text_lower for p in ['constrains', 'limits', 'restricts', 'contraint']):
            return RelationType.CONSTRAINS
        if any(p in text_lower for p in ['depends on', 'relies on', 'dépend de']):
            return RelationType.DEPENDS_ON
        if any(p in text_lower for p in ['part of', 'component of', 'partie de']):
            return RelationType.PART_OF
        if any(p in text_lower for p in ['type of', 'kind of', 'specialization', 'spécialisation']):
            return RelationType.SPECIALIZES
        if any(p in text_lower for p in ['contradicts', 'conflicts with', 'contredit']):
            return RelationType.CONTRADICTS

        return RelationType.RELATED_TO

    def _apply_relation_limit(
        self,
        relations: List[ConceptRelation]
    ) -> Tuple[List[ConceptRelation], int]:
        """
        Applique le garde-fou: max 3 relations par concept source.

        Garde les relations avec la plus haute confiance.
        """
        # Grouper par source
        by_source: Dict[str, List[ConceptRelation]] = {}
        for rel in relations:
            if rel.source_concept_id not in by_source:
                by_source[rel.source_concept_id] = []
            by_source[rel.source_concept_id].append(rel)

        filtered = []
        rejected_count = 0

        for source_id, source_relations in by_source.items():
            # Trier par confiance décroissante
            sorted_rels = sorted(source_relations, key=lambda r: -r.confidence)

            # Garder les N premières
            kept = sorted_rels[:self.MAX_RELATIONS_PER_CONCEPT]
            rejected = sorted_rels[self.MAX_RELATIONS_PER_CONCEPT:]

            filtered.extend(kept)
            rejected_count += len(rejected)

        return filtered, rejected_count

    def _format_concepts_for_prompt(
        self,
        concepts: List[Concept],
        concept_to_infos: Dict[str, List[Information]]
    ) -> str:
        """Formate les concepts pour le prompt LLM."""
        lines = []
        for concept in concepts:
            infos = concept_to_infos.get(concept.concept_id, [])
            info_texts = [f"  - {i.text[:150]}..." for i in infos[:3]]
            info_section = "\n".join(info_texts) if info_texts else "  (aucune information)"

            lines.append(f"""
[{concept.concept_id}] {concept.name} ({concept.role.value})
  Variantes: {', '.join(concept.variants) if concept.variants else 'aucune'}
  Informations associées:
{info_section}
""")
        return "\n".join(lines)

    def _parse_relations_response(
        self,
        response: str,
        concepts: List[Concept],
        informations: List[Information]
    ) -> List[ConceptRelation]:
        """Parse la réponse JSON du LLM."""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            relations = []

            concept_ids = {c.concept_id for c in concepts}
            info_ids = {i.info_id for i in informations}

            for r_data in data.get("relations", []):
                source_id = r_data.get("source_concept_id")
                target_id = r_data.get("target_concept_id")
                rel_type = r_data.get("relation_type", RelationType.RELATED_TO)

                # Valider
                if source_id not in concept_ids or target_id not in concept_ids:
                    continue
                if rel_type not in VALID_RELATION_TYPES:
                    rel_type = RelationType.RELATED_TO

                # Valider evidence
                evidence = r_data.get("evidence_info_ids", [])
                valid_evidence = [e for e in evidence if e in info_ids]

                relations.append(ConceptRelation(
                    relation_id=f"rel_{uuid.uuid4().hex[:8]}",
                    source_concept_id=source_id,
                    target_concept_id=target_id,
                    relation_type=rel_type,
                    confidence=r_data.get("confidence", 0.8),
                    evidence_info_ids=valid_evidence,
                    justification=r_data.get("justification", "")
                ))

            return relations

        except json.JSONDecodeError as e:
            logger.warning(f"[OSMOSE:Pass2] Parse JSON échoué: {e}")
            return []

    def _default_system_prompt(self) -> str:
        return """Expert relation extraction for OSMOSE knowledge system.
Identify semantic RELATIONS between concepts based on their associated informations.

VALID RELATION TYPES:
- REQUIRES: A needs B to function
- ENABLES: A makes B possible
- CONSTRAINS: A limits or restricts B
- DEPENDS_ON: A depends on B
- RELATED_TO: A is related to B (generic)
- SPECIALIZES: A is a specialization/type of B
- PART_OF: A is a component of B
- CONTRADICTS: A contradicts B

RULES:
- Each relation must be justified by information content
- Confidence >= 0.7 for explicit relations
- Confidence 0.5-0.7 for implicit relations
- Maximum 3 relations per source concept
- Prefer specific relation types over RELATED_TO
- Output ONLY valid JSON"""

    def _default_user_prompt(self) -> str:
        return """Identifie les relations entre ces concepts.

CONCEPTS ET INFORMATIONS ASSOCIÉES:
{concepts}

TYPES DE RELATIONS VALIDES: {relation_types}

Réponds avec ce JSON:
```json
{{
  "relations": [
    {{
      "source_concept_id": "concept_xxx",
      "target_concept_id": "concept_yyy",
      "relation_type": "REQUIRES|ENABLES|...",
      "confidence": 0.85,
      "evidence_info_ids": ["info_xxx"],
      "justification": "Pourquoi cette relation existe"
    }}
  ]
}}
```"""
