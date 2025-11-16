# Code OSMOSE Pure pour Pipeline PPTX

**Date:** 2025-10-14
**Status:** Code de remplacement prêt

---

## 🎯 Ce qui Change

### ❌ Ancien Pipeline (Legacy)
```
PPTX → Vision analyse chaque slide → Chunks (entities/relations)
     → Qdrant "knowbase" + Neo4j entities/relations (Phase 3)
```

### ✅ Nouveau Pipeline (OSMOSE Pure)
```
PPTX → Vision génère résumés riches → Texte enrichi complet
     → OSMOSE Pipeline → Proto-KG UNIQUEMENT
```

---

## 📝 Section à Remplacer

**Fichier:** `src/knowbase/ingestion/pipelines/pptx_pipeline.py`

**Lignes à remplacer:** ~1821-2221 (section ThreadPoolExecutor jusqu'à fin)

---

## ✅ Nouveau Code

```python
    # ===== OSMOSE PURE : Vision génère résumés riches =====
    # Au lieu d'extraire entities/relations, Vision décrit visuellement chaque slide
    # OSMOSE fera ensuite l'analyse sémantique sur ces résumés

    actual_workers = 1 if total_slides > 400 else MAX_WORKERS
    logger.info(f"📊 [OSMOSE PURE] Utilisation de {actual_workers} workers pour {total_slides} slides")

    vision_tasks = []
    logger.info(f"🤖 [OSMOSE PURE] Soumission de {len(slides_data)} tâches Vision (résumés)...")

    with ThreadPoolExecutor(max_workers=actual_workers) as ex:
        for slide in slides_data:
            idx = slide["slide_index"]
            raw_text = slide.get("text", "")
            notes = slide.get("notes", "")
            megaparse_content = slide.get("megaparse_content", raw_text)

            if idx in image_paths:
                # Mode OSMOSE Pure: Vision génère résumé riche
                if use_vision:
                    vision_tasks.append(
                        (
                            idx,
                            ex.submit(
                                ask_gpt_vision_summary,  # Nouvelle fonction
                                image_paths[idx],
                                idx,
                                pptx_path.name,
                                raw_text,
                                notes,
                                megaparse_content
                            ),
                        )
                    )
                else:
                    # Fallback texte brut
                    vision_tasks.append(
                        (idx, None)  # Pas de Vision, texte direct
                    )

    total_slides_with_vision = len([t for t in vision_tasks if t[1] is not None])
    logger.info(f"🚀 [OSMOSE PURE] Début génération de {total_slides_with_vision} résumés Vision")

    if progress_callback:
        progress_callback("Analyse Vision", 20, 100, f"Génération résumés visuels ({total_slides_with_vision} slides)")

    # Collecter les résumés
    slide_summaries = []

    for i, (idx, future) in enumerate(vision_tasks):
        slide_progress = 20 + int((i / len(vision_tasks)) * 40)  # 20% → 60%
        if progress_callback:
            progress_callback("Analyse Vision", slide_progress, 100, f"Slide {i+1}/{len(vision_tasks)}")

        if future is not None:
            # Attendre résumé Vision
            try:
                import concurrent.futures
                import time

                timeout_seconds = 60
                start_time = time.time()

                while not future.done():
                    try:
                        summary = future.result(timeout=timeout_seconds)
                        break
                    except concurrent.futures.TimeoutError:
                        # Heartbeat
                        elapsed = time.time() - start_time
                        if elapsed > 300:  # 5 minutes max
                            logger.warning(f"Slide {idx} [VISION SUMMARY]: Timeout après 5min")
                            summary = f"Slide {idx}: timeout"
                            break
                        try:
                            from knowbase.ingestion.queue.jobs import send_worker_heartbeat
                            send_worker_heartbeat()
                        except Exception:
                            pass

                if not future.done():
                    logger.error(f"Slide {idx} [VISION SUMMARY]: Future n'est pas done après attente")
                    summary = f"Slide {idx}: erreur"
                else:
                    summary = future.result()

            except Exception as e:
                logger.error(f"Slide {idx} [VISION SUMMARY]: Erreur récupération résultat: {e}")
                # Fallback texte
                slide_data = slides_data[i] if i < len(slides_data) else {}
                summary = f"Slide {idx}: {slide_data.get('text', '')} {slide_data.get('notes', '')}"

        else:
            # Pas de Vision, utiliser texte brut
            slide_data = slides_data[i] if i < len(slides_data) else {}
            text = slide_data.get('text', '')
            notes = slide_data.get('notes', '')
            summary = f"{text}\n{notes}".strip() or f"Slide {idx}"

        # Ajouter à la collection
        slide_summaries.append({
            "slide_index": idx,
            "summary": summary
        })

        logger.info(f"Slide {idx} [VISION SUMMARY]: {len(summary)} chars collectés")

        # Heartbeat périodique
        if (i + 1) % 3 == 0:
            try:
                from knowbase.ingestion.queue.jobs import send_worker_heartbeat
                send_worker_heartbeat()
            except Exception:
                pass

    logger.info(f"✅ [OSMOSE PURE] {len(slide_summaries)} résumés Vision collectés")

    # ===== Construire texte complet enrichi =====
    logger.info("[OSMOSE PURE] Construction du texte enrichi complet...")

    full_text_parts = []
    for slide_summary in slide_summaries:
        idx = slide_summary["slide_index"]
        summary = slide_summary["summary"]
        full_text_parts.append(f"\\n--- Slide {idx} ---\\n{summary}")

    full_text_enriched = "\\n\\n".join(full_text_parts)

    logger.info(f"[OSMOSE PURE] Texte enrichi construit: {len(full_text_enriched)} chars depuis {len(slide_summaries)} slides")

    if progress_callback:
        progress_callback("Préparation OSMOSE", 65, 100, "Texte enrichi construit")

    # ===== OSMOSE Pipeline V2.1 - Analyse Sémantique =====
    logger.info("=" * 80)
    logger.info("[OSMOSE PURE] Lancement du traitement sémantique (remplace ingestion legacy)")
    logger.info("=" * 80)

    try:
        from knowbase.ingestion.osmose_integration import process_document_with_osmose
        import asyncio

        if full_text_enriched and len(full_text_enriched) >= 100:
            if progress_callback:
                progress_callback("OSMOSE Semantic", 70, 100, "Extraction concepts canoniques cross-linguals")

            # Appeler OSMOSE Pure de manière asynchrone
            osmose_result = asyncio.run(
                process_document_with_osmose(
                    document_id=pptx_path.stem,
                    document_title=pptx_path.name,
                    document_path=pptx_path,
                    text_content=full_text_enriched,  # Résumés Vision enrichis
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
                    f"  - Proto-KG: {osmose_result.proto_kg_concepts_stored} concepts + "
                    f"{osmose_result.proto_kg_relations_stored} relations + "
                    f"{osmose_result.proto_kg_embeddings_stored} embeddings\\n"
                    f"  - Durée: {osmose_result.osmose_duration_seconds:.1f}s"
                )
                logger.info("=" * 80)

                if progress_callback:
                    progress_callback(
                        "OSMOSE Complete",
                        95,
                        100,
                        f"{osmose_result.canonical_concepts} concepts canoniques extraits"
                    )

            else:
                error_msg = f"OSMOSE processing failed: {osmose_result.osmose_error}"
                logger.error(f"[OSMOSE PURE] ❌ {error_msg}")
                if progress_callback:
                    progress_callback("Erreur OSMOSE", 70, 100, error_msg)
                raise Exception(error_msg)

        else:
            error_msg = f"Text too short ({len(full_text_enriched) if full_text_enriched else 0} chars)"
            logger.error(f"[OSMOSE PURE] ❌ {error_msg}")
            if progress_callback:
                progress_callback("Erreur", 70, 100, error_msg)
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
    logger.info(
        f"📊 Métriques: {osmose_result.canonical_concepts} concepts canoniques, "
        f"{osmose_result.proto_kg_concepts_stored} stockés dans Proto-KG"
    )

    logger.info(f"Done {pptx_path.name} — OSMOSE Pure mode")

    return {
        "osmose_pure": True,
        "canonical_concepts": osmose_result.canonical_concepts,
        "concept_connections": osmose_result.concept_connections,
        "proto_kg_concepts_stored": osmose_result.proto_kg_concepts_stored,
        "proto_kg_relations_stored": osmose_result.proto_kg_relations_stored,
        "proto_kg_embeddings_stored": osmose_result.proto_kg_embeddings_stored
    }
```

---

## 🔧 Application

**Remplacer dans `pptx_pipeline.py` :**

1. **Trouver** la ligne ~1815 : `actual_workers = 1 if total_slides > 400 else MAX_WORKERS`
2. **Supprimer** jusqu'à la ligne ~2221 (fin de la fonction process_pptx, avant les autres fonctions)
3. **Remplacer** par le code ci-dessus

---

## ✅ Résultat

- ✅ Vision génère résumés riches (compréhension visuelle)
- ✅ OSMOSE analyse sémantique (concepts canoniques)
- ✅ Proto-KG seul storage (Neo4j + Qdrant concepts_proto)
- ❌ Plus de Qdrant "knowbase"
- ❌ Plus de Phase 3 entities/relations
- ❌ Plus d'Episodes

---

**Version:** 1.0
**Date:** 2025-10-14
