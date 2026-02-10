from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, HasIdCondition
from sentence_transformers import SentenceTransformer

from knowbase.config.settings import Settings
from knowbase.common.clients import rerank_chunks
from knowbase.common.logging import setup_logging
from .synthesis import synthesize_response

TOP_K = 10
SCORE_THRESHOLD = 0.5
PUBLIC_URL = os.getenv("PUBLIC_URL", "knowbase.ngrok.app")

# Logger pour le module search
_settings = Settings()
logger = setup_logging(_settings.logs_dir, "search_service.log")


def build_response_payload(result, public_url: str) -> dict[str, Any]:
    payload = result.payload or {}

    # Nouvelle structure: document et chunk sous-objets
    document = payload.get("document", {})
    chunk = payload.get("chunk", {})

    # Gestion des URLs avec fallback vers l'ancienne structure ET document_name
    # Priorité: document.source_file_url > payload.source_file_url > payload.document_name > payload.doc_id
    source_file_url = (
        document.get("source_file_url") or
        payload.get("source_file_url") or
        payload.get("document_name", "") or
        payload.get("doc_id", "")  # Fallback knowbase_chunks_v2
    )
    slide_image_url = document.get("slide_image_url") or payload.get("slide_image_url", "")
    slide_index = (
        chunk.get("slide_index") or
        payload.get("slide_index") or
        payload.get("page_no", "")  # Fallback knowbase_chunks_v2
    )

    # Construction de l'URL thumbnail complète
    if slide_image_url and not slide_image_url.startswith("http"):
        slide_image_url = f"https://{public_url}/static/thumbnails/{os.path.basename(slide_image_url)}"
    elif slide_image_url and slide_image_url.startswith(f"https://{public_url}"):
        # URL déjà complète, pas besoin de modification
        pass

    return {
        "text": payload.get("text", ""),
        "source_file": source_file_url,
        "slide_index": slide_index,
        "score": result.score,
        "slide_image_url": slide_image_url,
    }


def search_documents(
    *,
    question: str,
    qdrant_client: QdrantClient,
    embedding_model: SentenceTransformer,
    settings: Settings,
    solution: str | None = None,
    tenant_id: str = "default",
    use_graph_context: bool = True,
    graph_enrichment_level: str = "standard",
    session_id: str | None = None,
    use_hybrid_anchor_search: bool = False,
    use_graph_first: bool = True,  # Activé par défaut pour utiliser Topics/COVERS (mode ANCHORED)
    use_kg_traversal: bool = True,  # 🔗 OSMOSE: Traversée multi-hop CHAINS_TO
    use_instrumented: bool = False,
) -> dict[str, Any]:
    """
    Recherche sémantique avec enrichissement Knowledge Graph (OSMOSE) et contexte conversationnel.

    Args:
        question: Question de l'utilisateur
        qdrant_client: Client Qdrant
        embedding_model: Modèle d'embedding
        settings: Configuration
        solution: Filtre par solution SAP (optionnel)
        tenant_id: Tenant ID pour le KG
        use_graph_context: Activer l'enrichissement KG (Graph-Guided RAG)
        graph_enrichment_level: Niveau d'enrichissement (none, light, standard, deep)
        session_id: ID de session pour contexte conversationnel (Memory Layer Phase 2.5)
        use_hybrid_anchor_search: Utiliser le HybridAnchorSearchService (Phase 7)
        use_graph_first: Utiliser le runtime Graph-First (ADR Phase C)
        use_instrumented: Activer les reponses instrumentees (Assertion-Centric UX)

    Returns:
        Résultats de recherche avec synthèse enrichie
    """
    query = question.strip()

    # 🧠 Memory Layer: Récupérer le contexte de conversation si session_id fourni
    session_context_text = ""
    enriched_query = query  # Requête enrichie pour la recherche vectorielle
    recent_messages = []  # Pour le resolver d'entités

    if session_id:
        try:
            from knowbase.memory import get_session_manager
            manager = get_session_manager()

            # Récupérer les derniers messages de la session
            recent_messages = manager.get_recent_messages(session_id, count=5)

            if recent_messages:
                # Construire le contexte conversationnel pour la synthèse
                session_context_lines = ["## Contexte de la conversation précédente\n"]
                for msg in recent_messages:
                    role_label = "Utilisateur" if msg.role == "user" else "Assistant"
                    # Tronquer les messages longs
                    content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
                    session_context_lines.append(f"**{role_label}**: {content}\n")
                session_context_text = "\n".join(session_context_lines)

                # 🔑 NOTE: On n'enrichit PAS la requête vectorielle avec le contexte précédent
                # Le contexte de session (session_context_text) est passé au LLM pour la synthèse,
                # ce qui lui permet de gérer les références contextuelles (follow-up questions).
                # Enrichir la requête vectorielle causait des bugs où une nouvelle question
                # sur un sujet différent retournait les résultats de la question précédente.
                # Fix 2026-01-23: enriched_query reste égal à query (pas de pollution)

                logger.info(
                    f"[MEMORY] Session context loaded: {len(recent_messages)} messages from {session_id[:8]}..."
                )
        except Exception as e:
            logger.warning(f"[MEMORY] Failed to load session context (non-blocking): {e}")

    # Utiliser la requête enrichie pour l'embedding
    query_vector = embedding_model.encode(enriched_query)
    if hasattr(query_vector, "tolist"):
        query_vector = query_vector.tolist()
    elif hasattr(query_vector, "numpy"):
        query_vector = query_vector.numpy().tolist()
    query_vector = [float(x) for x in query_vector]

    # 🌊 ADR_GRAPH_FIRST_ARCHITECTURE Phase C: Graph-First Search Mode
    graph_first_plan = None
    graph_first_chunks = None
    graph_first_succeeded = False

    # Lier use_graph_first à use_graph_context pour cohérence UX (fix 2026-01-23)
    # Si l'utilisateur désactive "Knowledge Graph", on désactive aussi le routage structurel
    effective_graph_first = use_graph_first and use_graph_context

    if effective_graph_first:
        try:
            from .graph_first_search import get_graph_first_service, SearchMode as GFSearchMode

            gf_service = get_graph_first_service(tenant_id)

            # Construire le plan de recherche (détermine le mode)
            loop = asyncio.new_event_loop()
            try:
                graph_first_plan = loop.run_until_complete(
                    gf_service.build_search_plan(query)
                )
            finally:
                loop.close()

            # Exécuter la recherche selon le mode
            if graph_first_plan.mode in (GFSearchMode.REASONED, GFSearchMode.ANCHORED):
                context_ids = graph_first_plan.get_context_ids_for_qdrant()
                document_ids = graph_first_plan.get_document_ids_for_qdrant()

                # Utiliser context_ids si disponible, sinon document_ids (fix 2026-01-23)
                if context_ids or document_ids:
                    # Recherche Qdrant filtrée par context_ids ou document_ids
                    loop = asyncio.new_event_loop()
                    try:
                        graph_first_chunks = loop.run_until_complete(
                            gf_service.search_qdrant_filtered(
                                query=enriched_query,
                                context_ids=context_ids,
                                document_ids=document_ids if not context_ids else None,
                                collection_name=settings.qdrant_collection,
                                top_k=TOP_K,
                            )
                        )
                    finally:
                        loop.close()

                    if graph_first_chunks:
                        graph_first_succeeded = True
                        filter_type = "contexts" if context_ids else "documents"
                        filter_count = len(context_ids) if context_ids else len(document_ids)
                        logger.info(
                            f"[GRAPH-FIRST] Mode {graph_first_plan.mode.value}: "
                            f"{len(graph_first_chunks)} chunks from {filter_count} {filter_type}"
                        )

            if not graph_first_succeeded:
                logger.info(
                    f"[GRAPH-FIRST] Falling back to standard search "
                    f"(mode={graph_first_plan.mode.value}, reason={graph_first_plan.fallback_reason})"
                )

        except Exception as e:
            logger.warning(f"[GRAPH-FIRST] Search failed, falling back to standard: {e}")

    # 🚀 OSMOSE Phase 7: Hybrid Anchor Search Mode
    reranked_chunks = None
    hybrid_search_succeeded = False

    if use_hybrid_anchor_search:
        try:
            from .hybrid_anchor_search import (
                get_hybrid_anchor_search_service,
                SearchMode
            )

            hybrid_service = get_hybrid_anchor_search_service(
                qdrant_client=qdrant_client,
                embedding_model=embedding_model,
                tenant_id=tenant_id
            )

            # Construire les filtres
            filter_params = {}
            if solution:
                filter_params["solution.main"] = solution

            # Exécuter la recherche hybride
            hybrid_response = hybrid_service.search_sync(
                query=enriched_query,
                collection_name=settings.qdrant_collection,
                top_k=TOP_K,
                mode=SearchMode.HYBRID,
                filter_params=filter_params if filter_params else None
            )

            if hybrid_response.results:
                # Convertir les résultats hybrides en format standard
                hybrid_chunks = []
                for hr in hybrid_response.results:
                    chunk_data = {
                        "text": hr.text,
                        "source_file": hr.source_file_url or hr.document_name,
                        "slide_index": hr.slide_index,
                        "score": hr.score,
                        "slide_image_url": hr.slide_image_url,
                        # Métadonnées additionnelles Hybrid Anchor
                        "chunk_score": hr.chunk_score,
                        "concept_score": hr.concept_score,
                        "citations": [
                            {
                                "concept_label": c.concept_label,
                                "anchor_role": c.anchor_role,
                                "quote": c.quote,
                            }
                            for c in hr.citations
                        ]
                    }
                    hybrid_chunks.append(chunk_data)

                reranked_chunks = hybrid_chunks
                hybrid_search_succeeded = True

                logger.info(
                    f"[OSMOSE:HybridAnchor] Search returned {len(hybrid_chunks)} results "
                    f"({hybrid_response.total_concepts_matched} concepts matched, "
                    f"{hybrid_response.processing_time_ms:.1f}ms)"
                )

        except Exception as e:
            logger.warning(
                f"[OSMOSE:HybridAnchor] Search failed, falling back to standard: {e}"
            )

    # ADR_GRAPH_FIRST: Si graph-first a réussi, utiliser ces chunks
    if graph_first_succeeded and graph_first_chunks:
        reranked_chunks = graph_first_chunks
        # Reranker pour améliorer l'ordre
        reranked_chunks = rerank_chunks(query, reranked_chunks, top_k=TOP_K)

    # Recherche classique (seulement si graph-first ET hybrid search n'ont pas fonctionné)
    if not graph_first_succeeded and not hybrid_search_succeeded:
        # Construction du filtre
        must_not_conditions = []
        must_conditions = []

        # Exclure les Q/A RFP si le champ type existe (ancienne collection knowbase)
        # knowbase_chunks_v2 n'a pas ce champ, le filtre est ignoré proprement
        if settings.qdrant_collection == "knowbase":
            must_not_conditions.append(
                FieldCondition(key="type", match=MatchValue(value="rfp_qa"))
            )

        # Ajouter le filtre par solution si spécifié
        if solution:
            must_conditions.append(
                FieldCondition(key="solution.main", match=MatchValue(value=solution))
            )

        query_filter = Filter(
            must_not=must_not_conditions if must_not_conditions else None,
            must=must_conditions if must_conditions else None
        )
        results = qdrant_client.search(
            collection_name=settings.qdrant_collection,
            query_vector=query_vector,
            limit=TOP_K,
            with_payload=True,
            query_filter=query_filter,
        )
        filtered = [r for r in results if r.score >= SCORE_THRESHOLD]
        if not filtered:
            return {
                "status": "no_results",
                "results": [],
                "message": "Aucune information pertinente n'a été trouvée dans la base de connaissance.",
                "graph_first_plan": graph_first_plan.to_dict() if graph_first_plan else None,
            }

        public_url = PUBLIC_URL
        response_chunks = [build_response_payload(r, public_url) for r in filtered]

        # Apply reranking to improve relevance ordering
        reranked_chunks = rerank_chunks(query, response_chunks, top_k=TOP_K)

    # 🧠 Session Entity Resolution: Si session active, chercher chunks via KG
    # pour les entités mentionnées dans le contexte de conversation
    kg_entity_chunks = []
    if session_id and recent_messages and use_graph_context:
        try:
            from .session_entity_resolver import get_session_entity_resolver

            resolver = get_session_entity_resolver(tenant_id)
            kg_entity_chunks = resolver.resolve_and_get_chunks(
                query=query,
                session_messages=recent_messages,
                max_chunks=5  # Max 5 chunks supplémentaires du KG
            )

            if kg_entity_chunks:
                logger.info(
                    f"[SESSION-KG] Found {len(kg_entity_chunks)} chunks via entity resolution"
                )

                # Ajouter les chunks KG aux résultats (avec marqueur kg_source)
                # Les placer en tête car ils sont pertinents pour la question de suivi
                for kg_chunk in kg_entity_chunks:
                    # Éviter les doublons (comparer par texte)
                    is_duplicate = any(
                        chunk.get("text", "")[:100] == kg_chunk.get("text", "")[:100]
                        for chunk in reranked_chunks
                    )
                    if not is_duplicate:
                        reranked_chunks.insert(0, kg_chunk)

                # Limiter le total de chunks
                reranked_chunks = reranked_chunks[:TOP_K + 3]

        except Exception as e:
            logger.warning(f"[SESSION-KG] Entity resolution failed (non-blocking): {e}")

    # 🌊 OSMOSE: Enrichissement Knowledge Graph (Graph-Guided RAG)
    graph_context_text = ""
    graph_context_data = None

    if use_graph_context and graph_enrichment_level != "none":
        try:
            from .graph_guided_search import (
                get_graph_guided_service,
                EnrichmentLevel
            )

            service = get_graph_guided_service()

            # Mapper le niveau d'enrichissement
            level_map = {
                "none": EnrichmentLevel.NONE,
                "light": EnrichmentLevel.LIGHT,
                "standard": EnrichmentLevel.STANDARD,
                "deep": EnrichmentLevel.DEEP,
            }
            enrichment_level = level_map.get(
                graph_enrichment_level.lower(),
                EnrichmentLevel.STANDARD
            )

            # Exécuter l'enrichissement KG de façon synchrone
            loop = asyncio.new_event_loop()
            try:
                graph_context = loop.run_until_complete(
                    service.build_graph_context(
                        query=query,
                        tenant_id=tenant_id,
                        enrichment_level=enrichment_level
                    )
                )
            finally:
                loop.close()

            # Formater le contexte pour le prompt LLM
            graph_context_text = service.format_context_for_synthesis(graph_context)
            graph_context_data = graph_context.to_dict()

            logger.info(
                f"[OSMOSE] Graph context: {len(graph_context.query_concepts)} concepts, "
                f"{len(graph_context.related_concepts)} related, "
                f"{graph_context.processing_time_ms:.1f}ms"
            )

        except Exception as e:
            logger.warning(f"[OSMOSE] Graph enrichment failed (non-blocking): {e}")
            # Continue sans enrichissement KG

    # 🔗 OSMOSE: Traversée multi-hop CHAINS_TO pour raisonnement transitif cross-document
    chain_signals = {}
    if use_kg_traversal and use_graph_context:
        try:
            logger.info(f"[OSMOSE] KG traversal starting for query: {query[:80]}...")
            kg_chains_text, kg_chain_doc_ids, chain_signals = _get_kg_traversal_context(query, tenant_id)
            if kg_chains_text:
                # 1. Injecter le markdown dans le contexte LLM (synthèse reformule en français)
                graph_context_text += "\n\n" + kg_chains_text
                logger.info(
                    f"[OSMOSE] KG traversal: {len(kg_chains_text)} chars context, "
                    f"{len(kg_chain_doc_ids)} chain doc_ids, "
                    f"chain_signals={chain_signals}"
                )

                # 2. Recherche Qdrant ciblée sur les documents de la chaîne
                #    pour trouver les VRAIS chunks riches (pas des claims brutes)
                existing_doc_ids = {
                    c.get("source_file", "").split("/")[-1].replace(".pptx", "").replace(".pdf", "")
                    for c in reranked_chunks
                }
                # Ne chercher que les doc_ids pas déjà couverts par la recherche vectorielle
                new_doc_ids = [
                    did for did in kg_chain_doc_ids
                    if not any(did[:20] in ed for ed in existing_doc_ids if ed)
                ]

                if new_doc_ids:
                    try:
                        kg_doc_filter = Filter(
                            must=[FieldCondition(key="doc_id", match=MatchAny(any=new_doc_ids))]
                        )
                        kg_qdrant_results = qdrant_client.search(
                            collection_name=settings.qdrant_collection,
                            query_vector=query_vector,
                            limit=5,
                            with_payload=True,
                            query_filter=kg_doc_filter,
                        )
                        kg_real_chunks = [
                            build_response_payload(r, PUBLIC_URL)
                            for r in kg_qdrant_results
                            if r.score >= SCORE_THRESHOLD * 0.8  # seuil légèrement assoupli
                        ]
                        # Ajouter les vrais chunks (sans doublons)
                        added = 0
                        for kc in kg_real_chunks:
                            is_dup = any(
                                c.get("text", "")[:80] == kc.get("text", "")[:80]
                                for c in reranked_chunks
                            )
                            if not is_dup:
                                reranked_chunks.append(kc)
                                added += 1
                        if added:
                            logger.info(
                                f"[OSMOSE] KG traversal: added {added} real Qdrant chunks "
                                f"from chain documents {new_doc_ids[:3]}"
                            )
                    except Exception as e:
                        logger.warning(f"[OSMOSE] KG Qdrant lookup failed (non-blocking): {e}")
            else:
                logger.info("[OSMOSE] KG traversal returned no chains")
        except Exception as e:
            logger.warning(f"[OSMOSE] KG traversal failed (non-blocking): {e}")
            import traceback
            logger.debug(f"[OSMOSE] KG traversal traceback: {traceback.format_exc()}")

    # Extraire les signaux KG pour le calcul de confiance
    kg_signals = None
    if graph_context_data:
        kg_signals = {
            "concepts_count": len(graph_context_data.get("query_concepts", [])) +
                              len(graph_context_data.get("related_concepts", [])),
            "relations_count": len(graph_context_data.get("typed_edges", [])),
            "sources_count": len(set(
                edge.get("source_doc_id", "")
                for edge in graph_context_data.get("typed_edges", [])
                if edge.get("source_doc_id")
            )),
            "avg_confidence": sum(
                edge.get("confidence", 0.5)
                for edge in graph_context_data.get("typed_edges", [])
            ) / max(len(graph_context_data.get("typed_edges", [])), 1)
        }
        logger.debug(f"[OSMOSE] KG signals for synthesis: {kg_signals}")

    # Generate synthesized response using LLM (with optional KG and session context)
    synthesis_result = synthesize_response(
        query,
        reranked_chunks,
        graph_context_text,
        session_context_text,
        kg_signals,
        chain_signals=chain_signals
    )

    response = {
        "status": "success",
        "results": reranked_chunks,
        "synthesis": synthesis_result
    }

    # 🎯 OSMOSE Assertion-Centric: Construire la reponse instrumentee si demandee
    if use_instrumented:
        try:
            from .instrumented_answer_builder import build_instrumented_answer

            # Extraire les relations KG confirmées pour booster la classification
            kg_relations = graph_context_data.get("related_concepts", []) if graph_context_data else []

            instrumented_answer, build_metadata = build_instrumented_answer(
                question=query,
                chunks=reranked_chunks,
                language="fr",  # TODO: detecter la langue de la question
                session_context=session_context_text,
                retrieval_stats={
                    "candidates_considered": len(reranked_chunks),
                    "top_k_used": TOP_K,
                    "kg_nodes_touched": len(graph_context_data.get("query_concepts", [])) if graph_context_data else 0,
                    "kg_edges_touched": len(graph_context_data.get("typed_edges", [])) if graph_context_data else 0,
                },
                kg_relations=kg_relations,
            )

            response["instrumented_answer"] = instrumented_answer.model_dump(by_alias=True)
            response["instrumented_metadata"] = build_metadata

            logger.info(
                f"[OSMOSE:Instrumented] Built instrumented answer: "
                f"{len(instrumented_answer.assertions)} assertions, "
                f"FACT={instrumented_answer.truth_contract.facts_count}, "
                f"INFERRED={instrumented_answer.truth_contract.inferred_count}, "
                f"FRAGILE={instrumented_answer.truth_contract.fragile_count}, "
                f"CONFLICT={instrumented_answer.truth_contract.conflict_count}"
            )

        except Exception as e:
            logger.warning(f"[OSMOSE:Instrumented] Failed to build instrumented answer (non-blocking): {e}")
            import traceback
            logger.debug(f"[OSMOSE:Instrumented] Traceback: {traceback.format_exc()}")

    # 🌊 ADR_GRAPH_FIRST Phase C: Ajouter le plan graph-first
    if graph_first_plan:
        response["graph_first_plan"] = graph_first_plan.to_dict()

    # 🌊 Phase 2.12: Ajouter le profil de visibilité actif
    try:
        from .visibility_service import get_visibility_service
        visibility_service = get_visibility_service(tenant_id=tenant_id)
        profile_id = visibility_service.get_profile_for_tenant(tenant_id)
        profile = visibility_service.get_profile(profile_id)
        response["visibility"] = {
            "profile_id": profile_id,
            "profile_name": profile.name,
            "show_maturity_badge": profile.ui.show_maturity_badge,
            "show_confidence": profile.ui.show_confidence,
        }
    except Exception as e:
        logger.warning(f"[VISIBILITY] Could not add visibility info: {e}")

    # Ajouter le contexte KG si disponible
    if graph_context_data:
        response["graph_context"] = graph_context_data

        # 🌊 Phase 3.5: Transformer en graph_data pour D3.js
        try:
            from .graph_data_transformer import transform_graph_context

            # Extraire les concepts utilisés dans la synthèse
            # Les "used concepts" sont les concepts LIÉS (targets des relations)
            # qui supportent la réponse, PAS les query concepts
            related_concepts = graph_context_data.get("related_concepts", [])
            used_concepts = []
            for rel in related_concepts:
                target = rel.get("concept", "")
                if target and target not in used_concepts:
                    used_concepts.append(target)

            # Ajouter aussi les bridge concepts comme "used"
            bridge_concepts = graph_context_data.get("bridge_concepts", [])
            for bc in bridge_concepts:
                if isinstance(bc, dict):
                    name = bc.get("canonical_name") or bc.get("name", "")
                elif isinstance(bc, str):
                    name = bc
                else:
                    continue
                if name and name not in used_concepts:
                    used_concepts.append(name)

            logger.debug(f"[PHASE-3.5] Used concepts for proof: {used_concepts[:5]}...")

            # Transformer en format D3.js (synchrone)
            graph_data = transform_graph_context(
                graph_context_data,
                used_in_synthesis=used_concepts,
                tenant_id=tenant_id
            )
            response["graph_data"] = graph_data
            logger.info(
                f"[PHASE-3.5] Graph data: {len(graph_data.get('nodes', []))} nodes, "
                f"{len(graph_data.get('edges', []))} edges"
            )

            # 🌊 Phase 3.5+: Proof Subgraph pour visualisation ciblée
            try:
                from .proof_subgraph_builder import build_proof_graph

                # Extraire les IDs des concepts depuis graph_data (qui a les bons IDs hash)
                # graph_data contient queryConceptIds et usedConceptIds avec les IDs corrects
                query_concept_ids = graph_data.get("queryConceptIds", [])
                used_concept_ids = graph_data.get("usedConceptIds", [])

                # Fallback: si pas d'IDs dans graph_data, utiliser les noms comme IDs
                if not query_concept_ids:
                    for c in graph_context_data.get("query_concepts", []):
                        if isinstance(c, dict):
                            cid = c.get("canonical_id") or c.get("id", "")
                            if cid:
                                query_concept_ids.append(cid)
                        elif isinstance(c, str) and c:
                            # Chercher l'ID correspondant dans les nodes
                            for node in graph_data.get("nodes", []):
                                if node.get("name", "").lower() == c.lower():
                                    query_concept_ids.append(node.get("id"))
                                    break

                if query_concept_ids or used_concept_ids:
                    proof_graph = build_proof_graph(
                        graph_data=graph_data,
                        query_concept_ids=query_concept_ids,
                        used_concept_ids=used_concept_ids,
                        tenant_id=tenant_id,
                    )
                    response["proof_graph"] = proof_graph
                    logger.info(
                        f"[PHASE-3.5+] Proof graph: {proof_graph.get('stats', {}).get('total_nodes', 0)} nodes, "
                        f"{proof_graph.get('stats', {}).get('total_edges', 0)} edges, "
                        f"{proof_graph.get('stats', {}).get('total_paths', 0)} paths"
                    )
                else:
                    logger.debug("[PHASE-3.5+] No concepts for proof graph, skipping")

            except Exception as e:
                import traceback
                logger.warning(f"[PHASE-3.5+] Proof subgraph building failed (non-blocking): {e}")
                logger.debug(f"[PHASE-3.5+] Traceback: {traceback.format_exc()}")

        except Exception as e:
            logger.warning(f"[PHASE-3.5] Graph data transformation failed (non-blocking): {e}")

        # 🌊 Phase 3.5+: Exploration Intelligence (explications, suggestions, questions)
        try:
            from .exploration_intelligence import get_exploration_service

            exploration_service = get_exploration_service()
            exploration_intelligence = exploration_service.generate_exploration_intelligence(
                query=query,
                synthesis_answer=synthesis_result.get("synthesized_answer", ""),
                graph_context=graph_context_data,
                chunks=reranked_chunks,
                tenant_id=tenant_id,
            )
            response["exploration_intelligence"] = exploration_intelligence.to_dict()
            logger.info(
                f"[PHASE-3.5+] Exploration intelligence: "
                f"{len(exploration_intelligence.concept_explanations)} explanations, "
                f"{len(exploration_intelligence.exploration_suggestions)} suggestions, "
                f"{len(exploration_intelligence.suggested_questions)} questions, "
                f"{len(exploration_intelligence.research_axes)} research axes "
                f"({exploration_intelligence.processing_time_ms:.1f}ms)"
            )

        except Exception as e:
            logger.warning(f"[PHASE-3.5+] Exploration intelligence failed (non-blocking): {e}")

    # 🌊 Answer+Proof: Bloc B - Knowledge Proof Summary
    # NOTE: Execute TOUJOURS, meme sans graph_context_data
    try:
        from .knowledge_proof_service import get_knowledge_proof_service
        from .confidence_engine import DomainSignals

        proof_service = get_knowledge_proof_service()

        # Construire les domain signals depuis le DomainContext
        domain_signals = DomainSignals(
            in_scope_domains=[],  # Sera enrichi si DomainContext disponible
            matched_domains=["default"],  # Assume COVERED par defaut
        )

        # Extraire concepts du graph_context si disponible
        query_concepts = graph_context_data.get("query_concepts", []) if graph_context_data else []
        related_concepts = graph_context_data.get("related_concepts", []) if graph_context_data else []

        knowledge_proof = proof_service.build_proof_summary(
            query_concepts=query_concepts,
            related_concepts=related_concepts,
            sources=synthesis_result.get("sources_used", []),
            tenant_id=tenant_id,
            domain_signals=domain_signals,
        )
        response["knowledge_proof"] = knowledge_proof.to_dict()

        # Ajouter la confiance globale (Bloc A)
        from .confidence_engine import get_confidence_engine
        confidence_engine = get_confidence_engine()
        if knowledge_proof.kg_signals:
            confidence_result = confidence_engine.evaluate(
                knowledge_proof.kg_signals,
                domain_signals
            )
            response["confidence"] = confidence_result.to_dict()

        logger.info(
            f"[ANSWER-PROOF] Knowledge proof: {knowledge_proof.concepts_count} concepts, "
            f"{knowledge_proof.relations_count} relations, "
            f"state={knowledge_proof.epistemic_state.value}"
        )

    except Exception as e:
        logger.warning(f"[ANSWER-PROOF] Knowledge proof failed (non-blocking): {e}")

    # 🌊 Answer+Proof: Bloc C - Reasoning Trace
    # NOTE: Execute TOUJOURS, meme sans graph_context_data
    try:
        from .reasoning_trace_service import build_reasoning_trace_sync

        # Extraire concepts du graph_context si disponible
        focus_concepts = graph_context_data.get("query_concepts", []) if graph_context_data else []
        related_concepts = graph_context_data.get("related_concepts", []) if graph_context_data else []

        reasoning_trace = build_reasoning_trace_sync(
            query=query,
            answer=synthesis_result.get("synthesized_answer", ""),
            focus_concepts=focus_concepts,
            related_concepts=related_concepts,
            tenant_id=tenant_id,
        )
        response["reasoning_trace"] = reasoning_trace.to_dict()
        logger.info(
            f"[ANSWER-PROOF] Reasoning trace: {len(reasoning_trace.steps)} steps, "
            f"coherence={reasoning_trace.coherence_status}"
        )

    except Exception as e:
        logger.warning(f"[ANSWER-PROOF] Reasoning trace failed (non-blocking): {e}")

    # 🌊 Answer+Proof: Bloc D - Coverage Map - DÉSACTIVÉ
    # Raison: Les sub_domains du DomainContext sont définis au setup par l'admin,
    # mais ne correspondent pas forcément aux documents ingérés ensuite.
    # Cela donne une fausse impression de couverture incomplète.
    # À réactiver si on implémente une détection automatique des catégories
    # basée sur le contenu réel du Knowledge Graph.
    #
    # try:
    #     from .coverage_map_service import build_coverage_map_sync
    #     query_concepts = graph_context_data.get("query_concepts", []) if graph_context_data else []
    #     kg_relations = graph_context_data.get("related_concepts", []) if graph_context_data else []
    #     coverage_map = build_coverage_map_sync(
    #         query=query,
    #         query_concepts=query_concepts,
    #         kg_relations=kg_relations,
    #         tenant_id=tenant_id,
    #     )
    #     response["coverage_map"] = coverage_map.to_dict()
    #     logger.info(f"[ANSWER-PROOF] Coverage map: {coverage_map.covered_count}/{coverage_map.total_relevant} domains")
    # except Exception as e:
    #     logger.warning(f"[ANSWER-PROOF] Coverage map failed (non-blocking): {e}")

    return response


def get_available_solutions(
    *,
    qdrant_client: QdrantClient,
    settings: Settings,
) -> list[str]:
    """Récupère la liste des solutions disponibles dans la base Qdrant."""
    # Vérifier si la collection existe
    try:
        collections = qdrant_client.get_collections()
        collection_exists = any(
            col.name == settings.qdrant_collection
            for col in collections.collections
        )
        if not collection_exists:
            return []
    except Exception:
        return []

    # Récupération de tous les points avec la propriété main_solution
    solutions = set()

    try:
        # Utilisation de scroll pour récupérer tous les points avec solution.main
        scroll_result = qdrant_client.scroll(
            collection_name=settings.qdrant_collection,
            limit=1000,  # Limite élevée pour récupérer beaucoup de points
            with_payload=["solution"],
        )
    except Exception:
        # Collection existe mais vide ou erreur de lecture
        return []

    points, next_page_offset = scroll_result

    # Traitement de la première page
    for point in points:
        payload = point.payload or {}
        solution_data = payload.get("solution", {})
        main_solution = solution_data.get("main")
        if isinstance(main_solution, str) and main_solution.strip():
            solutions.add(main_solution.strip())

    # Continuer la pagination si nécessaire
    while next_page_offset is not None:
        scroll_result = qdrant_client.scroll(
            collection_name=settings.qdrant_collection,
            limit=1000,
            with_payload=["solution"],
            offset=next_page_offset
        )
        points, next_page_offset = scroll_result

        for point in points:
            payload = point.payload or {}
            solution_data = payload.get("solution", {})
            main_solution = solution_data.get("main")
            if isinstance(main_solution, str) and main_solution.strip():
                solutions.add(main_solution.strip())

    # Retourner la liste triée
    return sorted(list(solutions))


def _get_kg_traversal_context(query: str, tenant_id: str) -> tuple[str, list[str], dict]:
    """
    Traversée multi-hop CHAINS_TO dans le Knowledge Graph.

    Extrait les entités de la question, cherche les claims liées,
    puis traverse CHAINS_TO (1-3 hops) pour découvrir le raisonnement
    transitif cross-document.

    Retourne:
        - texte markdown formaté à injecter dans le contexte LLM (synthèse)
        - liste de doc_ids des documents traversés par les chaînes
          (pour recherche Qdrant ciblée sur ces documents)
        - signaux de qualité des chaînes (pour scoring de confiance)
    """
    import re
    from neo4j import GraphDatabase
    from knowbase.config.settings import get_settings

    settings = get_settings()

    # 1. Extraire les entités candidates de la question
    # Stratégie : chercher les noms propres/techniques, pas les mots courants

    # Acronymes (ex: "PLM", "ABAP", "BTP", "SAP") — toujours utiles
    acronyms = re.findall(r'\b[A-Z]{2,}(?:\s+[A-Z]{2,})*\b', query)

    # Expressions techniques : acronyme + suite de mots anglais (ex: "PLM for discrete manufacturing")
    # Exige des mots de 3+ lettres après la liaison pour éviter "de", "du", "la", etc.
    technical_phrases = re.findall(
        r'\b([A-Z]{2,}(?:\s+(?:for|of|and|in|on|with)\s+[a-z]\w{2,}(?:\s+[a-z]\w{2,}){0,3})?)\b',
        query
    )

    # Termes capitalisés multi-mots (ex: "SAP HANA", "ABAP Platform")
    capitalized_terms = re.findall(r'\b([A-Z][A-Za-z0-9/\-]+(?:\s+[A-Z][A-Za-z0-9/\-]+)+)\b', query)

    # Combiner et dédupliquer — les plus longs d'abord (plus spécifiques)
    all_terms = technical_phrases + capitalized_terms + acronyms
    stop_words = {"Sur", "Par", "Pour", "Dans", "Des", "Les", "Une", "Que", "En",
                  "Est", "Avec", "The", "For", "And", "With", "SAP"}
    candidates = []
    for term in all_terms:
        term = term.strip()
        if term not in stop_words and len(term) >= 2 and term not in candidates:
            candidates.append(term)

    if not candidates:
        return "", [], {}

    # Limiter à 5 candidats, les plus longs en premier (plus spécifiques)
    candidates = sorted(candidates, key=len, reverse=True)[:5]

    # Éliminer les candidats courts déjà couverts par un candidat plus long
    # Ex: "ERP" est redondant si "SAP Cloud ERP Private Edition" est déjà candidat
    filtered = []
    for c in candidates:
        if any(c != longer and c.lower() in longer.lower() for longer in candidates if len(longer) > len(c)):
            continue
        filtered.append(c)
    candidates = filtered

    logger.info(f"[OSMOSE] KG traversal candidates: {candidates}")

    # 2. Query Cypher : Entity → Claim ABOUT → CHAINS_TO*1..3
    # Priorise les chaînes cross-doc et les entités les plus spécifiques
    cypher = """
    UNWIND $candidates AS candidate
    CALL (candidate) {
        MATCH (e:Entity {tenant_id: $tid})
        WHERE toLower(e.normalized_name) CONTAINS toLower(candidate)
           OR toLower(e.name) CONTAINS toLower(candidate)
           OR any(alias IN coalesce(e.aliases, []) WHERE toLower(alias) CONTAINS toLower(candidate))
        // Prioriser les entités plus spécifiques (noms longs = plus précis)
        WITH e ORDER BY size(e.name) DESC
        LIMIT 5
        MATCH (start_claim:Claim {tenant_id: $tid})-[:ABOUT]->(e)
        WITH start_claim, e
        LIMIT 15
        MATCH path = (start_claim)-[:CHAINS_TO*1..3]->(end_claim:Claim {tenant_id: $tid})
        WITH e.name AS entity_name,
             start_claim.doc_id AS start_doc,
             end_claim.doc_id AS end_doc,
             [rel IN relationships(path) | {
                 cross_doc: rel.cross_doc,
                 join_key: rel.join_key,
                 confidence: rel.confidence
             }] AS chain_rels,
             [node IN nodes(path) | {
                 text: node.text,
                 doc_id: node.doc_id,
                 claim_type: node.claim_type
             }] AS chain_steps,
             length(path) AS hops
        // Compter les docs distincts dans la chaîne
        WITH entity_name, start_doc, end_doc, chain_rels, chain_steps, hops,
             size(apoc.coll.toSet([node IN chain_steps | node.doc_id])) AS distinct_docs
        // Prioriser : 1) plus de docs distincts, 2) cross-doc, 3) hops longs (plus riches)
        ORDER BY
            distinct_docs DESC,
            CASE WHEN any(r IN chain_rels WHERE r.cross_doc = true) THEN 0 ELSE 1 END,
            hops DESC
        LIMIT 5
        RETURN entity_name, chain_steps, chain_rels, hops
    }
    RETURN candidate, entity_name, chain_steps, chain_rels, hops
    LIMIT 15
    """

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password)
    )

    try:
        with driver.session() as session:
            result = session.run(cypher, tid=tenant_id, candidates=candidates)
            records = [dict(r) for r in result]
    finally:
        driver.close()

    if not records:
        return "", [], {}

    # 3. Filtrer : ne garder que les chaînes cross-doc (le vrai apport du KG)
    cross_doc_records = []
    for rec in records:
        steps = rec["chain_steps"]
        docs_in_chain = list(dict.fromkeys(s.get("doc_id", "") for s in steps))
        if len(docs_in_chain) > 1:
            rec["_docs"] = docs_in_chain
            cross_doc_records.append(rec)

    if not cross_doc_records:
        return "", [], {}

    # Helper : doc_id → nom court lisible
    def _short_doc_name(doc_id: str) -> str:
        # "022_Business-Scope-S4HANA-Cloud-Private-Edition-FPS03_cf21e8ba" → "Business Scope S4HANA Cloud Private Edition FPS03"
        parts = doc_id.split("_", 1)
        name = parts[1] if len(parts) > 1 else doc_id
        name = re.sub(r'_[a-f0-9]{8,}$', '', name)  # retirer le hash final
        name = name.replace("-", " ").replace("_", " ").strip()
        # Simplifier les noms trop longs
        name = name.replace("Implementation Best Practices", "Best Practices")
        name = name.replace("incl. clean core environment setup", "clean core")
        return name

    # 4. Formater en markdown (pour le LLM de synthèse) + collecter les doc_ids
    lines = ["## Raisonnement cross-document (Knowledge Graph)\n"]
    lines.append("IMPORTANT : Ces chaînes de faits relient plusieurs documents et révèlent "
                 "des liens architecturaux impossibles à trouver dans un seul document. "
                 "Tu DOIS reformuler ces chaînes dans la langue de la question en expliquant "
                 "clairement la logique transitive : A implique B (source 1), "
                 "qui implique C (source 2), etc.\n")
    seen_chains = set()
    all_chain_doc_ids = set()
    chain_hops_list = []  # hops de chaque chaîne retenue (pour signaux qualité)

    for rec in cross_doc_records:
        steps = rec["chain_steps"]
        hops = rec["hops"]
        entity = rec["entity_name"]
        docs_in_chain = rec["_docs"]

        # Dédupliquer par contenu des étapes
        chain_key = " → ".join(s.get("doc_id", "") + ":" + (s.get("text", "")[:50]) for s in steps)
        if chain_key in seen_chains:
            continue
        seen_chains.add(chain_key)
        chain_hops_list.append(hops)

        # Collecter les doc_ids pour recherche Qdrant ciblée
        for doc_id in docs_in_chain:
            all_chain_doc_ids.add(doc_id)

        # Markdown pour le contexte LLM (synthesis prompt)
        lines.append(f"**Chaîne cross-document ({hops} étapes)** — via {entity}")
        for i, step in enumerate(steps):
            doc = step.get("doc_id", "?")
            text = step.get("text", "").strip()
            short_doc = _short_doc_name(doc)
            prefix = "  →" if i > 0 else "  •"
            lines.append(f"{prefix} {text} *(source: {short_doc})*")
        lines.append("")

    if not all_chain_doc_ids:
        return "", [], {}

    # Signaux de qualité des chaînes pour le scoring de confiance
    chain_signals = {
        "chain_count": len(seen_chains),
        "distinct_docs_count": len(all_chain_doc_ids),
        "max_hops": max(chain_hops_list) if chain_hops_list else 0,
        "avg_hops": sum(chain_hops_list) / len(chain_hops_list) if chain_hops_list else 0,
    }

    return "\n".join(lines), list(all_chain_doc_ids), chain_signals


__all__ = ["search_documents", "get_available_solutions", "TOP_K", "SCORE_THRESHOLD"]
