"""
Pipeline PPTX avec Knowledge Graph (Phase 1 Critère 1.3)

Version enrichie du pipeline PPTX qui extrait simultanément :
- Chunks pour Qdrant (vector search)
- Entities + Relations pour Graphiti (knowledge graph)

Principe: Zero appel LLM additionnel - extraction triple en UN SEUL appel
"""

import logging
import shutil
from pathlib import Path
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor

from knowbase.ingestion.pipelines.pptx_pipeline import (
    # Réutiliser fonctions utilitaires existantes
    ensure_dirs,
    remove_hidden_slides_inplace,
    convert_pptx_to_pdf,
    extract_notes_and_text,
    extract_pptx_metadata,
    analyze_deck_summary,
    convert_pdf_to_images_pymupdf,
    ingest_chunks,
    # Variables globales
    SLIDES_PNG,
    THUMBNAILS_DIR,
    DOCS_DONE,
    logger,
)

# Import des helpers pour LLM
from knowbase.ingestion.pipelines.pptx_pipeline import (
    llm_router,
    clean_gpt_response,
    recursive_chunk,
    create_fallback_chunks,
    PROMPT_REGISTRY,
    embed_texts,
    get_language_iso2,
    qdrant_client,
    QDRANT_COLLECTION,
    PUBLIC_URL,
)
from knowbase.config.prompts_loader import render_prompt
from knowbase.config.document_type_registry import get_document_type_registry
from knowbase.common.llm_router import TaskType
from qdrant_client.models import PointStruct
from datetime import datetime, timezone
import base64
import json
import time
import uuid

from knowbase.graphiti.qdrant_sync import get_sync_service
from knowbase.common.clients import get_qdrant_client

# Import Graphiti client
try:
    from knowbase.graphiti.graphiti_client import get_graphiti_client
    GRAPHITI_AVAILABLE = True
except ImportError:
    GRAPHITI_AVAILABLE = False
    logger.warning("⚠️ Graphiti non disponible - mode Qdrant-only")

from PIL import Image


def ingest_chunks_kg(chunks, doc_meta, file_uid, slide_index, deck_summary) -> List[str]:
    """
    Ingestion chunks dans Qdrant avec retour des IDs (Phase 1 Critère 1.3)

    Différence avec ingest_chunks() standard:
    - RETOURNE la liste des chunk IDs insérés
    - Permet de lier chunks ↔ episode Graphiti

    Args:
        chunks: Liste chunks à insérer
        doc_meta: Métadonnées document
        file_uid: UID fichier
        slide_index: Index slide
        deck_summary: Résumé deck

    Returns:
        List[str]: Liste des chunk IDs insérés dans Qdrant
    """
    # Filtrer les slides non informatifs (identique pipeline standard)
    excluded_roles = {"title", "transition", "agenda"}

    valid = []
    for ch in chunks:
        if not ch.get("full_explanation", "").strip():
            continue

        meta = ch.get("meta", {})
        slide_role = meta.get("slide_role", "")

        if slide_role in excluded_roles:
            logger.info(f"Slide {slide_index}: skipping chunk with slide_role '{slide_role}'")
            continue

        valid.append(ch)

    if not valid:
        logger.info(f"Slide {slide_index}: no valid chunks after filtering")
        return []

    # Embeddings
    texts = [ch["full_explanation"] for ch in valid]
    embs = embed_texts(texts)

    # Créer points Qdrant avec IDs trackés
    points = []
    chunk_ids = []

    for ch, emb in zip(valid, embs):
        meta = ch.get("meta", {})

        # Générer ID unique
        chunk_id = str(uuid.uuid4())
        chunk_ids.append(chunk_id)

        # Payload NORTH STAR (schéma cible Phase 1 Critère 1.3)
        # Séparation responsabilités: Qdrant = mémoire textuelle, KG = sémantique métier
        payload = {
            # Core (stable)
            "text": ch["full_explanation"].strip(),
            "language": get_language_iso2(ch["full_explanation"]),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "title": meta.get("title", f"Slide {slide_index}"),

            # Document (source info)
            "document": {
                "source_name": f"{file_uid}.pptx",
                "source_type": "pptx",
                "source_date_iso": doc_meta.get("source_date", ""),  # Format ISO
                "source_date_raw": doc_meta.get("source_date", ""),  # Format brut
                "links": {
                    "source_file_url": f"{PUBLIC_URL}/static/presentations/{file_uid}.pptx",
                    "slide_image_url": f"{PUBLIC_URL}/static/thumbnails/{file_uid}_slide_{slide_index}.jpg"
                }
            },

            # Chunk (position)
            "chunk": {
                "slide_index": slide_index
            },

            # Custom metadata (extensible, non-critique)
            # NOTE: main_solution sera enrichi plus tard via liaison KG
            "custom_metadata": {
                "solution": {
                    "id": "",  # À enrichir via canonicalisation KG (Phase 4)
                    "name": doc_meta.get("main_solution", "")  # Temporaire, sera remplacé par liaison KG
                },
                "audience": doc_meta.get("audience", [])  # Métadonnée éditoriale (reste dans Qdrant)
            },

            # Sys (infos techniques)
            "sys": {
                "tags_tech": ["pptx", "kg_pipeline_v1"],
                "prompt_meta": ch.get("prompt_meta", {})
            },

            # Liaisons Knowledge Graph (Phase 1 Critère 1.3)
            "related_node_ids": {
                "candidates": [],  # IDs entities/relations candidates (Phase 3)
                "approved": []     # IDs entities/relations approuvées (Phase 4)
            },

            # Liaisons Facts structurés (Phase 3)
            "related_facts": {
                "proposed": [],   # IDs facts proposed
                "approved": []    # IDs facts approved
            }
        }

        points.append(PointStruct(id=chunk_id, vector=emb, payload=payload))

    # Upsert dans Qdrant
    qdrant_client.upsert(collection_name=QDRANT_COLLECTION, points=points)
    logger.info(f"Slide {slide_index}: ingested {len(points)} chunks (IDs tracked for KG)")

    return chunk_ids


def ask_gpt_slide_analysis_kg(
    image_path,
    deck_summary,
    slide_index,
    source_name,
    text,
    notes,
    megaparse_content="",
    document_type="default",
    deck_prompt_id="unknown",
    retries=2,
):
    """
    Analyse slide via LLM vision avec extraction Knowledge Graph (Phase 1 Critère 1.3)

    NOUVEAU: Extraction triple-output en UN SEUL appel LLM (zero cost additionnel)
    - Concepts (chunks Qdrant)
    - Entities (Graphiti KG)
    - Relations (Graphiti KG)

    Critère 1.3 Phase 1: Intégration Qdrant ↔ Graphiti
    - Réutilisation appel LLM existant (zero latence additionnelle)
    - Extraction structurée entities + relations
    - Fallback chunks-only si LLM échoue

    Returns:
        Dict avec trois clés:
        {
            "chunks": List[Dict] - Chunks Qdrant (enrichis ou fallback),
            "entities": List[Dict] - Entities KG (vide si fallback),
            "relations": List[Dict] - Relations KG (vide si fallback)
        }
    """
    # Heartbeat avant l'appel LLM vision (long processus)
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
        send_worker_heartbeat()
    except Exception:
        pass  # Ignorer si pas dans un contexte RQ

    doc_type = document_type or "default"

    # **NOUVEAU: Génération dynamique de prompt via DocumentTypeRegistry**
    doc_type_registry = get_document_type_registry()

    # Vérifier que type existe, fallback sur 'default'
    if not doc_type_registry.exists(doc_type):
        logger.warning(
            f"[KG] Document type '{doc_type}' not found in registry, "
            f"using 'default' instead"
        )
        doc_type = "default"

    # Template de base avec variables Jinja2
    base_template = """**CRITICAL TRIPLE-OUTPUT ANALYSIS**

You are analyzing section {{ slide_index }} from '{{ source_name }}' (PowerPoint document).

Global deck summary:
{{ deck_summary }}

Section {{ slide_index }} content (extracted via MegaParse):
{{ megaparse_content | default(text) }}

Original text (legacy):
{{ text }}

Notes:
{{ notes }}

---

## 1. CONCEPTS (for vector search)

Extract 2-10 detailed explanations (50-500 words each) covering:
- Core ideas, features, capabilities described in this slide
- Technical details, processes, workflows explained
- Business value, use cases, benefits highlighted

Each concept should be self-contained and searchable.

{{ entity_relation_section }}

---

**Return a JSON object** with three sections:

{
  "concepts": [
    {
      "full_explanation": "Detailed explanation (50-500 words)...",
      "meta": {
        "scope": "solution-specific" | "cross-solution" | "industry-specific",
        "type": "feature" | "process" | "architecture" | "use_case" | "benefit"
      }
    }
  ],
  "entities": [
    {
      "name": "Entity name",
      "entity_type": "TYPE_FROM_DOCUMENT_CONFIG",
      "description": "Clear description of this entity",
      "attributes": {}
    }
  ],
  "relations": [
    {
      "source": "Source entity name",
      "target": "Target entity name",
      "relation_type": "TYPE_FROM_DOCUMENT_CONFIG",
      "description": "Description of relationship"
    }
  ]
}

**IMPORTANT**: Return ONLY the JSON object, no markdown, no explanations outside JSON.
"""

    # Générer section entities/relations spécifique au document_type
    entity_relation_section = doc_type_registry.generate_kg_prompt_section(doc_type)

    # Injecter section dans le template
    full_template = base_template.replace(
        "{{ entity_relation_section }}",
        entity_relation_section
    )

    # BLOC BEST-EFFORT: Extraction enrichie LLM vision
    try:
        img_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")

        # Render template avec variables Jinja2
        prompt_text = render_prompt(
            full_template,
            deck_summary=deck_summary,
            slide_index=slide_index,
            source_name=source_name,
            text=text,
            notes=notes,
            megaparse_content=megaparse_content,
        )
        msg = [
            {
                "role": "system",
                "content": "You analyze slides with visuals deeply and coherently, extracting structured knowledge.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                ],
            },
        ]

        for attempt in range(retries):
            try:
                raw_content = llm_router.complete(TaskType.VISION, msg)
                cleaned_content = clean_gpt_response(raw_content or "")

                # Parser triple-output JSON (toujours format KG maintenant)
                kg_data = json.loads(cleaned_content)

                # Validation: S'assurer que kg_data est un dict
                if not isinstance(kg_data, dict):
                    raise ValueError(f"LLM returned non-dict: {type(kg_data).__name__}")

                # Extraire concepts pour chunks Qdrant
                concepts = kg_data.get("concepts", [])
                entities = kg_data.get("entities", [])
                relations = kg_data.get("relations", [])

                # Validation: S'assurer que concepts/entities/relations sont des listes
                if not isinstance(concepts, list):
                    logger.warning(f"'concepts' n'est pas une liste: {type(concepts).__name__}, fallback []")
                    concepts = []
                if not isinstance(entities, list):
                    logger.warning(f"'entities' n'est pas une liste: {type(entities).__name__}, fallback []")
                    entities = []
                if not isinstance(relations, list):
                    logger.warning(f"'relations' n'est pas une liste: {type(relations).__name__}, fallback []")
                    relations = []

                # Créer chunks depuis concepts
                enriched = []
                for concept in concepts:
                    # Validation: S'assurer que concept est un dict
                    if not isinstance(concept, dict):
                        logger.warning(f"Concept ignoré (non-dict): {type(concept).__name__}")
                        continue

                    expl = concept.get("full_explanation", "")
                    meta = concept.get("meta", {})
                    if expl:
                        for seg in recursive_chunk(expl, max_len=400, overlap_ratio=0.15):
                            enriched.append({
                                "full_explanation": seg,
                                "meta": meta,
                                "prompt_meta": {
                                    "document_type": doc_type,
                                    "document_type_display": doc_type_registry.get_display_name(doc_type),
                                    "extraction_status": "kg_success",
                                    "entity_types_count": len(entities),
                                    "relations_count": len(relations)
                                },
                            })

                if enriched:
                    logger.info(
                        f"[KG] Slide {slide_index}: {len(enriched)} chunks + {len(entities)} entities + "
                        f"{len(relations)} relations (type: {doc_type})"
                    )
                    return {
                        "chunks": enriched,
                        "entities": entities,
                        "relations": relations
                    }
                else:
                    logger.warning(
                        f"[KG] Slide {slide_index}: LLM returned empty, retry {attempt + 1}/{retries}"
                    )

            except Exception as e:
                logger.warning(
                    f"Slide {slide_index} LLM attempt {attempt + 1}/{retries} failed: {e}"
                )
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))

    except Exception as e:
        logger.error(
            f"Slide {slide_index}: Erreur critique LLM vision: {e}. "
            f"Basculement fallback chunks-only"
        )

    # BLOC CRITIQUE: Fallback chunks-only (doit toujours réussir)
    logger.warning(
        f"Slide {slide_index}: LLM échoué après {retries} tentatives. "
        f"Fallback chunks-only activé (no KG data)"
    )

    fallback_chunks = create_fallback_chunks(
        text=text,
        notes=notes,
        megaparse_content=megaparse_content,
        slide_index=slide_index,
        document_type=doc_type,
        slide_prompt_id=slide_prompt_id
    )

    return {
        "chunks": fallback_chunks,
        "entities": [],
        "relations": []
    }


async def process_pptx_kg(
    pptx_path: Path,
    tenant_id: str,
    document_type: str = "default",
    progress_callback=None,
    rq_job=None
) -> Dict[str, Any]:
    """
    Pipeline PPTX enrichi avec Knowledge Graph (Phase 1 Critère 1.3)

    Nouveautés vs process_pptx():
    - Extraction entities/relations en MÊME TEMPS que chunks (zero cost LLM)
    - Accumulation entities/relations de tous les slides
    - Création episode Graphiti avec toutes les données du document
    - Liaison chunks ↔ episode (metadata bidirectionnelle)

    Args:
        pptx_path: Chemin vers fichier PPTX
        tenant_id: ID du tenant (pour isolation Graphiti)
        document_type: Type de document (default, rfp, etc.)
        progress_callback: Callback progression (optionnel)
        rq_job: Job RQ actuel (optionnel)

    Returns:
        Dict avec:
        {
            "chunks_inserted": int,
            "episode_id": str,
            "episode_name": str,
            "entities_count": int,
            "relations_count": int
        }
    """
    logger.info(f"🚀 [KG PIPELINE] Début ingestion enrichie: {pptx_path.name} (tenant: {tenant_id})")

    # Vérifier disponibilité Graphiti
    if not GRAPHITI_AVAILABLE:
        logger.warning(
            "⚠️ Graphiti non disponible - fallback sur pipeline standard "
            "(chunks Qdrant uniquement, pas de KG)"
        )
        from knowbase.ingestion.pipelines.pptx_pipeline import process_pptx
        result = process_pptx(pptx_path, document_type, progress_callback, rq_job)
        result.update({
            "episode_id": "",
            "episode_name": "",
            "entities_count": 0,
            "relations_count": 0,
            "kg_enabled": False
        })
        return result

    # Obtenir le job RQ actuel si pas fourni
    if rq_job is None:
        try:
            from rq import get_current_job
            rq_job = get_current_job()
        except Exception:
            rq_job = None

    if progress_callback:
        progress_callback("Préparation", 2, 100, "Suppression des slides cachés")

    # 1. Préparation document (identique pipeline standard)
    remove_hidden_slides_inplace(pptx_path)

    if progress_callback:
        progress_callback("Conversion PDF", 5, 100, "Conversion du PowerPoint en PDF")

    ensure_dirs()
    pdf_path = convert_pptx_to_pdf(pptx_path, SLIDES_PNG)
    slides_data = extract_notes_and_text(pptx_path)

    if progress_callback:
        progress_callback("Analyse du contenu", 10, 100, "Analyse du contenu et génération du résumé")

    # 2. Métadonnées + résumé document
    auto_metadata = extract_pptx_metadata(pptx_path)
    deck_info = analyze_deck_summary(
        slides_data, pptx_path.name, document_type=document_type, auto_metadata=auto_metadata
    )
    summary = deck_info.get("summary", "")
    metadata = deck_info.get("metadata", {})
    deck_prompt_id = deck_info.get("_prompt_meta", {}).get("deck_prompt_id", "unknown")

    if progress_callback:
        progress_callback("Génération des miniatures", 15, 100, "Conversion PDF → images en cours")

    # 3. Génération images (DPI adaptatif selon taille document)
    if len(slides_data) > 400:
        dpi = 120
        logger.info(f"📊 Gros document ({len(slides_data)} slides) - DPI réduit à {dpi}")
    elif len(slides_data) > 200:
        dpi = 150
        logger.info(f"📊 Document moyen ({len(slides_data)} slides) - DPI à {dpi}")
    else:
        dpi = 200
        logger.info(f"📊 Document normal ({len(slides_data)} slides) - DPI standard à {dpi}")

    try:
        images = convert_pdf_to_images_pymupdf(str(pdf_path), dpi=dpi, rq_job=rq_job)
        image_paths = {}

        for i, img in enumerate(images, start=1):
            img_path = THUMBNAILS_DIR / f"{pptx_path.stem}_slide_{i}.jpg"

            # Sauvegarder l'image pour le LLM
            if img.mode == "RGBA":
                rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1])
                rgb_img.save(img_path, "JPEG", quality=60, optimize=True)
            else:
                img.save(img_path, "JPEG", quality=60, optimize=True)

            image_paths[i] = img_path

            # Heartbeat périodique pour gros documents
            if len(slides_data) > 200 and i % 100 == 0:
                try:
                    from knowbase.ingestion.queue.jobs import send_worker_heartbeat
                    send_worker_heartbeat()
                    logger.debug(f"Heartbeat envoyé après génération de {i}/{len(images)} images")
                except Exception:
                    pass

        del images
        logger.info(f"✅ {len(image_paths)} images générées avec succès")

    except Exception as e:
        logger.error(f"❌ Erreur génération d'images: {e}")
        raise

    # 4. ANALYSE LLM ENRICHIE (chunks + entities + relations)
    logger.info(f"🔄 [KG] Début analyse LLM enrichie des slides...")

    actual_slide_count = len(image_paths)
    total_slides = len(slides_data)

    if progress_callback:
        progress_callback("Génération des miniatures", 18, 100, f"Création de {actual_slide_count} miniatures")

    # Réduire workers pour gros documents
    actual_workers = 1 if total_slides > 400 else 3
    logger.info(f"📊 Utilisation de {actual_workers} workers pour {total_slides} slides")

    # Structures pour accumuler données KG
    all_entities = []  # Liste de toutes les entities extraites
    all_relations = []  # Liste de toutes les relations extraites
    all_chunk_ids = []  # Liste de tous les chunk IDs insérés dans Qdrant

    tasks = []
    logger.info(f"🤖 [KG] Soumission de {len(slides_data)} tâches LLM au ThreadPoolExecutor...")

    with ThreadPoolExecutor(max_workers=actual_workers) as ex:
        for slide in slides_data:
            idx = slide["slide_index"]
            raw_text = slide.get("text", "")
            notes = slide.get("notes", "")
            megaparse_content = slide.get("megaparse_content", raw_text)
            content_type = slide.get("content_type", "unknown")

            # Ne transmettre le texte legacy que si nous n'avons pas de contenu MegaParse exploitable
            if megaparse_content and content_type not in ("python_pptx_fallback", "fallback_single"):
                prompt_text = ""
            else:
                prompt_text = raw_text

            if idx in image_paths:
                tasks.append(
                    (
                        idx,
                        ex.submit(
                            ask_gpt_slide_analysis_kg,  # NOUVELLE fonction avec KG
                            image_paths[idx],
                            summary,
                            idx,
                            pptx_path.name,
                            prompt_text,
                            notes,
                            megaparse_content,
                            document_type,
                            deck_prompt_id,
                        ),
                    )
                )

    total_slides = len(tasks)
    logger.info(f"🚀 [KG] Début analyse LLM de {total_slides} slides")
    if progress_callback:
        progress_callback("Analyse des slides", 20, 100, f"Analyse IA de {total_slides} slides")
        import time
        time.sleep(0.1)

    total_chunks = 0

    for i, (idx, future) in enumerate(tasks):
        # Progression de 20% à 90% pendant l'analyse des slides
        slide_progress = 20 + int((i / total_slides) * 70)
        if progress_callback:
            progress_callback("Analyse des slides", slide_progress, 100, f"Analyse slide {i+1}/{total_slides}")

        logger.info(f"🔍 [KG] Attente résultat LLM pour slide {idx} ({i+1}/{total_slides})")

        # Attendre le résultat avec heartbeats
        result = None
        try:
            import concurrent.futures
            import time

            timeout_seconds = 30
            start_time = time.time()

            while not future.done():
                try:
                    result = future.result(timeout=timeout_seconds)
                    break
                except concurrent.futures.TimeoutError:
                    elapsed = time.time() - start_time
                    try:
                        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
                        send_worker_heartbeat()
                        logger.debug(f"Heartbeat envoyé pendant analyse slide {idx} (attente: {elapsed:.1f}s)")
                    except Exception as e:
                        logger.warning(f"Erreur envoi heartbeat: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Erreur lors de l'analyse slide {idx}: {e}")
                    result = {"chunks": [], "entities": [], "relations": []}
                    break

            if result is None:
                result = future.result()

        except Exception as e:
            logger.error(f"Erreur critique slide {idx}: {e}")
            result = {"chunks": [], "entities": [], "relations": []}

        # Extraire données triple-output
        chunks = result.get("chunks", [])
        entities = result.get("entities", [])
        relations = result.get("relations", [])

        if not chunks:
            logger.info(f"Slide {idx}: No concepts extracted (empty/title/transition slide)")
        else:
            logger.info(
                f"✅ [KG] Slide {idx}: {len(chunks)} chunks + {len(entities)} entities + "
                f"{len(relations)} relations extraits"
            )

            # Log détaillé des entities extraites
            if entities:
                entity_types = [e.get('entity_type', 'UNKNOWN') for e in entities]
                entity_names = [e.get('name', 'N/A')[:30] for e in entities[:3]]  # 3 premières
                logger.info(f"   📊 Entities types: {', '.join(set(entity_types))}")
                logger.info(f"   📝 Exemples entities: {', '.join(entity_names)}")

            # Log détaillé des relations extraites
            if relations:
                relation_types = [r.get('relation_type', 'UNKNOWN') for r in relations]
                logger.info(f"   🔗 Relations types: {', '.join(set(relation_types))}")
                # Exemple de relation
                if relations:
                    r = relations[0]
                    logger.info(
                        f"   📌 Exemple: {r.get('source', 'N/A')[:20]} → "
                        f"{r.get('relation_type', 'N/A')} → {r.get('target', 'N/A')[:20]}"
                    )

        # Ingérer chunks dans Qdrant avec tracking des IDs (NOUVELLE VERSION)
        chunk_ids = ingest_chunks_kg(chunks, metadata, pptx_path.stem, idx, summary)
        logger.info(f"📝 [KG] Slide {idx}: {len(chunk_ids)} chunks ingérés dans Qdrant (IDs: {chunk_ids[:2] if chunk_ids else []}...)")
        total_chunks += len(chunks)

        # Accumuler chunk IDs pour liaison episode
        all_chunk_ids.extend(chunk_ids)

        # Accumuler entities/relations pour Graphiti
        all_entities.extend(entities)
        all_relations.extend(relations)

        logger.info(
            f"📊 [KG] Accumulation totale: {len(all_entities)} entities, "
            f"{len(all_relations)} relations ({len(all_chunk_ids)} chunks)"
        )

        # Heartbeat après traitement de la slide
        try:
            from knowbase.ingestion.queue.jobs import send_worker_heartbeat
            send_worker_heartbeat()
            logger.debug(f"Heartbeat envoyé après traitement slide {i+1}/{total_slides}")
        except Exception:
            pass

    logger.info(
        f"🎯 [KG] Finalisation: {total_chunks} chunks + {len(all_entities)} entities + "
        f"{len(all_relations)} relations accumulés"
    )
    print(f"\n🎯 [KG] Finalisation: {total_chunks} chunks + {len(all_entities)} entities + {len(all_relations)} relations")

    if progress_callback:
        progress_callback("Ingestion Knowledge Graph", 92, 100, "Création episode Graphiti")

    # 5. CRÉER EPISODE GRAPHITI avec toutes les données du document
    episode_id = ""
    episode_name = ""

    print(f"\n🌐 [KG] Début création episode Graphiti...")
    try:
        graphiti_client = get_graphiti_client()
        print(f"✅ Client Graphiti obtenu")

        # Nom episode basé sur metadata
        episode_name = f"PPTX: {pptx_path.name}"
        if metadata.get("main_solution"):
            episode_name = f"{metadata['main_solution']} - {pptx_path.name}"

        # Construire message principal avec résumé du document + chunk_ids
        chunk_ids_preview = all_chunk_ids[:5] if len(all_chunk_ids) > 5 else all_chunk_ids
        episode_content = f"""Document: {pptx_path.name}
Title: {metadata.get('title', 'N/A')}
Date: {metadata.get('source_date', 'N/A')}
Summary: {summary}

This document contains {len(all_entities)} entities and {len(all_relations)} relations extracted from {total_chunks} content chunks across the presentation.

Qdrant Chunks (total: {len(all_chunk_ids)}): {', '.join(chunk_ids_preview)}{"..." if len(all_chunk_ids) > 5 else ""}"""

        # Transformer entities au format Graphiti (description → summary)
        graphiti_entities = []
        for entity in all_entities:
            graphiti_entities.append({
                "name": entity.get("name", ""),
                "entity_type": entity.get("entity_type", "CONCEPT"),
                "summary": entity.get("description", "")  # Graphiti utilise 'summary' pas 'description'
            })

        # Transformer relations au format Graphiti (retirer description si présente)
        graphiti_relations = []
        for relation in all_relations:
            graphiti_relations.append({
                "source": relation.get("source", ""),
                "target": relation.get("target", ""),
                "relation_type": relation.get("relation_type", "RELATED_TO")
            })

        # Construire messages au format Graphiti
        # Message principal avec résumé + toutes les entities/relations
        messages = [
            {
                "content": episode_content,
                "role_type": "user",  # Requis par Graphiti API
                "role": "document_import",  # Requis: nom du rôle customisé
                "entities": graphiti_entities,
                "relations": graphiti_relations
            }
        ]

        logger.info(
            f"📤 [KG] Envoi à Graphiti: {len(graphiti_entities)} entities, "
            f"{len(graphiti_relations)} relations"
        )

        # Log échantillon entities à envoyer
        if graphiti_entities:
            sample_entity_types = {}
            for e in graphiti_entities:
                et = e.get('entity_type', 'UNKNOWN')
                sample_entity_types[et] = sample_entity_types.get(et, 0) + 1
            logger.info(f"   📊 Distribution entity types: {dict(sorted(sample_entity_types.items(), key=lambda x: -x[1])[:5])}")

        # Log échantillon relations à envoyer
        if graphiti_relations:
            sample_relation_types = {}
            for r in graphiti_relations:
                rt = r.get('relation_type', 'UNKNOWN')
                sample_relation_types[rt] = sample_relation_types.get(rt, 0) + 1
            logger.info(f"   🔗 Distribution relation types: {dict(sorted(sample_relation_types.items(), key=lambda x: -x[1])[:5])}")

        # Appel Graphiti avec format correct
        logger.info(f"🌐 [KG] Appel API Graphiti pour création episode...")

        result = graphiti_client.add_episode(
            group_id=tenant_id,
            messages=messages
        )

        # Note: Graphiti retourne une réponse asynchrone {"success": true, "message": "..."}
        # Les données sont traitées en arrière-plan et transformées en "facts"
        # L'episode_id n'est pas retourné immédiatement, il faut interroger l'API pour l'obtenir

        # Pour l'instant, on utilise un identifiant basé sur le document
        episode_id = f"{tenant_id}_{pptx_path.stem}"

        if result.get("success"):
            logger.info(
                f"✅ [KG] Episode envoyé avec succès à Graphiti ({episode_name})"
            )
            logger.info(
                f"   📤 Données envoyées: {len(graphiti_entities)} entities, {len(graphiti_relations)} relations"
            )
            logger.info(
                f"   ⏳ Traitement asynchrone en cours (Graphiti transforme en facts)"
            )
        else:
            logger.warning(f"⚠️ [KG] Réponse Graphiti inattendue: {result}")

    except Exception as e:
        logger.error(f"❌ [KG] Erreur création episode Graphiti: {e}", exc_info=True)
        print(f"\n⚠️  ERREUR GRAPHITI: {type(e).__name__}: {str(e)}")
        import traceback
        print(traceback.format_exc())
        # Continuer même si Graphiti échoue (chunks Qdrant déjà insérés)

    if progress_callback:
        progress_callback("Ingestion Knowledge Graph", 95, 100, "Liaison chunks ↔ episode")

    # 6. LIER CHUNKS QDRANT → EPISODE GRAPHITI (metadata bidirectionnelle)
    if episode_id:
        try:
            # TODO: Récupérer les chunk IDs réels depuis Qdrant
            # Pour Phase 1, on suppose que all_chunk_ids est rempli par ingest_chunks()
            # Besoin de modifier ingest_chunks() pour retourner les IDs

            sync_service = get_sync_service(
                qdrant_client=get_qdrant_client(),
                graphiti_client=graphiti_client
            )

            # Lier chunks → episode (update metadata Qdrant)
            # Note: all_chunk_ids doit être rempli - à implémenter dans ingest_chunks()
            if all_chunk_ids:
                await sync_service.link_chunks_to_episode(
                    chunk_ids=all_chunk_ids,
                    episode_id=episode_id,
                    episode_name=episode_name
                )
                logger.info(f"✅ [KG] {len(all_chunk_ids)} chunks liés à episode {episode_id}")
            else:
                logger.warning("⚠️ [KG] Aucun chunk ID disponible pour liaison episode")

        except Exception as e:
            logger.error(f"❌ [KG] Erreur liaison chunks ↔ episode: {e}", exc_info=True)

    # 7. Finalisation (identique pipeline standard)
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
        send_worker_heartbeat()
        logger.debug("Heartbeat envoyé avant finalisation")
    except Exception:
        pass

    logger.info(f"📁 Déplacement du fichier vers docs_done...")
    shutil.move(str(pptx_path), DOCS_DONE / f"{pptx_path.stem}.pptx")

    if progress_callback:
        progress_callback(
            "Terminé",
            100,
            100,
            f"Import terminé - {total_chunks} chunks + {len(all_entities)} entities insérés"
        )

    logger.info(
        f"🎉 [KG PIPELINE] INGESTION TERMINÉE - {pptx_path.name} - "
        f"{total_chunks} chunks + episode {episode_id}"
    )

    return {
        "chunks_inserted": total_chunks,
        "episode_id": episode_id,
        "episode_name": episode_name,
        "entities_count": len(all_entities),
        "relations_count": len(all_relations),
        "kg_enabled": True
    }
