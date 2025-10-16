"""
PPTX Pipeline - OSMOSE Pure Version

Cette version REMPLACE complètement l'ingestion legacy par OSMOSE Pure:
- ❌ Supprimé: Ingestion Qdrant "knowbase" (chunks)
- ❌ Supprimé: Ingestion Neo4j entities/relations/facts (Phase 3)
- ❌ Supprimé: Création Episodes
- ✅ Ajouté: OSMOSE Pipeline V2.1 → Proto-KG UNIQUEMENT

Architecture:
    PPTX → Extraction Texte → OSMOSE Pipeline → Proto-KG (concepts canoniques)

Ce fichier contient les fonctions modifiées pour process_pptx().
À intégrer dans pptx_pipeline.py en remplacement de la logique legacy.
"""

# Remplacement pour process_pptx() - Section after slide processing
OSMOSE_REPLACEMENT_CODE = """
    logger.info(f"🎯 Finalisation: {total} chunks au total traités")

    # ===== OSMOSE PURE - Traitement sémantique UNIQUEMENT =====
    # REMPLACE:
    # - Ingestion Qdrant "knowbase" (chunks)
    # - Phase 3 Neo4j (entities/relations/facts)
    # - Création Episodes
    #
    # Tout passe maintenant par le Proto-KG (concepts canoniques cross-linguals)
    logger.info("=" * 80)
    logger.info("[OSMOSE PURE] Lancement du traitement sémantique (remplace ingestion legacy)")
    logger.info("=" * 80)

    try:
        from knowbase.ingestion.osmose_integration import process_document_with_osmose
        import asyncio

        # Construire le texte complet depuis slides_data
        logger.info("[OSMOSE PURE] Construction du texte complet depuis les slides...")

        full_text_parts = []
        for slide in slides_data:
            slide_index = slide.get("slide_index", 0)
            slide_text = slide.get("text", "")
            slide_notes = slide.get("notes", "")
            megaparse_content = slide.get("megaparse_content", "")

            # Utiliser megaparse si disponible, sinon fallback sur text + notes
            if megaparse_content:
                full_text_parts.append(f"\\n--- Slide {slide_index} ---\\n{megaparse_content}")
            else:
                combined = f"{slide_text}\\n{slide_notes}".strip()
                if combined:
                    full_text_parts.append(f"\\n--- Slide {slide_index} ---\\n{combined}")

        full_text = "\\n".join(full_text_parts)

        logger.info(f"[OSMOSE PURE] Texte complet construit: {len(full_text)} chars depuis {len(slides_data)} slides")

        if full_text and len(full_text) >= 100:
            if progress_callback:
                progress_callback("OSMOSE Semantic", 90, 100, "Extraction concepts canoniques cross-linguals")

            # Appeler OSMOSE Pure de manière asynchrone
            # AUCUN storage legacy (ni Qdrant "knowbase", ni Neo4j entities/relations)
            osmose_result = asyncio.run(
                process_document_with_osmose(
                    document_id=pptx_path.stem,
                    document_title=pptx_path.name,
                    document_path=pptx_path,
                    text_content=full_text,
                    tenant_id="default"
                )
            )

            if osmose_result.osmose_success:
                logger.info("=" * 80)
                logger.info(
                    f"[OSMOSE PURE] ✅ Traitement réussi:\\n"
                    f"  - {osmose_result.canonical_concepts} concepts canoniques\\n"
                    f"  - {osmose_result.concept_connections} connexions cross-documents\\n"
                    f"  - {osmose_result.topics_segmented} topics segmentés\\n"
                    f"  - Proto-KG: {osmose_result.proto_kg_concepts_stored} concepts + {osmose_result.proto_kg_relations_stored} relations + {osmose_result.proto_kg_embeddings_stored} embeddings\\n"
                    f"  - Durée: {osmose_result.osmose_duration_seconds:.1f}s"
                )
                logger.info("=" * 80)

                if progress_callback:
                    progress_callback(
                        "OSMOSE Complete",
                        97,
                        100,
                        f"{osmose_result.canonical_concepts} concepts canoniques extraits"
                    )

            else:
                error_msg = f"OSMOSE processing failed: {osmose_result.osmose_error}"
                logger.error(f"[OSMOSE PURE] ❌ {error_msg}")
                if progress_callback:
                    progress_callback("Erreur OSMOSE", 90, 100, error_msg)
                raise Exception(error_msg)

        else:
            error_msg = f"Text too short ({len(full_text) if full_text else 0} chars)"
            logger.error(f"[OSMOSE PURE] ❌ {error_msg}")
            if progress_callback:
                progress_callback("Erreur", 90, 100, error_msg)
            raise Exception(error_msg)

    except Exception as e:
        # En mode OSMOSE Pure, une erreur OSMOSE = échec complet de l'ingestion
        logger.error(f"[OSMOSE PURE] ❌ Erreur traitement sémantique: {e}", exc_info=True)
        if progress_callback:
            progress_callback("Erreur OSMOSE", 0, 100, str(e))
        status_file.write_text("error")
        raise  # Re-raise pour arrêter le traitement

    # ===== Fin OSMOSE Pure =====

    # Heartbeat final avant finalisation
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
        send_worker_heartbeat()
        logger.debug("Heartbeat envoyé avant finalisation")
    except Exception:
        pass

    logger.info(f"📁 Déplacement du fichier vers docs_done...")
    shutil.move(str(pptx_path), DOCS_DONE / f"{pptx_path.stem}.pptx")

    if progress_callback:
        progress_callback("Terminé", 100, 100, f"Import terminé - OSMOSE Pure activé")

    logger.info(f"🎉 INGESTION TERMINÉE - {pptx_path.name} - OSMOSE Pure")
    logger.info(f"📊 Métriques: {osmose_result.canonical_concepts} concepts canoniques, {osmose_result.proto_kg_concepts_stored} stockés dans Proto-KG")

    logger.info(f"Done {pptx_path.name} — OSMOSE Pure mode")

    return {
        "osmose_pure": True,
        "canonical_concepts": osmose_result.canonical_concepts,
        "concept_connections": osmose_result.concept_connections,
        "proto_kg_concepts_stored": osmose_result.proto_kg_concepts_stored,
        "proto_kg_relations_stored": osmose_result.proto_kg_relations_stored,
        "proto_kg_embeddings_stored": osmose_result.proto_kg_embeddings_stored
    }
"""

# Instructions pour intégration
INTEGRATION_INSTRUCTIONS = """
INTEGRATION DANS pptx_pipeline.py:

1. Trouver la section commençant par:
   logger.info(f"🎯 Finalisation: {total} chunks au total traités")
   (ligne ~1816)

2. SUPPRIMER tout le code jusqu'à (ligne ~2198):
   # === FIN PHASE 3 ===

3. REMPLACER par le code OSMOSE_REPLACEMENT_CODE ci-dessus

4. Supprimer également les appels à ingest_chunks() dans la boucle slide processing:
   - Ligne ~1803: ingest_chunks(chunks, metadata, pptx_path.stem, idx, summary)

5. Commentaires à retirer:
   - Toute la PHASE 3 (extraction KG, Neo4j, Episode)
   - Ingestion Qdrant legacy

Résultat:
- Pas d'ingestion Qdrant "knowbase"
- Pas d'ingestion Neo4j entities/relations
- Uniquement OSMOSE → Proto-KG
"""
