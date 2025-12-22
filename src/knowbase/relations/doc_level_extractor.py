"""
OSMOSE Phase 2.9.4 - Document-Level Relation Extractor

Extrait les relations cross-segment pour les concepts de haute qualité
qui sont isolés après la passe segment-level.

Architecture:
- Input: Concepts Bucket 3 (high quality, isolated)
- Output: Relations cross-segment uniquement
- Principe: Zéro redondance, zéro inférence gratuite

Améliorations ChatGPT v2:
- Anti-doublon explicite (existing relations in prompt + dedup code)
- Evidence windows ciblées autour des concepts
- Prédicat DEFINES ajouté
- Filtrage structurel strict (Article/Annex/Chapter)
- Batching intelligent par centralité
- Limite RELATES_TO à 20%
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import Counter

logger = logging.getLogger(__name__)


# Patterns pour détecter concepts structurels (à exclure)
STRUCTURAL_PATTERNS = [
    r"\bArticle\s+\d+",
    r"\bAnnex(es?)?\s+[IVX\d]+",
    r"\bChapter\s+[IVX\d]+",
    r"\bSection\s+\d+",
    r"\bRecital[s]?\s+\d+",
    r"\(\d+\)\s*\([a-z]\)",  # (1)(a) style references
]
STRUCTURAL_REGEX = re.compile("|".join(STRUCTURAL_PATTERNS), re.IGNORECASE)


@dataclass
class DocLevelRelation:
    """Relation extraite au niveau document."""
    subject_concept_id: str
    object_concept_id: str
    predicate: str
    confidence: float
    evidence: str
    subject_label: str = ""
    object_label: str = ""


@dataclass
class DocLevelExtractionResult:
    """Résultat de l'extraction doc-level."""
    relations: List[DocLevelRelation] = field(default_factory=list)
    concepts_processed: int = 0
    concepts_connected: int = 0
    duplicates_filtered: int = 0
    relates_to_capped: int = 0


# Prompt system pour extraction doc-level (ChatGPT optimized v2)
DOC_LEVEL_SYSTEM_PROMPT = """You are OSMOSE Document-Level Relation Extractor.

Your task is to extract ONLY cross-segment factual relations between the provided concepts.
A cross-segment relation is a relation that cannot be reliably extracted from a single local segment,
but becomes explicit when considering the document as a whole.

You must be strict and conservative.
Do NOT infer, generalize, or complete missing logic.
If a relation is not clearly supported by the document, do not return it.

CONCEPT SCOPE:
You may ONLY use the concepts listed below.
Do NOT invent new concepts.
Do NOT use structural references (articles, chapters, annexes) as subjects or objects.

ALLOWED RELATION TYPES (use these exact labels, prefer specific over generic):
DEFINES - subject defines/specifies object
REQUIRES - subject requires object
DEPENDS_ON - subject depends on object
ENABLES - subject enables/allows object
PREVENTS - subject prevents/prohibits object
CAUSES - subject causes object
AFFECTS - subject affects/impacts object
HAS_PROPERTY - subject has property object
APPLIES_TO - subject applies to object
RELATES_TO - generic relation (use ONLY if no specific type fits, max 20% of output)

EXTRACTION RULES:
- Extract ONLY relations that link concepts which are NOT typically co-present in a single segment.
- DO NOT repeat relations already listed in EXISTING_RELATIONS below.
- Each relation must be explicitly supported by the document.
- Each relation MUST include a short evidence snippet (verbatim or near-verbatim from document).
- Confidence must be >= 0.85. Otherwise, omit the relation.
- Prefer specific predicates. Limit RELATES_TO to exceptional cases.

OUTPUT FORMAT:
Return ONLY valid JSON. No markdown, no commentary.

{
  "relations": [
    {
      "subject_id": "c42",
      "predicate": "REQUIRES",
      "object_id": "c77",
      "confidence": 0.92,
      "evidence": "short supporting excerpt from the document"
    }
  ]
}"""


DOC_LEVEL_USER_PROMPT_TEMPLATE = """Extract cross-segment relations between the following concepts.

CONCEPTS (Bucket 3 - high quality, currently isolated):
{concepts_json}

EXISTING_RELATIONS (segment-level, DO NOT repeat these):
{existing_relations}

EVIDENCE WINDOWS (text excerpts containing the concepts):
{evidence_windows}

Return ONLY relations that are:
1. Explicitly supported by the evidence windows
2. NOT already in EXISTING_RELATIONS
3. Cross-segment (concepts not typically co-present locally)

If no valid cross-segment relations exist, return: {{"relations": []}}"""


class DocLevelRelationExtractor:
    """
    Extracteur de relations au niveau document.

    Cible uniquement les concepts Bucket 3 (haute qualité, isolés)
    pour établir des relations cross-segment.

    Améliorations v2:
    - Anti-doublon explicite
    - Evidence windows ciblées
    - Filtrage structurel
    - Batching par centralité
    - Limite RELATES_TO
    """

    def __init__(
        self,
        llm_router: Any = None,
        model: str = "gpt-4o-mini",
        min_confidence: float = 0.85,
        max_concepts_per_batch: int = 40,
        evidence_window_chars: int = 600,
        max_evidence_windows: int = 25,
        relates_to_max_ratio: float = 0.20
    ):
        """
        Initialise l'extracteur doc-level.

        Args:
            llm_router: Router LLM pour appels API
            model: Modèle à utiliser
            min_confidence: Seuil de confiance minimum
            max_concepts_per_batch: Max concepts par batch LLM
            evidence_window_chars: Taille fenêtre autour des mentions (±chars)
            max_evidence_windows: Nombre max de fenêtres d'évidence
            relates_to_max_ratio: Ratio max de RELATES_TO (0.20 = 20%)
        """
        self.llm_router = llm_router
        self.model = model
        self.min_confidence = min_confidence
        self.max_concepts_per_batch = max_concepts_per_batch
        self.evidence_window_chars = evidence_window_chars
        self.max_evidence_windows = max_evidence_windows
        self.relates_to_max_ratio = relates_to_max_ratio

        # Cache pour déduplication
        self._seen_relation_keys: Set[str] = set()

        logger.info(
            f"[DOC_LEVEL] Initialized DocLevelRelationExtractor "
            f"(model={model}, min_confidence={min_confidence}, "
            f"evidence_window={evidence_window_chars}chars)"
        )

    def identify_bucket3_concepts(
        self,
        all_concepts: List[Dict[str, Any]],
        existing_relations: List[Dict[str, Any]],
        quality_threshold: float = 0.9,
        allowed_types: List[str] = None,
        document_text: str = ""
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Identifie les concepts Bucket 3 (haute qualité, isolés).

        Args:
            all_concepts: Tous les concepts du document
            existing_relations: Relations déjà extraites (segment-level)
            quality_threshold: Seuil de qualité minimum
            allowed_types: Types autorisés (entity, role, standard par défaut)
            document_text: Texte du document (pour calcul fréquence)

        Returns:
            Tuple (concepts Bucket 3 triés par centralité, existing_relations formatées)
        """
        if allowed_types is None:
            allowed_types = ["entity", "role", "standard"]

        # Collecter les IDs des concepts déjà connectés
        connected_ids = set()
        existing_rel_strings = []

        for rel in existing_relations:
            if isinstance(rel, dict):
                subj = rel.get("subject_concept_id", "")
                obj = rel.get("object_concept_id", "")
                pred = rel.get("predicate_raw", "") or rel.get("predicate", "")
            else:
                subj = getattr(rel, "subject_concept_id", "")
                obj = getattr(rel, "object_concept_id", "")
                pred = getattr(rel, "predicate_raw", "") or getattr(rel, "predicate", "")

            connected_ids.add(subj)
            connected_ids.add(obj)

            # Format compact pour le prompt
            if subj and obj and pred:
                existing_rel_strings.append(f"{subj[:8]}..{pred[:20]}..{obj[:8]}")

        # Calculer fréquence dans le document (pour tri par centralité)
        concept_frequency = {}
        if document_text:
            doc_lower = document_text.lower()
            for concept in all_concepts:
                name = (concept.get("canonical_name") or concept.get("name", "")).lower()
                if name and len(name) > 3:
                    concept_frequency[concept.get("canonical_id") or concept.get("concept_id", "")] = \
                        doc_lower.count(name)

        # Filtrer pour Bucket 3
        bucket3 = []
        filtered_structural = 0

        for concept in all_concepts:
            concept_id = concept.get("canonical_id") or concept.get("concept_id", "")
            quality = concept.get("quality_score", 0.0)
            concept_type = concept.get("concept_type", "").lower()
            name = concept.get("canonical_name") or concept.get("name", "")

            # Filtrage structurel strict (Article X, Annex Y, etc.)
            if STRUCTURAL_REGEX.search(name):
                filtered_structural += 1
                continue

            # Critères Bucket 3
            is_isolated = concept_id not in connected_ids
            is_high_quality = quality >= quality_threshold
            # Accepter si type est dans allowed_types OU si type est None/vide (pas de classification)
            is_allowed_type = concept_type in allowed_types or not concept_type

            if is_isolated and is_high_quality and is_allowed_type:
                # Ajouter score de centralité pour tri
                concept["_centrality_score"] = (
                    concept_frequency.get(concept_id, 0) * 0.5 +
                    quality * 100
                )
                bucket3.append(concept)

        # Trier par centralité (fréquence + qualité)
        bucket3.sort(key=lambda c: c.get("_centrality_score", 0), reverse=True)

        logger.info(
            f"[DOC_LEVEL] Identified {len(bucket3)} Bucket 3 concepts "
            f"(isolated, quality>={quality_threshold}, types={allowed_types}, "
            f"structural_filtered={filtered_structural})"
        )

        return bucket3, existing_rel_strings[:50]  # Limiter à 50 relations existantes

    def extract_doc_level_relations(
        self,
        bucket3_concepts: List[Dict[str, Any]],
        document_text: str,
        document_id: str,
        existing_relations: List[str] = None
    ) -> DocLevelExtractionResult:
        """
        Extrait les relations doc-level pour les concepts Bucket 3.

        Args:
            bucket3_concepts: Concepts Bucket 3 à connecter (triés par centralité)
            document_text: Texte complet du document
            document_id: ID du document
            existing_relations: Relations existantes formatées (pour anti-doublon)

        Returns:
            DocLevelExtractionResult avec relations cross-segment
        """
        if not bucket3_concepts:
            logger.info("[DOC_LEVEL] No Bucket 3 concepts to process")
            return DocLevelExtractionResult()

        if not self.llm_router:
            logger.warning("[DOC_LEVEL] No LLM router configured")
            return DocLevelExtractionResult(concepts_processed=len(bucket3_concepts))

        existing_relations = existing_relations or []

        # Reset cache de déduplication pour ce document
        self._seen_relation_keys.clear()

        # Préparer liste concepts pour le prompt (triés par centralité)
        concepts_for_prompt = [
            {
                "id": f"c{i+1}",
                "label": c.get("canonical_name") or c.get("name", ""),
                "type": c.get("concept_type", "unknown"),
                "original_id": c.get("canonical_id") or c.get("concept_id", "")
            }
            for i, c in enumerate(bucket3_concepts[:self.max_concepts_per_batch])
        ]

        # Mapping idx -> original_id/label
        idx_to_id = {c["id"]: c["original_id"] for c in concepts_for_prompt}
        idx_to_label = {c["id"]: c["label"] for c in concepts_for_prompt}

        # Créer evidence windows ciblées
        evidence_windows = self._create_evidence_windows(
            document_text,
            [c["label"] for c in concepts_for_prompt]
        )

        # Construire prompt
        concepts_json = json.dumps(
            [{"id": c["id"], "label": c["label"], "type": c["type"]} for c in concepts_for_prompt],
            ensure_ascii=False,
            indent=2
        )

        existing_rel_str = "\n".join(existing_relations[:30]) if existing_relations else "(none)"

        user_prompt = DOC_LEVEL_USER_PROMPT_TEMPLATE.format(
            concepts_json=concepts_json,
            existing_relations=existing_rel_str,
            evidence_windows=evidence_windows[:12000]  # Limiter taille
        )

        logger.info(
            f"[DOC_LEVEL] Extracting relations for {len(concepts_for_prompt)} concepts "
            f"(doc_id={document_id}, evidence_windows={len(evidence_windows)}chars)"
        )

        try:
            # Appel LLM via le router avec le bon TaskType
            from knowbase.common.llm_router import TaskType

            response = self.llm_router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[
                    {"role": "system", "content": DOC_LEVEL_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=4000
            )

            # Parser réponse avec déduplication et validation
            relations, stats = self._parse_and_validate_response(
                response,
                idx_to_id,
                idx_to_label,
                document_text
            )

            # Calculer concepts connectés
            connected_ids = set()
            for rel in relations:
                connected_ids.add(rel.subject_concept_id)
                connected_ids.add(rel.object_concept_id)

            result = DocLevelExtractionResult(
                relations=relations,
                concepts_processed=len(concepts_for_prompt),
                concepts_connected=len(connected_ids),
                duplicates_filtered=stats.get("duplicates", 0),
                relates_to_capped=stats.get("relates_to_capped", 0)
            )

            logger.info(
                f"[DOC_LEVEL] Extracted {len(relations)} cross-segment relations, "
                f"connected {result.concepts_connected}/{result.concepts_processed} concepts "
                f"(dedup={result.duplicates_filtered}, relates_to_cap={result.relates_to_capped})"
            )

            return result

        except Exception as e:
            logger.error(f"[DOC_LEVEL] Extraction failed: {e}")
            return DocLevelExtractionResult(concepts_processed=len(concepts_for_prompt))

    def _create_evidence_windows(
        self,
        document_text: str,
        concept_labels: List[str]
    ) -> str:
        """
        Crée des fenêtres d'évidence ciblées autour des mentions de concepts.

        Stratégie: Pour chaque concept, extraire ±N chars autour de ses occurrences.
        Puis dédupliquer et merger les fenêtres qui se chevauchent.
        """
        if not document_text or not concept_labels:
            return "[No evidence windows available]"

        windows = []
        doc_lower = document_text.lower()
        window_size = self.evidence_window_chars

        # Collecter positions de toutes les mentions
        mention_positions = []
        for label in concept_labels:
            label_lower = label.lower()
            if len(label_lower) < 4:
                continue

            pos = 0
            while True:
                pos = doc_lower.find(label_lower, pos)
                if pos == -1:
                    break
                mention_positions.append((pos, label))
                pos += 1

        # Trier par position
        mention_positions.sort(key=lambda x: x[0])

        # Créer fenêtres et merger celles qui se chevauchent
        merged_windows = []
        for pos, label in mention_positions[:self.max_evidence_windows * 2]:
            start = max(0, pos - window_size)
            end = min(len(document_text), pos + len(label) + window_size)

            # Vérifier chevauchement avec dernière fenêtre
            if merged_windows and start < merged_windows[-1][1]:
                # Étendre la dernière fenêtre
                merged_windows[-1] = (merged_windows[-1][0], max(end, merged_windows[-1][1]))
            else:
                merged_windows.append((start, end))

            if len(merged_windows) >= self.max_evidence_windows:
                break

        # Extraire texte des fenêtres
        for i, (start, end) in enumerate(merged_windows):
            window_text = document_text[start:end].strip()
            # Nettoyer début/fin (éviter mots coupés)
            if start > 0:
                first_space = window_text.find(' ')
                if first_space > 0 and first_space < 50:
                    window_text = window_text[first_space + 1:]
            if end < len(document_text):
                last_space = window_text.rfind(' ')
                if last_space > len(window_text) - 50:
                    window_text = window_text[:last_space]

            windows.append(f"[WINDOW {i+1}]\n{window_text}")

        if not windows:
            # Fallback: début + fin du document
            return f"[DOCUMENT START]\n{document_text[:3000]}\n\n[DOCUMENT END]\n{document_text[-3000:]}"

        return "\n\n".join(windows)

    def _parse_and_validate_response(
        self,
        response: str,
        idx_to_id: Dict[str, str],
        idx_to_label: Dict[str, str],
        document_text: str
    ) -> Tuple[List[DocLevelRelation], Dict[str, int]]:
        """
        Parse la réponse LLM avec validation et déduplication.

        Returns:
            Tuple (relations validées, stats)
        """
        stats = {"duplicates": 0, "relates_to_capped": 0, "evidence_weak": 0}

        try:
            # Nettoyer markdown si présent
            response_text = response.strip()
            if response_text.startswith("```"):
                response_text = re.sub(r"```json?\n?", "", response_text)
                response_text = re.sub(r"\n?```$", "", response_text)

            logger.debug(f"[DOC_LEVEL] Raw response (first 500 chars): {response_text[:500]}")

            parsed = json.loads(response_text)
            relations_data = parsed.get("relations", [])

            logger.debug(f"[DOC_LEVEL] Parsed {len(relations_data)} raw relations from LLM")

            relations = []
            relates_to_count = 0
            max_relates_to = max(1, int(len(relations_data) * self.relates_to_max_ratio))

            for item in relations_data:
                subject_idx = item.get("subject_id", "")
                object_idx = item.get("object_id", "")
                predicate = item.get("predicate", "RELATES_TO")
                confidence = float(item.get("confidence", 0.0))
                evidence = item.get("evidence", "")

                logger.debug(
                    f"[DOC_LEVEL] Raw relation: {subject_idx} --{predicate}--> {object_idx} "
                    f"(conf={confidence})"
                )

                # Filtrer par confiance
                if confidence < self.min_confidence:
                    logger.debug(f"[DOC_LEVEL] Filtered: confidence {confidence} < {self.min_confidence}")
                    continue

                # Résoudre IDs
                subject_id = idx_to_id.get(subject_idx)
                object_id = idx_to_id.get(object_idx)

                if not subject_id or not object_id:
                    logger.debug(
                        f"[DOC_LEVEL] Filtered: unknown idx {subject_idx}->{object_idx}"
                    )
                    continue

                # Déduplication par clé canonique
                rel_key = f"{subject_id}|{predicate}|{object_id}"
                if rel_key in self._seen_relation_keys:
                    stats["duplicates"] += 1
                    continue
                self._seen_relation_keys.add(rel_key)

                # Limite RELATES_TO
                if predicate == "RELATES_TO":
                    if relates_to_count >= max_relates_to:
                        stats["relates_to_capped"] += 1
                        continue
                    relates_to_count += 1

                # Validation evidence (au moins quelques mots doivent matcher)
                if evidence and document_text:
                    evidence_words = set(evidence.lower().split())
                    doc_words = set(document_text.lower().split())
                    common_words = evidence_words & doc_words
                    # Au moins 30% des mots de l'evidence doivent être dans le doc
                    if len(evidence_words) > 3 and len(common_words) < len(evidence_words) * 0.3:
                        stats["evidence_weak"] += 1
                        logger.debug(f"[DOC_LEVEL] Weak evidence for {subject_idx}->{object_idx}")
                        # On garde quand même mais avec flag potentiel

                relations.append(DocLevelRelation(
                    subject_concept_id=subject_id,
                    object_concept_id=object_id,
                    predicate=predicate,
                    confidence=confidence,
                    evidence=evidence[:500],
                    subject_label=idx_to_label.get(subject_idx, ""),
                    object_label=idx_to_label.get(object_idx, "")
                ))

            return relations, stats

        except json.JSONDecodeError as e:
            logger.error(f"[DOC_LEVEL] JSON parse error: {e}")
            return [], stats
