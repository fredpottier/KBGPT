#!/usr/bin/env python3
"""
Script pour appliquer le Doc-Level Extraction aux concepts existants.

Phase 2.9.4: Connecte les concepts Bucket 3 isolés sans réimporter les documents.
Utilise le cache d'extraction pour récupérer le texte source.

Usage:
    docker-compose exec app python /app/scripts/apply_doc_level_existing.py [--dry-run] [--limit N]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

from neo4j import GraphDatabase

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Neo4j Configuration (container)
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")


def load_extraction_cache() -> Dict[str, Dict[str, Any]]:
    """
    Charge tous les fichiers cache d'extraction.

    Returns:
        Dict mapping source_file -> cache_data
    """
    # Dans le conteneur Docker, data est monté sur /data (pas /app/data)
    cache_dir = Path("/data/extraction_cache")
    if not cache_dir.exists():
        # Try /app/data path (fallback)
        cache_dir = Path("/app/data/extraction_cache")
    if not cache_dir.exists():
        # Try Windows path
        cache_dir = Path("C:/Projects/SAP_KB/data/extraction_cache")

    cache_by_file = {}

    for cache_file in cache_dir.glob("*.knowcache.json"):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            source_file = data.get("metadata", {}).get("source_file", "")
            if source_file:
                full_text = data.get("extracted_text", {}).get("full_text", "")
                cache_by_file[source_file] = {
                    "full_text": full_text,
                    "cache_file": str(cache_file),
                    "title": data.get("document_metadata", {}).get("title", source_file)
                }
                logger.debug(f"Loaded cache for: {source_file} ({len(full_text)} chars)")
        except Exception as e:
            logger.warning(f"Failed to load cache {cache_file}: {e}")

    logger.info(f"[CACHE] Loaded {len(cache_by_file)} document caches")
    return cache_by_file


def get_isolated_concepts(session) -> List[Dict[str, Any]]:
    """
    Récupère tous les concepts isolés (sans relations).

    Returns:
        Liste de tous les concepts isolés
    """
    query = """
    // Concepts sans aucune relation (ni subject ni object)
    MATCH (c:CanonicalConcept)
    WHERE c.tenant_id = 'default'
    AND NOT EXISTS {
        MATCH (c)-[:RAW_ASSERTION]->()
    }
    AND NOT EXISTS {
        MATCH ()-[:RAW_ASSERTION]->(c)
    }

    RETURN
        c.canonical_id as canonical_id,
        c.name as name,
        c.concept_type as concept_type,
        c.quality_score as quality_score
    ORDER BY c.quality_score DESC
    """

    result = session.run(query)

    concepts = []
    for record in result:
        concepts.append({
            "concept_id": record.get("canonical_id"),  # Use canonical_id as concept_id
            "canonical_id": record.get("canonical_id"),
            "name": record.get("name", ""),
            "concept_type": record.get("concept_type", ""),
            "quality_score": record.get("quality_score", 0.5),
        })

    logger.info(f"[NEO4J] Found {len(concepts)} isolated concepts")
    return concepts


def match_concepts_to_documents(
    concepts: List[Dict[str, Any]],
    cache_by_file: Dict[str, Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Associe les concepts aux documents en vérifiant leur présence dans le texte.

    Returns:
        Dict mapping source_file -> list of concepts found in that document
    """
    by_document = defaultdict(list)

    for concept in concepts:
        name = concept.get("name", "").lower()
        if len(name) < 3:
            continue

        # Chercher dans quel document ce concept apparaît
        for source_file, cache_data in cache_by_file.items():
            full_text = cache_data.get("full_text", "").lower()
            if name in full_text:
                by_document[source_file].append(concept)
                break  # Un concept ne peut venir que d'un document

    # Log résumé
    matched = sum(len(v) for v in by_document.values())
    logger.info(f"[MATCH] Matched {matched}/{len(concepts)} concepts to {len(by_document)} documents")

    return dict(by_document)


def get_existing_relations(session) -> List[Dict[str, Any]]:
    """
    Récupère toutes les relations existantes pour l'anti-doublon.
    """
    query = """
    MATCH (s:CanonicalConcept)-[r:RAW_ASSERTION]->(o:CanonicalConcept)
    WHERE s.tenant_id = 'default'
    RETURN
        s.concept_id as subject_id,
        s.name as subject_name,
        r.predicate as predicate,
        o.concept_id as object_id,
        o.name as object_name
    LIMIT 1000
    """

    result = session.run(query)

    relations = []
    for record in result:
        relations.append({
            "subject_id": record.get("subject_id"),
            "subject_name": record.get("subject_name"),
            "predicate": record.get("predicate"),
            "object_id": record.get("object_id"),
            "object_name": record.get("object_name")
        })

    logger.info(f"[NEO4J] Found {len(relations)} existing relations")
    return relations


def match_document_to_cache(doc_id: str, cache_by_file: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Trouve le cache correspondant à un document_id.

    Le doc_id peut être:
    - Le nom de fichier exact
    - Un hash ou identifiant partiel
    """
    # Essai direct
    if doc_id in cache_by_file:
        return cache_by_file[doc_id]

    # Essai avec extension
    for ext in [".pdf", ".pptx", ".docx"]:
        if doc_id + ext in cache_by_file:
            return cache_by_file[doc_id + ext]

    # Recherche partielle
    doc_id_lower = doc_id.lower()
    for filename, cache_data in cache_by_file.items():
        if doc_id_lower in filename.lower():
            return cache_data
        # Essai sans extension
        base_name = Path(filename).stem.lower()
        if doc_id_lower == base_name or base_name in doc_id_lower:
            return cache_data

    return None


async def process_document(
    doc_id: str,
    concepts: List[Dict[str, Any]],
    document_text: str,
    existing_relations: List[Dict[str, Any]],
    extractor,
    writer,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Traite un document : identifie Bucket 3 et extrait relations.
    """
    stats = {
        "concepts_input": len(concepts),
        "bucket3_count": 0,
        "relations_extracted": 0,
        "relations_written": 0
    }

    # Identifier concepts Bucket 3
    bucket3_concepts, existing_rel_strings = extractor.identify_bucket3_concepts(
        all_concepts=concepts,
        existing_relations=existing_relations,
        quality_threshold=0.85,  # Légèrement plus bas pour rattraper plus de concepts
        allowed_types=["entity", "role", "standard", "abstract"],
        document_text=document_text
    )

    stats["bucket3_count"] = len(bucket3_concepts)

    if not bucket3_concepts:
        logger.info(f"  [{doc_id}] No Bucket 3 concepts found")
        return stats

    logger.info(f"  [{doc_id}] Found {len(bucket3_concepts)} Bucket 3 concepts")

    # Extraire relations doc-level
    result = extractor.extract_doc_level_relations(
        bucket3_concepts=bucket3_concepts,
        document_text=document_text,
        document_id=doc_id,
        existing_relations=existing_rel_strings
    )

    stats["relations_extracted"] = len(result.relations)

    if not result.relations:
        logger.info(f"  [{doc_id}] No new relations extracted")
        return stats

    logger.info(f"  [{doc_id}] Extracted {len(result.relations)} relations")

    # Écrire les relations
    if not dry_run and writer:
        from knowbase.relations.types import RawAssertionFlags

        # Flags pour doc-level: cross_sentence=True car extraction cross-segment
        doc_level_flags = RawAssertionFlags(cross_sentence=True)

        for rel in result.relations:
            try:
                result_id = writer.write_assertion(
                    subject_concept_id=rel.subject_concept_id,
                    object_concept_id=rel.object_concept_id,
                    predicate_raw=rel.predicate,
                    evidence_text=rel.evidence,
                    source_doc_id=doc_id,
                    source_chunk_id=f"{doc_id}_doc_level_retrofit",
                    confidence=rel.confidence,
                    source_language="multi",
                    subject_surface_form=rel.subject_label,
                    object_surface_form=rel.object_label,
                    flags=doc_level_flags
                )
                if result_id:
                    stats["relations_written"] += 1
            except Exception as e:
                logger.warning(f"  [{doc_id}] Failed to write relation: {e}")

    return stats


async def main():
    parser = argparse.ArgumentParser(description="Apply doc-level extraction to existing concepts")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to Neo4j, just show what would be done")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of documents to process (0=all)")
    parser.add_argument("--min-concepts", type=int, default=3, help="Minimum isolated concepts per document to process")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Doc-Level Extraction Retrofit Script")
    logger.info(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    logger.info("=" * 60)

    # Charger le cache
    cache_by_file = load_extraction_cache()

    if not cache_by_file:
        logger.error("No extraction cache found!")
        sys.exit(1)

    # Connexion Neo4j directe (comme les autres scripts)
    driver = None
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        logger.info(f"[NEO4J] Connected to {NEO4J_URI}")
    except Exception as e:
        logger.error(f"[NEO4J] Connection failed: {e}")
        sys.exit(1)

    with driver.session() as session:
        # Récupérer tous les concepts isolés
        all_isolated = get_isolated_concepts(session)

        if not all_isolated:
            logger.info("No isolated concepts found - nothing to do!")
            driver.close()
            sys.exit(0)

        # Récupérer relations existantes
        existing_relations = get_existing_relations(session)

    # Matcher les concepts aux documents par leur présence dans le texte
    isolated_by_doc = match_concepts_to_documents(all_isolated, cache_by_file)

    if not isolated_by_doc:
        logger.info("Could not match any concepts to cached documents!")
        driver.close()
        sys.exit(0)

    # Initialiser extracteur et writer
    from knowbase.relations.doc_level_extractor import DocLevelRelationExtractor
    from knowbase.common.llm_router import LLMRouter

    llm_router = LLMRouter()
    extractor = DocLevelRelationExtractor(
        llm_router=llm_router,
        model="gpt-4o-mini",
        min_confidence=0.80,
        evidence_window_chars=600,
        max_evidence_windows=25,
        relates_to_max_ratio=0.20
    )

    writer = None
    if not args.dry_run:
        from knowbase.relations.raw_assertion_writer import RawAssertionWriter
        from knowbase.common.clients.neo4j_client import Neo4jClient

        # Create Neo4j client with container URI
        neo4j_client_for_writer = Neo4jClient(
            uri=NEO4J_URI,
            user=NEO4J_USER,
            password=NEO4J_PASSWORD
        )
        writer = RawAssertionWriter(
            neo4j_client=neo4j_client_for_writer,
            tenant_id="default",
            extractor_version="doc_level_retrofit_v1"
        )

    # Statistiques globales
    total_stats = {
        "documents_processed": 0,
        "documents_skipped_no_cache": 0,
        "documents_skipped_few_concepts": 0,
        "total_concepts": 0,
        "total_bucket3": 0,
        "total_relations_extracted": 0,
        "total_relations_written": 0
    }

    # Traiter chaque document
    documents_to_process = list(isolated_by_doc.items())
    if args.limit > 0:
        documents_to_process = documents_to_process[:args.limit]

    for source_file, concepts in documents_to_process:
        # Filtrer documents avec peu de concepts
        if len(concepts) < args.min_concepts:
            total_stats["documents_skipped_few_concepts"] += 1
            continue

        # Récupérer le texte du document (déjà dans cache_by_file)
        cache_data = cache_by_file.get(source_file)
        if not cache_data:
            logger.warning(f"[SKIP] Cache data not found for: {source_file}")
            total_stats["documents_skipped_no_cache"] += 1
            continue

        document_text = cache_data.get("full_text", "")
        if len(document_text) < 500:
            logger.warning(f"[SKIP] Document text too short for: {source_file}")
            continue

        doc_id = source_file  # Utiliser le nom du fichier comme ID
        logger.info(f"\n[PROCESSING] {source_file} ({len(concepts)} isolated concepts)")

        # Traiter le document
        doc_stats = await process_document(
            doc_id=doc_id,
            concepts=concepts,
            document_text=document_text,
            existing_relations=existing_relations,
            extractor=extractor,
            writer=writer,
            dry_run=args.dry_run
        )

        # Accumuler stats
        total_stats["documents_processed"] += 1
        total_stats["total_concepts"] += doc_stats["concepts_input"]
        total_stats["total_bucket3"] += doc_stats["bucket3_count"]
        total_stats["total_relations_extracted"] += doc_stats["relations_extracted"]
        total_stats["total_relations_written"] += doc_stats["relations_written"]

    # Résumé final
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Documents processed:     {total_stats['documents_processed']}")
    logger.info(f"Documents skipped (no cache): {total_stats['documents_skipped_no_cache']}")
    logger.info(f"Documents skipped (few concepts): {total_stats['documents_skipped_few_concepts']}")
    logger.info(f"Total isolated concepts: {total_stats['total_concepts']}")
    logger.info(f"Bucket 3 concepts:       {total_stats['total_bucket3']}")
    logger.info(f"Relations extracted:     {total_stats['total_relations_extracted']}")
    logger.info(f"Relations written:       {total_stats['total_relations_written']}")

    if args.dry_run:
        logger.info("\n⚠️  DRY-RUN mode - no changes were made to Neo4j")
        logger.info("Run without --dry-run to apply changes")

    # Fermer connexion
    if driver:
        driver.close()


if __name__ == "__main__":
    asyncio.run(main())
