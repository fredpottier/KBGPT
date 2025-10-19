# Phase 2 OSMOSE - LLM-First Relation Extraction
# Architecture robuste basée sur gpt-4o-mini

import logging
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import uuid

from knowbase.relations.types import (
    RelationType,
    TypedRelation,
    RelationMetadata,
    ExtractionMethod,
    RelationStrength,
    RelationStatus
)
from knowbase.common.llm_router import LLMRouter

logger = logging.getLogger(__name__)


# Prompt optimisé pour gpt-4o-mini (extraction batch relations)
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
    """

    def __init__(
        self,
        llm_router: Optional[LLMRouter] = None,
        model: str = "gpt-4o-mini",
        max_context_chars: int = 3000,
        co_occurrence_window: int = 150
    ):
        """
        Initialise LLM extractor.

        Args:
            llm_router: Router LLM (default: nouveau instance)
            model: Modèle à utiliser (default: gpt-4o-mini - bon rapport qualité/prix)
            max_context_chars: Taille max contexte envoyé au LLM
            co_occurrence_window: Fenêtre caractères pour co-occurrence
        """
        self.llm_router = llm_router or LLMRouter()
        self.model = model
        self.max_context_chars = max_context_chars
        self.co_occurrence_window = co_occurrence_window

        logger.info(
            f"[OSMOSE:LLMRelationExtractor] Initialized "
            f"(model={model}, max_context={max_context_chars})"
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

        # Étape 3: LLM extraction par chunk
        all_relations = []
        for chunk_idx, chunk_data in enumerate(text_chunks):
            logger.info(
                f"[OSMOSE:LLMRelationExtractor] Processing chunk {chunk_idx + 1}/{len(text_chunks)} "
                f"({len(chunk_data['text'])} chars, {len(chunk_data['concepts'])} concepts)"
            )

            chunk_relations = self._extract_from_chunk(
                chunk_data=chunk_data,
                document_id=document_id,
                document_name=document_name,
                chunk_ids=chunk_ids
            )

            all_relations.extend(chunk_relations)

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
            # Chercher canonical_name
            canonical = concept["canonical_name"].lower()
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

                # Vérifier que ce sont des concepts différents
                if mention_a["concept"]["concept_id"] != mention_b["concept"]["concept_id"]:
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
        unique_pairs = []
        seen = set()
        for concept_a, concept_b, context in pairs:
            pair_key = tuple(sorted([concept_a["concept_id"], concept_b["concept_id"]]))
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

        # Formater concepts pour prompt
        concepts_list = "\n".join([
            f"- {c['concept_id']}: {c['canonical_name']} ({c.get('concept_type', 'UNKNOWN')})"
            for c in chunk_concepts
        ])

        # Construire prompt
        prompt = RELATION_EXTRACTION_PROMPT.format(
            full_text_excerpt=chunk_text,
            concepts_list=concepts_list
        )

        # Appel LLM
        try:
            response = self.llm_router.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.1,  # Bas pour cohérence
                response_format={"type": "json_object"}  # Force JSON
            )

            response_text = response.choices[0].message.content

            # Parser JSON response
            relations_data = json.loads(response_text)

            # Si LLM retourne objet avec clé "relations"
            if isinstance(relations_data, dict) and "relations" in relations_data:
                relations_data = relations_data["relations"]

            # Créer TypedRelation pour chaque relation
            relations = []
            for rel_data in relations_data:
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
                f"from chunk"
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
