"""
OSMOSE Enrichment - Context, Summary, Cross-Reference Methods.

Module extrait de osmose_agentique.py pour améliorer la modularité.
Contient les méthodes d'enrichissement et de contexte.

Author: OSMOSE Refactoring
Date: 2025-01-05
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Dict, List, Any, Optional, TYPE_CHECKING

import logging

from knowbase.common.llm_router import LLMRouter, get_llm_router, TaskType

if TYPE_CHECKING:
    from knowbase.extraction_v2.context.doc_context_frame import DocContextFrame

logger = logging.getLogger(__name__)

# Cache global pour le contexte document (évite recalcul)
_document_context_cache: Dict[str, tuple[str, float]] = {}


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
                # Extraire le passage (quote) de l'anchor
                passage = getattr(anchor, 'quote', '')
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
) -> tuple[str, float]:
    """
    Génère un résumé contextuel du document ET évalue sa densité technique.

    Phase 1.8 Task T1.8.1.0: Document Context Global.
    Phase 1.8.2: Ajout technical_density_hint pour stratégie extraction domain-agnostic.

    Ce résumé est utilisé pour:
    - Désambiguïser les acronymes/abréviations
    - Préférer les noms complets officiels
    - Contexte domaine pour meilleure extraction

    Le technical_density_hint (0.0-1.0) indique si le document contient
    du vocabulaire technique spécialisé nécessitant une extraction LLM.

    Args:
        document_id: ID unique pour cache
        full_text: Texte complet du document
        llm_router: Router LLM pour la génération
        max_length: Longueur max du résumé (caractères)

    Returns:
        Tuple (résumé contextuel, technical_density_hint 0.0-1.0)
    """
    # Vérifier cache global (inclut maintenant le hint)
    cache_key = hashlib.md5(document_id.encode()).hexdigest()

    if cache_key in _document_context_cache:
        cached = _document_context_cache[cache_key]
        # Support ancien format (string) et nouveau format (tuple)
        if isinstance(cached, tuple):
            logger.info(f"[PHASE1.8:Context] Cache hit for document {document_id[:20]}...")
            return cached
        else:
            # Ancien format: retourner avec hint par défaut
            return (cached, 0.5)

    logger.info(f"[PHASE1.8:Context] Generating document context for {document_id[:20]}...")

    # Extraction métadonnées sans LLM
    metadata = extract_document_metadata(full_text)

    # Construire prompt pour LLM
    # Limiter texte envoyé au LLM (premiers 4000 chars + derniers 1000)
    text_sample = full_text[:4000]
    if len(full_text) > 5000:
        text_sample += "\n[...]\n" + full_text[-1000:]

    # Prompt générique (domain-agnostic) avec évaluation densité technique
    system_prompt = """You are a document analyst. Your task is to:
1. Generate a concise document summary (1-2 paragraphs, max 500 characters)
2. Evaluate the technical density of the document

For the summary, focus on:
- Main theme/topic of the document
- Full official names of products, solutions, or key terms mentioned
- Industry or domain context
- Target audience

For technical density evaluation (0.0-1.0):
- 0.0-0.3: Simple text (marketing, general communication, basic explanations)
- 0.3-0.5: Moderate technical content (business documents, standard procedures)
- 0.5-0.7: Technical content (specialized domain vocabulary, acronyms, jargon)
- 0.7-1.0: Highly technical (scientific papers, technical specifications, dense terminology)

Answer in JSON format:
{"summary": "your summary here", "technical_density": 0.X}

Write the summary in the same language as the document."""

    # Injection du Domain Context si disponible
    try:
        injector = get_domain_context_injector()
        system_prompt = injector.inject_context(system_prompt, tenant_id="default")
        logger.info("[PHASE1.8:Context] Domain Context injected into summary prompt")
    except Exception as e:
        logger.debug(f"[PHASE1.8:Context] No Domain Context available: {e}")

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
            max_tokens=400
        )

        # Parser la réponse JSON
        import json
        technical_density = 0.5  # Défaut
        summary = response

        try:
            # Chercher JSON dans la réponse
            json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                summary = data.get("summary", response)
                technical_density = float(data.get("technical_density", 0.5))
                # Clamp entre 0 et 1
                technical_density = max(0.0, min(1.0, technical_density))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[PHASE1.8:Context] Failed to parse JSON response: {e}")
            # Garder le response brut comme summary

        # Tronquer si trop long
        if len(summary) > max_length:
            summary = summary[:max_length-3] + "..."

        # Stocker en cache (nouveau format tuple)
        _document_context_cache[cache_key] = (summary, technical_density)

        logger.info(
            f"[PHASE1.8:Context] Generated context ({len(summary)} chars, "
            f"technical_density={technical_density:.2f}) for document {document_id[:20]}..."
        )

        return (summary, technical_density)

    except Exception as e:
        logger.warning(f"[PHASE1.8:Context] Failed to generate summary: {e}")

        # Fallback: construire contexte minimal depuis métadonnées
        fallback = f"Document: {metadata.get('title', 'Unknown')}. "
        if metadata.get('keywords'):
            fallback += f"Topics: {', '.join(metadata['keywords'][:5])}."

        # Fallback hint: 0.5 (neutre)
        _document_context_cache[cache_key] = (fallback, 0.5)
        return (fallback, 0.5)


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
]
