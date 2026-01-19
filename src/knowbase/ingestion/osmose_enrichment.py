"""
OSMOSE Enrichment - Context, Summary, Cross-Reference Methods.

Module extrait de osmose_agentique.py pour améliorer la modularité.
Contient les méthodes d'enrichissement et de contexte.

Author: OSMOSE Refactoring
Date: 2025-01-05
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Dict, List, Any, Optional, Tuple, TYPE_CHECKING, Union

import logging

from knowbase.common.llm_router import LLMRouter, get_llm_router, TaskType
from knowbase.extraction_v2.context.models import (
    DocumentContext,
    StructureHint,
    EntityHint,
    TemporalHint,
)

if TYPE_CHECKING:
    from knowbase.extraction_v2.context.models import DocContextFrame

logger = logging.getLogger(__name__)

# Cache global pour le contexte document (évite recalcul)
# Format: (summary, technical_density, document_context)
_document_context_cache: Dict[str, Tuple[str, float, DocumentContext]] = {}


def get_anchor_context_analyzer():
    """Lazy import du AnchorContextAnalyzer."""
    from knowbase.extraction_v2.context.anchor_context import get_anchor_context_analyzer
    return get_anchor_context_analyzer()


def get_domain_context_injector():
    """Lazy import du DomainContextInjector."""
    from knowbase.extraction_v2.context.domain_context_injector import get_domain_context_injector
    return get_domain_context_injector()


async def enrich_anchors_with_context(
    proto_concepts: List[Any],
    doc_context_frame: Optional["DocContextFrame"] = None,
) -> None:
    """
    Enrichit les anchors des ProtoConcepts avec contexte d'assertion.

    Applique l'analyse de contexte (polarity, scope, markers) sur chaque
    anchor et calcule le contexte agrégé du ProtoConcept.

    ADR: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - PR2

    Args:
        proto_concepts: Liste des ProtoConcepts à enrichir (modifiés in-place)
        doc_context_frame: Contexte documentaire (si disponible)
    """
    if not proto_concepts:
        return

    analyzer = get_anchor_context_analyzer()

    # Compteurs pour stats
    anchors_enriched = 0
    protos_with_context = 0

    for proto in proto_concepts:
        if not hasattr(proto, 'anchors') or not proto.anchors:
            continue

        # Analyser chaque anchor
        for anchor in proto.anchors:
            try:
                # Extraire le passage (surface_form) de l'anchor
                passage = getattr(anchor, 'surface_form', '')
                if not passage:
                    continue

                # Analyse sync (heuristiques uniquement pour Pass 1)
                anchor_context = analyzer.analyze_sync(
                    passage=passage,
                    doc_context=doc_context_frame,
                )

                # Enrichir l'anchor avec les résultats
                # (conversion vers les champs du schema Pydantic)
                anchor.polarity = anchor_context.polarity
                anchor.scope = anchor_context.scope
                anchor.local_markers = [
                    {"value": m.value, "evidence": m.evidence, "confidence": m.confidence}
                    for m in anchor_context.local_markers
                ]
                anchor.is_override = anchor_context.is_override
                anchor.qualifier_source = anchor_context.qualifier_source
                anchor.context_confidence = anchor_context.confidence

                anchors_enriched += 1

            except Exception as e:
                logger.debug(
                    f"[OSMOSE:PR2:Context] Failed to enrich anchor: {e}"
                )

        # Calculer le contexte agrégé du ProtoConcept
        if hasattr(proto, 'compute_context'):
            try:
                proto.context = proto.compute_context()
                protos_with_context += 1
            except Exception as e:
                logger.debug(
                    f"[OSMOSE:PR2:Context] Failed to compute proto context: {e}"
                )

    logger.info(
        f"[OSMOSE:PR2:Context] Enriched {anchors_enriched} anchors, "
        f"{protos_with_context} ProtoConcepts with aggregated context"
    )


def extract_document_metadata(full_text: str) -> Dict[str, Any]:
    """
    Extrait métadonnées basiques du document sans LLM.

    Phase 1.8: Extraction heuristique titre, headers, mots-clés.

    Args:
        full_text: Texte complet du document

    Returns:
        Dict avec title, headers, keywords
    """
    metadata: Dict[str, Any] = {
        "title": None,
        "headers": [],
        "keywords": []
    }

    lines = full_text.split("\n")
    non_empty_lines = [l.strip() for l in lines if l.strip()]

    # Heuristique titre: première ligne non-vide courte (<100 chars)
    if non_empty_lines:
        first_line = non_empty_lines[0]
        if len(first_line) < 100:
            metadata["title"] = first_line

    # Extraction headers via patterns (# Header, HEADER:, Header majuscule isolé)
    header_patterns = [
        r'^#{1,3}\s+(.+)$',  # Markdown headers
        r'^([A-Z][A-Z0-9\s]{2,50}):?\s*$',  # UPPERCASE headers
        r'^(\d+\.?\s+[A-Z].{5,80})$',  # Numbered headers
    ]

    for line in non_empty_lines[:50]:  # Limiter aux 50 premières lignes
        for pattern in header_patterns:
            match = re.match(pattern, line)
            if match:
                header = match.group(1).strip()
                if header and len(header) < 100 and header not in metadata["headers"]:
                    metadata["headers"].append(header)
                    if len(metadata["headers"]) >= 10:
                        break
        if len(metadata["headers"]) >= 10:
            break

    # Extraction mots-clés: termes SAP fréquents + noms propres capitalisés
    sap_keywords = set()

    # Pattern SAP: "SAP X", "S/4HANA", "BTP", etc.
    sap_pattern = r'\b(SAP\s+\w+(?:\s+\w+)?|S/4HANA(?:\s+Cloud)?|BTP|Fiori|HANA|SuccessFactors|Ariba|Concur)\b'
    for match in re.finditer(sap_pattern, full_text, re.IGNORECASE):
        term = match.group(1)
        if term:
            sap_keywords.add(term)

    # Pattern noms propres: mots capitalisés répétés
    proper_nouns = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', full_text)
    noun_counts = Counter(proper_nouns)

    # Garder les plus fréquents (>2 occurrences)
    for noun, count in noun_counts.most_common(20):
        if count > 2 and noun not in ["The", "This", "That", "These", "What", "How", "Where"]:
            sap_keywords.add(noun)

    metadata["keywords"] = list(sap_keywords)[:15]

    return metadata


async def generate_document_summary(
    document_id: str,
    full_text: str,
    llm_router: LLMRouter,
    max_length: int = 500
) -> Tuple[str, float, DocumentContext]:
    """
    Génère un résumé contextuel du document, évalue sa densité technique,
    et extrait les contraintes document-level pour filtrage des markers.

    Phase 1.8 Task T1.8.1.0: Document Context Global.
    Phase 1.8.2: Ajout technical_density_hint pour stratégie extraction domain-agnostic.
    ADR Document Context Markers: Ajout document_context constraints.

    Ce résumé est utilisé pour:
    - Désambiguïser les acronymes/abréviations
    - Préférer les noms complets officiels
    - Contexte domaine pour meilleure extraction
    - Filtrer les faux positifs markers via structure_hint
    - Renforcer la normalisation via entity_hints

    IMPORTANT (ADR):
    - Le LLM n'extrait PAS de markers, seulement des CONTRAINTES
    - Hiérarchie: MarkerMention > Normalization > DocumentContext
    - Safe-by-default: en cas de doute, confidence basse

    Args:
        document_id: ID unique pour cache
        full_text: Texte complet du document
        llm_router: Router LLM pour la génération
        max_length: Longueur max du résumé (caractères)

    Returns:
        Tuple (résumé contextuel, technical_density 0.0-1.0, document_context)
    """
    # Vérifier cache global
    cache_key = hashlib.md5(document_id.encode()).hexdigest()

    if cache_key in _document_context_cache:
        cached = _document_context_cache[cache_key]
        # Support ancien format (2-tuple) et nouveau format (3-tuple)
        if isinstance(cached, tuple):
            if len(cached) == 3:
                logger.info(f"[OSMOSE:Context] Cache hit for document {document_id[:20]}...")
                return cached
            elif len(cached) == 2:
                # Ancien format: ajouter DocumentContext vide
                return (cached[0], cached[1], DocumentContext.empty())

    logger.info(f"[OSMOSE:Context] Generating document context for {document_id[:20]}...")

    # Extraction métadonnées sans LLM
    metadata = extract_document_metadata(full_text)

    # Limiter texte envoyé au LLM (premiers 4000 chars + derniers 1000)
    text_sample = full_text[:4000]
    if len(full_text) > 5000:
        text_sample += "\n[...]\n" + full_text[-1000:]

    # Prompt enrichi avec document_context (ADR Document Context Markers)
    system_prompt = """You are a document analyst.

Your tasks:
1) Produce a concise summary (1-2 paragraphs, max 500 characters).
2) Estimate technical density (0.0-1.0).
3) Produce DOCUMENT CONTEXT CONSTRAINTS to help interpret locally-extracted markers.
   IMPORTANT: You do NOT create markers. You only provide constraints and hints.

For the summary, focus on:
- Main theme/topic
- Full official names of the dominant entities (products/systems/standards/regulations/orgs)
- Domain context

For document_context, provide:

A) structure_hint:
- Does the document use numbered headings/sections?
- What numbering patterns are present (e.g., "WORD+NUMBER", "1.2.3")?
- Confidence.

B) entity_hints:
- List up to 5 dominant entities that the document is mainly about.
- For each, provide:
  - label
  - type_hint: product|system|standard|regulation|org|other
  - confidence
  - evidence: "explicit" if clearly stated, otherwise "inferred"
- IMPORTANT: Do not fabricate versions or years.

C) temporal_hint:
- If an explicit publication/creation date is clearly stated, extract it.
- If not explicit, you may provide a weak inferred year with low confidence.
- Prefer "unknown" over guessing.

D) scope_hints:
- Generic deployment/variant cues (cloud/on-premise/edition/region) if explicitly mentioned.

Strict rules:
- Do NOT output "product_versions".
- Do NOT turn section numbers into versions.
- If the document has numbered sections, tokens like "PUBLIC 3" are likely headings, not versions.
- If unsure, set confidence low and/or return empty lists.

Output JSON only:
{
  "summary": "...",
  "technical_density": 0.X,
  "document_context": {
    "structure_hint": {
      "has_numbered_sections": true/false,
      "numbering_patterns": ["..."],
      "confidence": 0.X
    },
    "entity_hints": [
      {"label":"...", "type_hint":"...", "confidence":0.X, "evidence":"explicit|inferred"}
    ],
    "temporal_hint": {"explicit":"YYYY-MM|YYYY-Q#", "inferred":"YYYY", "confidence":0.X},
    "scope_hints": ["..."]
  }
}

Write the summary in the same language as the document."""

    # Injection du Domain Context si disponible
    try:
        injector = get_domain_context_injector()
        system_prompt = injector.inject_context(system_prompt, tenant_id="default")
        logger.info("[OSMOSE:Context] Domain Context injected into summary prompt")
    except Exception as e:
        logger.debug(f"[OSMOSE:Context] No Domain Context available: {e}")

    user_prompt = f"""Document metadata:
- Title: {metadata.get('title', 'Unknown')}
- Headers: {', '.join(metadata.get('headers', [])[:5])}
- Keywords detected: {', '.join(metadata.get('keywords', [])[:10])}

Document text sample:
{text_sample}

Analyze this document and provide JSON response:"""

    try:
        # Utiliser LONG_TEXT_SUMMARY pour ce type de tâche
        response = await llm_router.acomplete(
            task_type=TaskType.LONG_TEXT_SUMMARY,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=800  # Augmenté pour document_context
        )

        # Parser la réponse JSON
        technical_density = 0.5
        summary = response
        doc_context = DocumentContext.empty()

        try:
            # Chercher JSON complet dans la réponse (peut être multi-ligne)
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group(0))
                summary = data.get("summary", response)
                technical_density = float(data.get("technical_density", 0.5))
                technical_density = max(0.0, min(1.0, technical_density))

                # Parser document_context si présent
                if "document_context" in data:
                    doc_context = _parse_document_context(data["document_context"])
                    logger.info(
                        f"[OSMOSE:Context] Parsed document_context: {doc_context}"
                    )

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[OSMOSE:Context] Failed to parse JSON response: {e}")

        # Tronquer si trop long
        if len(summary) > max_length:
            summary = summary[:max_length-3] + "..."

        # Stocker en cache (nouveau format 3-tuple)
        result = (summary, technical_density, doc_context)
        _document_context_cache[cache_key] = result

        logger.info(
            f"[OSMOSE:Context] Generated context ({len(summary)} chars, "
            f"density={technical_density:.2f}, "
            f"numbered_sections={doc_context.structure_hint.has_numbered_sections}, "
            f"entities={len(doc_context.entity_hints)}) "
            f"for document {document_id[:20]}..."
        )

        return result

    except Exception as e:
        logger.warning(f"[OSMOSE:Context] Failed to generate summary: {e}")

        # Fallback: construire contexte minimal depuis métadonnées
        fallback = f"Document: {metadata.get('title', 'Unknown')}. "
        if metadata.get('keywords'):
            fallback += f"Topics: {', '.join(metadata['keywords'][:5])}."

        result = (fallback, 0.5, DocumentContext.empty())
        _document_context_cache[cache_key] = result
        return result


def _parse_document_context(data: Dict[str, Any]) -> DocumentContext:
    """
    Parse le document_context depuis la réponse JSON du LLM.

    Gère les cas où certains champs sont manquants ou mal formés.
    Safe-by-default: en cas de doute, retourne des valeurs neutres.

    Args:
        data: Dictionnaire document_context du JSON

    Returns:
        DocumentContext parsé
    """
    # Parse structure_hint
    structure_hint = StructureHint.empty()
    if "structure_hint" in data and isinstance(data["structure_hint"], dict):
        sh = data["structure_hint"]
        structure_hint = StructureHint(
            has_numbered_sections=bool(sh.get("has_numbered_sections", False)),
            numbering_patterns=sh.get("numbering_patterns", []) or [],
            confidence=float(sh.get("confidence", 0.5)),
        )

    # Parse entity_hints
    entity_hints: List[EntityHint] = []
    if "entity_hints" in data and isinstance(data["entity_hints"], list):
        for eh in data["entity_hints"][:5]:  # Max 5
            if isinstance(eh, dict) and "label" in eh:
                entity_hints.append(EntityHint(
                    label=str(eh.get("label", "")),
                    type_hint=str(eh.get("type_hint", "other")),
                    confidence=float(eh.get("confidence", 0.5)),
                    evidence=str(eh.get("evidence", "inferred")),
                ))

    # Parse temporal_hint
    temporal_hint = TemporalHint.empty()
    if "temporal_hint" in data and isinstance(data["temporal_hint"], dict):
        th = data["temporal_hint"]
        explicit = th.get("explicit")
        inferred = th.get("inferred")
        # Normaliser les valeurs nulles/vides
        if explicit in (None, "", "null", "unknown"):
            explicit = None
        if inferred in (None, "", "null", "unknown"):
            inferred = None
        temporal_hint = TemporalHint(
            explicit=explicit,
            inferred=inferred,
            confidence=float(th.get("confidence", 0.0)),
        )

    # Parse scope_hints
    scope_hints: List[str] = []
    if "scope_hints" in data and isinstance(data["scope_hints"], list):
        scope_hints = [str(s) for s in data["scope_hints"] if s]

    return DocumentContext(
        structure_hint=structure_hint,
        entity_hints=entity_hints,
        temporal_hint=temporal_hint,
        scope_hints=scope_hints,
    )


def cross_reference_chunks_and_concepts(
    chunks: List[Dict[str, Any]],
    chunk_ids: List[str],
    concept_to_chunk_ids: Dict[str, List[str]],
    tenant_id: str
) -> None:
    """
    Établit le cross-référencement bidirectionnel Neo4j ↔ Qdrant.

    Après création des chunks, cette méthode :
    1. Récupère le mapping Proto → Canonical depuis Neo4j
    2. Met à jour les chunks Qdrant avec canonical_concept_ids
    3. Met à jour les CanonicalConcepts Neo4j avec chunk_ids

    Args:
        chunks: Liste des chunks créés
        chunk_ids: IDs des chunks dans Qdrant
        concept_to_chunk_ids: Mapping proto_id → chunk_ids
        tenant_id: ID tenant
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.common.clients.qdrant_client import get_qdrant_client
    from knowbase.config.settings import get_settings

    settings = get_settings()
    neo4j_client = get_neo4j_client(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database="neo4j"
    )
    qdrant_client = get_qdrant_client()

    try:
        # Étape 1: Récupérer mapping Proto → Canonical depuis Neo4j
        proto_to_canonical = {}
        with neo4j_client.driver.session(database="neo4j") as session:
            result = session.run("""
                MATCH (p:ProtoConcept)-[:PROMOTED_TO]->(c:CanonicalConcept)
                WHERE p.tenant_id = $tenant_id
                RETURN p.concept_id as proto_id, c.canonical_id as canonical_id
            """, tenant_id=tenant_id)

            for record in result:
                proto_to_canonical[record["proto_id"]] = record["canonical_id"]

        logger.info(
            f"[OSMOSE:CrossRef] Retrieved {len(proto_to_canonical)} Proto→Canonical mappings"
        )

        # Étape 2: Construire mapping chunk_id → canonical_concept_ids
        chunk_to_canonicals = {}
        canonical_to_chunks = {}  # Pour update Neo4j

        for chunk, chunk_id in zip(chunks, chunk_ids):
            proto_ids = chunk.get("proto_concept_ids", [])
            canonical_ids = []

            for proto_id in proto_ids:
                canonical_id = proto_to_canonical.get(proto_id)
                if canonical_id:
                    canonical_ids.append(canonical_id)
                    # Mapper Canonical → Chunks pour Neo4j update
                    if canonical_id not in canonical_to_chunks:
                        canonical_to_chunks[canonical_id] = []
                    canonical_to_chunks[canonical_id].append(chunk_id)

            if canonical_ids:
                chunk_to_canonicals[chunk_id] = canonical_ids

        logger.info(
            f"[OSMOSE:CrossRef] Mapped {len(chunk_to_canonicals)} chunks to canonical concepts"
        )

        # Étape 3: Update chunks Qdrant avec canonical_concept_ids (batch)
        if chunk_to_canonicals:
            # Utiliser set_payload pour update uniquement le champ (plus efficace)
            for chunk_id, canonical_ids in chunk_to_canonicals.items():
                qdrant_client.set_payload(
                    collection_name="knowbase",
                    payload={"canonical_concept_ids": canonical_ids},
                    points=[chunk_id]
                )

            logger.info(
                f"[OSMOSE:CrossRef] Updated {len(chunk_to_canonicals)} chunks in Qdrant with canonical_concept_ids"
            )

        # Étape 4: Update CanonicalConcepts Neo4j avec chunk_ids (batch)
        if canonical_to_chunks:
            with neo4j_client.driver.session(database="neo4j") as session:
                for canonical_id, chunk_list in canonical_to_chunks.items():
                    session.run("""
                        MATCH (c:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
                        SET c.chunk_ids = $chunk_ids
                    """, canonical_id=canonical_id, tenant_id=tenant_id, chunk_ids=chunk_list)

            logger.info(
                f"[OSMOSE:CrossRef] Updated {len(canonical_to_chunks)} CanonicalConcepts in Neo4j with chunk_ids"
            )

        # Log résumé
        logger.info(
            f"[OSMOSE:CrossRef] Cross-reference complete: "
            f"{len(chunk_to_canonicals)} chunks ↔ {len(canonical_to_chunks)} concepts"
        )

    except Exception as e:
        logger.error(f"[OSMOSE:CrossRef] Error during cross-reference: {e}", exc_info=True)
        raise


def clear_document_context_cache() -> None:
    """Vide le cache de contexte document (utile pour les tests)."""
    global _document_context_cache
    _document_context_cache.clear()
    logger.info("[OSMOSE:Enrichment] Document context cache cleared")


__all__ = [
    "enrich_anchors_with_context",
    "extract_document_metadata",
    "generate_document_summary",
    "cross_reference_chunks_and_concepts",
    "clear_document_context_cache",
    # Re-export DocumentContext pour commodité
    "DocumentContext",
]
