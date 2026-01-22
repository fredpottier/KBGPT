from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, HasIdCondition
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
    # Priorité: document.source_file_url > payload.source_file_url > payload.document_name
    source_file_url = (
        document.get("source_file_url") or
        payload.get("source_file_url") or
        payload.get("document_name", "")  # Fallback vers document_name (nouvelle structure OSMOSE)
    )
    slide_image_url = document.get("slide_image_url") or payload.get("slide_image_url", "")
    slide_index = chunk.get("slide_index") or payload.get("slide_index", "")

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

                # 🔑 Enrichir la requête vectorielle avec le contexte
                # Récupérer le dernier message assistant pour contexte thématique
                last_assistant_msg = None
                for msg in reversed(recent_messages):
                    if msg.role == "assistant":
                        last_assistant_msg = msg.content
                        break

                if last_assistant_msg:
                    # Extraire les premiers 200 caractères du contexte pour enrichir la recherche
                    context_snippet = last_assistant_msg[:200].replace("\n", " ")
                    enriched_query = f"{query} {context_snippet}"
                    logger.info(f"[MEMORY] Query enriched with session context")

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
        # Construction du filtre de base (pour recherche classique)
        filter_conditions = [FieldCondition(key="type", match=MatchValue(value="rfp_qa"))]

        # Ajouter le filtre par solution si spécifié
        must_conditions = []
        if solution:
            must_conditions.append(
                FieldCondition(key="solution.main", match=MatchValue(value=solution))
            )

        query_filter = Filter(
            must_not=filter_conditions,
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
        kg_signals
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


__all__ = ["search_documents", "get_available_solutions", "TOP_K", "SCORE_THRESHOLD"]
