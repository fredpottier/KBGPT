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

    # Recherche classique (seulement si hybrid search n'a pas fonctionné)
    if not hybrid_search_succeeded:
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

    # Generate synthesized response using LLM (with optional KG and session context)
    synthesis_result = synthesize_response(
        query,
        reranked_chunks,
        graph_context_text,
        session_context_text
    )

    response = {
        "status": "success",
        "results": reranked_chunks,
        "synthesis": synthesis_result
    }

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
            # (approximation basée sur les concepts de la réponse)
            used_concepts = graph_context_data.get("query_concepts", [])

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

    # 🌊 Answer+Proof: Bloc D - Coverage Map
    # NOTE: Execute TOUJOURS, meme sans graph_context_data
    # Le Coverage Map se base sur la QUESTION, pas sur le KG
    try:
        from .coverage_map_service import build_coverage_map_sync

        # Extraire concepts du graph_context si disponible
        query_concepts = graph_context_data.get("query_concepts", []) if graph_context_data else []
        kg_relations = graph_context_data.get("related_concepts", []) if graph_context_data else []

        coverage_map = build_coverage_map_sync(
            query=query,
            query_concepts=query_concepts,
            kg_relations=kg_relations,
            tenant_id=tenant_id,
        )
        response["coverage_map"] = coverage_map.to_dict()
        logger.info(
            f"[ANSWER-PROOF] Coverage map: {coverage_map.covered_count}/{coverage_map.total_relevant} domains, "
            f"{coverage_map.coverage_percent}% covered"
        )

    except Exception as e:
        logger.warning(f"[ANSWER-PROOF] Coverage map failed (non-blocking): {e}")

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
