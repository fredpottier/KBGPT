from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, HasIdCondition
from sentence_transformers import SentenceTransformer

from knowbase.config.settings import Settings
from knowbase.common.clients import rerank_chunks
from knowbase.common.logging import setup_logging
from .synthesis import synthesize_response
from .retriever import embed_query, retrieve_chunks as _retrieve_chunks
from .kg_signal_detector import detect_signals, SignalReport
from .signal_policy import build_policy


# ---------------------------------------------------------------------------
# ContradictionEnvelope — contrat de sortie pour les tensions KG
# ---------------------------------------------------------------------------

@dataclass
class ContradictionEnvelope:
    """Enveloppe deterministe pour forcer la divulgation des tensions KG.

    Quand requires_disclosure=True, la synthese DOIT mentionner les divergences.
    Si le LLM les ignore, un fallback deterministe est ajoute a la reponse.
    """
    has_tension: bool = False
    requires_disclosure: bool = False
    pairs: list[dict] = field(default_factory=list)
    synthesis_mode: str = "standard"  # "standard" ou "tension_explicit"


def _build_contradiction_envelope(
    kg_claims: list[dict],
    signal_report: SignalReport,
) -> ContradictionEnvelope:
    """Construit un ContradictionEnvelope a partir des claims KG et du signal report.

    Ne fait aucun appel externe — tout est calcule a partir des donnees deja en memoire.
    """
    tension_signal = signal_report.get_signal("tension")
    if not tension_signal:
        return ContradictionEnvelope()

    # Collecter les paires de contradictions depuis les claims
    pairs: list[dict] = []
    for claim in kg_claims:
        contradiction_texts = [t for t in claim.get("contradiction_texts", []) if t]
        if not contradiction_texts:
            continue

        claim_text = claim.get("text", "")
        claim_doc = claim.get("source_file", "")
        if claim_doc:
            claim_doc = claim_doc.split("/")[-1].replace(".pptx", "").replace(".pdf", "")

        for contra_text in contradiction_texts:
            # Les contradiction_texts sont prefixees par le type de relation
            # ex: "⚠ CONTRADICTION: ...", "↻ REFINES: ...", "≈ QUALIFIES: ..."
            axis = "tension"
            clean_text = contra_text
            if contra_text.startswith("⚠ CONTRADICTION:"):
                axis = "contradiction"
                clean_text = contra_text.replace("⚠ CONTRADICTION:", "").strip()
            elif contra_text.startswith("↻ REFINES:"):
                axis = "refinement"
                clean_text = contra_text.replace("↻ REFINES:", "").strip()
            elif contra_text.startswith("≈ QUALIFIES:"):
                axis = "qualification"
                clean_text = contra_text.replace("≈ QUALIFIES:", "").strip()

            # Eviter les doublons exacts
            if any(p["claim_b"] == clean_text and p["claim_a"] == claim_text for p in pairs):
                continue

            pairs.append({
                "claim_a": claim_text,
                "claim_b": clean_text,
                "doc_a": claim_doc or "Source A",
                "doc_b": "Source B",  # Le doc de la claim contradictoire n'est pas dans le query Neo4j
                "axis": axis,
            })

    if not pairs:
        return ContradictionEnvelope()

    return ContradictionEnvelope(
        has_tension=True,
        requires_disclosure=True,
        pairs=pairs[:5],  # Limiter a 5 paires max
        synthesis_mode="tension_explicit",
    )

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
        "_dense_score": payload.get("_dense_score", 0),
        "slide_image_url": slide_image_url,
        # Phase B: axis values pour filtrage version/release
        "axis_release_id": payload.get("axis_release_id"),
        "doc_id": payload.get("doc_id"),
        # Proposition A: chunk_id pour matching exact avec les claims KG
        "chunk_id": payload.get("chunk_id"),
    }


def _search_claims_vector(
    query: str,
    tenant_id: str = "default",
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """
    Phase 4 Bridge — Recherche vectorielle sur les claims Neo4j.

    Utilisé comme alternative au RAG Qdrant en mode TEXT_ONLY.
    Retourne des résultats au format chunk (compatible avec le reste du pipeline).
    """
    try:
        from knowbase.common.clients.embeddings import EmbeddingModelManager
        from knowbase.common.clients.neo4j_client import get_neo4j_client

        # Encoder la question
        emb_manager = EmbeddingModelManager()
        model = emb_manager.get_model()
        embedding = model.encode(f"query: {query}", normalize_embeddings=True).tolist()

        # Vector search Neo4j
        client = get_neo4j_client()
        with client.driver.session(database=client.database) as session:
            result = session.run(
                """
                CALL db.index.vector.queryNodes('claim_embedding', $k, $embedding)
                YIELD node AS c, score
                WHERE score > 0.65 AND c.tenant_id = $tenant_id
                OPTIONAL MATCH (c)-[tension:CONTRADICTS|REFINES|QUALIFIES]-(other:Claim)
                OPTIONAL MATCH (c)-[:ABOUT]->(e:Entity)
                OPTIONAL MATCH (c)-[comp:COMPLEMENTS|EVOLVES_TO|SPECIALIZES]-(complement:Claim)
                WHERE complement.doc_id <> c.doc_id
                WITH c, score,
                     collect(DISTINCT CASE WHEN type(tension) = 'CONTRADICTS' THEN '⚠ CONTRADICTION: ' + coalesce(other.text, '')
                                           WHEN type(tension) = 'REFINES' THEN '↻ REFINES: ' + coalesce(other.text, '')
                                           WHEN type(tension) = 'QUALIFIES' THEN '≈ QUALIFIES: ' + coalesce(other.text, '')
                                           END)[..3] AS contradiction_texts,
                     collect(DISTINCT e.name)[..5] AS entity_names,
                     collect(DISTINCT CASE WHEN complement IS NOT NULL
                         THEN type(comp) + ': ' + coalesce(complement.text, '') END)[..3] AS complement_texts
                RETURN
                    c.claim_id AS chunk_id,
                    c.text AS text,
                    c.doc_id AS source_file,
                    c.verbatim_quote AS verbatim_quote,
                    score,
                    contradiction_texts,
                    entity_names,
                    complement_texts,
                    c.chunk_ids AS chunk_ids
                ORDER BY score DESC
                LIMIT $k
                """,
                tenant_id=tenant_id,
                embedding=embedding,
                k=top_k,
            )

            claims = []
            for r in result:
                claim_chunk = {
                    "text": r["verbatim_quote"] or r["text"],
                    "source_file": r["source_file"] or "",
                    "score": r["score"],
                    "claim_id": r["chunk_id"],
                    "entity_names": r["entity_names"],
                    "contradiction_texts": r["contradiction_texts"],
                    "complement_texts": [t for t in (r["complement_texts"] or []) if t],
                    "chunk_ids": r["chunk_ids"] or [],  # Pont vers Qdrant
                    "source_type": "claim_vector",
                }
                claims.append(claim_chunk)

            return claims

    except Exception as e:
        logger.warning(f"[SEARCH] Claims vector search error: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════
# QuestionDimension matching — cache embeddings + cosine similarity
# ═══════════════════════════════════════════════════════════════════════

def _embed_query(text: str) -> list[float] | None:
    """Embed un texte via le meme modele multilingue que le corpus."""
    try:
        from knowbase.common.clients.embeddings import EmbeddingModelManager
        emb_manager = EmbeddingModelManager()
        model = emb_manager.get_model()
        return model.encode(f"query: {text}", normalize_embeddings=True).tolist()
    except Exception:
        # Fallback TEI burst via Redis state
        try:
            import os, json
            import redis
            tei_url = os.environ.get("TEI_URL", "")
            if not tei_url:
                r = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
                state = r.get("osmose:burst:state")
                if state:
                    tei_url = json.loads(state).get("embeddings_url", "")
            if tei_url:
                import requests as _req
                resp = _req.post(f"{tei_url}/embed", json={"inputs": f"query: {text}"}, timeout=5)
                if resp.status_code == 200:
                    return resp.json()[0]
        except Exception:
            pass
    return None


def _search_via_question_dimensions(
    query: str,
    tenant_id: str,
    qdrant_client: "QdrantClient",
    collection_name: str,
    max_results: int = 10,
) -> List[Dict]:
    """Niveau 1 — QuestionDimension routing.

    Resout la question utilisateur vers une QuestionDimension (question factuelle
    canonique), puis traverse QD → QuestionSignature → Claim → chunk_ids.

    C'est le differenciateur OSMOSIS : au lieu de chercher des chunks par similarite
    vectorielle, on identifie d'abord QUELLE QUESTION FACTUELLE est posee, puis on
    recupere les reponses extraites de chaque document avec leurs preuves.

    Retourne des chunks Qdrant enrichis des metadonnees KG.
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    client = get_neo4j_client()

    with client.driver.session(database=client.database) as session:
        # Matching semantique multilingue via vector index Neo4j
        # Meme modele d'embedding que le corpus (multilingual-e5-large)
        query_embedding = _embed_query(query)
        if query_embedding is None:
            return []

        # Vector search sur les QuestionDimensions (index qd_embedding)
        # puis traversee QD → QS → Claim en une seule requete
        result = session.run(
            """
            CALL db.index.vector.queryNodes('qd_embedding', $top_k, $embedding)
            YIELD node AS qd, score
            WHERE score > $threshold AND qd.tenant_id = $tenant_id

            // Traverser QD → QS → Claim
            MATCH (qs:QuestionSignature)-[:ANSWERS]->(qd)
            MATCH (c:Claim {claim_id: qs.claim_id, tenant_id: $tenant_id})
            OPTIONAL MATCH (c)-[:ABOUT]->(e:Entity)
            OPTIONAL MATCH (c)-[tension:CONTRADICTS|REFINES|QUALIFIES]-(other:Claim)
            OPTIONAL MATCH (c)-[comp:COMPLEMENTS|EVOLVES_TO|SPECIALIZES]-(complement:Claim)
            WHERE complement.doc_id <> c.doc_id

            RETURN
                qd.dimension_key AS dimension_key,
                qd.canonical_question AS canonical_question,
                score AS similarity,
                qs.extracted_value AS extracted_value,
                qs.doc_id AS doc_id,
                c.claim_id AS claim_id,
                c.text AS claim_text,
                c.verbatim_quote AS verbatim,
                c.chunk_ids AS chunk_ids,
                collect(DISTINCT e.name)[..5] AS entity_names,
                collect(DISTINCT CASE
                    WHEN type(tension) = 'CONTRADICTS' THEN 'CONTRADICTION: ' + coalesce(other.text, '')
                    WHEN type(tension) = 'REFINES' THEN 'REFINES: ' + coalesce(other.text, '')
                    WHEN type(tension) = 'QUALIFIES' THEN 'QUALIFIES: ' + coalesce(other.text, '')
                END)[..3] AS contradiction_texts,
                collect(DISTINCT CASE WHEN complement IS NOT NULL
                    THEN type(comp) + ': ' + coalesce(complement.text, '') END)[..3] AS complement_texts
            ORDER BY score DESC, qs.confidence DESC
            LIMIT $max_results
            """,
            embedding=query_embedding,
            top_k=5,
            threshold=0.75,
            tenant_id=tenant_id,
            max_results=max_results,
        )

        qd_claims = [dict(r) for r in result]

    if not qd_claims:
        return []

    logger.info(
        f"[KG-ROUTING:QD] Matched {len(qd_claims)} QS for dimensions: "
        f"{set(c['dimension_key'] for c in qd_claims)}"
    )

    # Construire les claims avec chunk_ids pour _fetch_chunks_for_claims
    claims_for_fetch = []
    for qdc in qd_claims:
        claims_for_fetch.append({
            "text": qdc["verbatim"] or qdc["claim_text"],
            "source_file": qdc["doc_id"],
            "score": qdc["similarity"],
            "claim_id": qdc["claim_id"],
            "entity_names": qdc["entity_names"],
            "contradiction_texts": [t for t in qdc["contradiction_texts"] if t],
            "chunk_ids": qdc["chunk_ids"] or [],
            "source_type": "question_dimension",
            # Metadonnees QD specifiques
            "dimension_key": qdc["dimension_key"],
            "canonical_question": qdc["canonical_question"],
            "extracted_value": qdc["extracted_value"],
        })

    # Fetch les chunks Qdrant pointes par ces claims
    chunks = _fetch_chunks_for_claims(
        qdrant_client=qdrant_client,
        claims=claims_for_fetch,
        collection_name=collection_name,
    )

    # Enrichir chaque chunk avec les metadonnees QD
    for chunk in chunks:
        chunk["source_type"] = "question_dimension"

    return chunks


def _fetch_chunks_for_claims(
    qdrant_client: "QdrantClient",
    claims: List[Dict],
    collection_name: str,
) -> List[Dict]:
    """Claim→Chunk retrieval : recupere les chunks Qdrant exacts pointes par les claims KG.

    Chaque claim a un champ chunk_ids (ex: ["default:DOC_ID:#/texts/44"]) qui pointe
    directement vers le payload chunk_id dans Qdrant. On fetch ces chunks specifiques
    au lieu de faire un vector search aveugle.

    Retourne des chunks au format standard, enrichis des metadonnees KG du claim parent.
    """
    # Collecter tous les chunk_ids uniques
    chunk_id_to_claim: Dict[str, Dict] = {}
    for claim in claims:
        for cid in claim.get("chunk_ids", []):
            if cid and cid not in chunk_id_to_claim:
                chunk_id_to_claim[cid] = claim

    if not chunk_id_to_claim:
        return []

    chunk_ids_list = list(chunk_id_to_claim.keys())

    # Fetch en batches (Qdrant scroll avec MatchAny)
    fetched_chunks = []
    BATCH_SIZE = 50
    for i in range(0, len(chunk_ids_list), BATCH_SIZE):
        batch = chunk_ids_list[i:i + BATCH_SIZE]
        try:
            scroll_result = qdrant_client.scroll(
                collection_name=collection_name,
                scroll_filter=Filter(must=[
                    FieldCondition(key="chunk_id", match=MatchAny(any=batch))
                ]),
                limit=len(batch),
                with_payload=True,
                with_vectors=False,
            )
            points = scroll_result[0] if scroll_result else []

            for point in points:
                payload = point.payload or {}
                cid = payload.get("chunk_id", "")
                parent_claim = chunk_id_to_claim.get(cid, {})

                chunk = {
                    "text": payload.get("text", ""),
                    "source_file": payload.get("doc_id", ""),
                    "doc_id": payload.get("doc_id", ""),
                    "score": parent_claim.get("score", 0.8),  # Score du claim parent
                    "chunk_id": cid,
                    "page_no": payload.get("page_no"),
                    "slide_index": payload.get("slide_index"),
                    "claim_id": parent_claim.get("claim_id", ""),
                    "claim_text": parent_claim.get("text", ""),
                    "entity_names": parent_claim.get("entity_names", []),
                    "contradiction_texts": [t for t in parent_claim.get("contradiction_texts", []) if t],
                    "source_type": "kg_claim_chunk",  # Marqueur : chunk retrouve via KG
                }
                fetched_chunks.append(chunk)

        except Exception as e:
            logger.warning(f"[KG-BRIDGE] Qdrant scroll batch failed: {e}")

    logger.info(
        f"[KG-BRIDGE] Claim→Chunk fetch: {len(fetched_chunks)} chunks from "
        f"{len(chunk_ids_list)} claim chunk_ids ({len(claims)} claims)"
    )
    return fetched_chunks


def _build_kg_findings(
    kg_claims: List[Dict],
    chunks: List[Dict],
) -> List[Dict]:
    """Construit les findings KG comme instructions de lecture (pas contenu narratif).

    INV-ARCH-06 : Le KG diagnostique, il ne raconte pas.
    Le KG ne fournit PAS du contenu semantique concurrent des chunks.
    Il fournit des INSTRUCTIONS DE LECTURE pour le LLM.

    Returns:
        Liste de dicts {"type": str, "instruction": str}
    """
    if not kg_claims:
        return []

    findings = []

    # 1. Tensions detectees (CONTRADICTS, REFINES, QUALIFIES)
    tensions = []
    for claim in kg_claims:
        for t in claim.get("contradiction_texts", []):
            if t and t not in tensions:
                tensions.append(t)

    if tensions:
        findings.append({
            "type": "tension",
            "instruction": (
                "Sources contain DIVERGENT information on this topic. "
                "Present ALL positions explicitly with their sources. "
                "Do NOT collapse into a single consensus answer."
            ),
        })

    # 2. Complements cross-doc (COMPLEMENTS, EVOLVES_TO, SPECIALIZES)
    complements = []
    for claim in kg_claims:
        for t in claim.get("complement_texts", []):
            if t and t not in complements:
                complements.append(t)

    if complements:
        findings.append({
            "type": "cross_doc_complement",
            "instruction": (
                "Other documents provide COMPLEMENTARY information on this topic. "
                "Integrate perspectives from ALL relevant documents to give a complete answer. "
                "Do NOT limit yourself to a single document's view."
            ),
        })

    # 3. Cross-doc discovery (documents absents du RAG mais pertinents)
    chunk_doc_ids = {c.get("doc_id", c.get("source_file", "")) for c in chunks}
    cross_doc_sources = set()
    for claim in kg_claims:
        claim_doc = claim.get("source_file", "")
        if claim_doc and claim_doc not in chunk_doc_ids:
            cross_doc_sources.add(claim_doc)

    if cross_doc_sources:
        doc_names = ", ".join(sorted(cross_doc_sources)[:3])
        findings.append({
            "type": "cross_doc_discovery",
            "instruction": (
                f"Additional documents ({doc_names}) were found via knowledge graph analysis "
                f"but were NOT in the initial search. If their content appears in the sources below, "
                f"compare it explicitly with the primary sources."
            ),
        })

    # 3. Coverage gap (signal detector a detecte des docs manquants)
    # Ceci est gere par le signal_policy, pas ici

    logger.info(
        f"[KG-FINDINGS] {len(findings)} findings: "
        f"tensions={len(tensions)}, complements={len(complements)}, cross_doc={len(cross_doc_sources)}"
    )

    return findings


def _format_kg_findings_as_instructions(findings: List[Dict]) -> str:
    """Formatte les findings KG en instructions de lecture pour le prompt.

    Placees APRES les sources dans le prompt pour eviter l'early commitment bias.
    """
    if not findings:
        return ""

    lines = []
    for f in findings:
        lines.append(f"- {f['instruction']}")

    return "\n## Reading instructions (from document analysis)\n" + "\n".join(lines)


def _build_kg_context_block(
    kg_claims: List[Dict],
    chunks: List[Dict],
) -> str:
    """Wrapper de compatibilite — appelle _build_kg_findings + _format_kg_findings_as_instructions."""
    findings = _build_kg_findings(kg_claims, chunks)
    return _format_kg_findings_as_instructions(findings)


def _enrich_chunks_with_kg(
    chunks: List[Dict],
    kg_claims: List[Dict],
    enrichment_map: Dict[str, Dict],
) -> None:
    """Enrichit les chunks Qdrant avec les metadonnees KG.

    Strategie 2 niveaux (le KG enrichit le RAG, ne le remplace pas) :
    1. Match EXACT par chunk_id (bridge claim→chunk, prioritaire)
    2. Match SAME-DOC : claims du meme doc_id propagent entites et tensions
       aux chunks de ce document (pas de pollution cross-doc)

    Injecte : entity_names, contradiction_texts (REFINES/QUALIFIES/CONTRADICTS), source_type
    """
    # Index niveau 1 : claims par chunk_id (bridge exact)
    claims_by_chunk_id: Dict[str, Dict] = {}
    for claim in kg_claims:
        for cid in claim.get("chunk_ids", []):
            if cid and cid not in claims_by_chunk_id:
                claims_by_chunk_id[cid] = claim

    # Index niveau 2 : claims par doc_id (same-doc fallback)
    claims_by_doc: Dict[str, List[Dict]] = {}
    for claim in kg_claims:
        did = claim.get("doc_id") or claim.get("source_file", "")
        if did:
            claims_by_doc.setdefault(did, []).append(claim)

    enriched_count = 0
    tension_count = 0

    for chunk in chunks:
        chunk_id = chunk.get("chunk_id", "")
        chunk_doc = chunk.get("doc_id") or chunk.get("source_file", "")

        best_claim = None

        # Niveau 1 : match EXACT par chunk_id (bridge)
        if chunk_id and chunk_id in claims_by_chunk_id:
            best_claim = claims_by_chunk_id[chunk_id]

        # Niveau 2 : same-doc — agréger entités et tensions de tous les claims du même doc
        if not best_claim and chunk_doc and chunk_doc in claims_by_doc:
            doc_claims = claims_by_doc[chunk_doc]
            # Agreger les entites et tensions du meme document
            agg_entities = []
            agg_tensions = []
            for dc in doc_claims:
                for e in dc.get("entity_names", []):
                    if e and e not in agg_entities:
                        agg_entities.append(e)
                for t in dc.get("contradiction_texts", []):
                    if t and t not in agg_tensions:
                        agg_tensions.append(t)
            if agg_entities or agg_tensions:
                chunk["entity_names"] = agg_entities[:10]
                chunk["contradiction_texts"] = agg_tensions[:5]
                chunk["source_type"] = "kg_doc_enriched"
                enriched_count += 1
                if agg_tensions:
                    tension_count += 1
                continue

        if not best_claim:
            continue

        # Injecter les enrichissements KG (niveau 1)
        entities = best_claim.get("entity_names", [])
        tensions = [t for t in best_claim.get("contradiction_texts", []) if t]

        if entities or tensions:
            chunk["entity_names"] = entities
            chunk["contradiction_texts"] = tensions
            chunk["source_type"] = "kg_enriched"
            enriched_count += 1
            if tensions:
                tension_count += 1

    # Collecter TOUTES les entites et tensions de tous les claims KG
    all_entities = set()
    all_tensions = []
    for claim in kg_claims:
        for e in claim.get("entity_names", []):
            if e:
                all_entities.add(e)
        for t in claim.get("contradiction_texts", []):
            if t and t not in all_tensions:
                all_tensions.append(t)

    # Stocker les enrichissements globaux sur le premier chunk (sera lu par le post-processing)
    if chunks and (all_entities or all_tensions):
        if "_kg_global" not in chunks[0]:
            chunks[0]["_kg_global"] = {
                "all_entity_names": list(all_entities)[:20],
                "all_tensions": all_tensions[:10],
                "enriched_chunks": enriched_count,
                "tension_chunks": tension_count,
            }

    if enriched_count > 0:
        logger.info(
            f"[KG-ENRICH] Enriched {enriched_count}/{len(chunks)} chunks "
            f"(bridge+same_doc, tensions={tension_count}, entities={len(all_entities)})"
        )


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
    release_id: str | None = None,  # 🔄 Phase B: Filtre par release
    use_latest: bool = True,  # 🔄 Phase B: Boost latest version
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

    # Utiliser la requête enrichie pour l'embedding (delegue a retriever)
    query_vector = embed_query(enriched_query, embedding_model)

    # Signal-driven KG injection : le KG detecte les signaux, le RAG reste pur par defaut
    kg_claim_results = []
    kg_enrichment_map = {}

    if use_graph_context:
        try:
            kg_claim_results = _search_claims_vector(
                query=enriched_query,
                tenant_id=tenant_id,
                top_k=TOP_K,
            )
            if kg_claim_results:
                # Construire le mapping pour enrichissement post-Qdrant
                for claim in kg_claim_results:
                    cid = claim.get("claim_id", "")
                    kg_enrichment_map[cid] = {
                        "entity_names": claim.get("entity_names", []),
                        "contradiction_texts": [t for t in claim.get("contradiction_texts", []) if t],
                        "source_file": claim.get("source_file", ""),
                        "claim_text": claim.get("text", ""),
                        "score": claim.get("score", 0),
                    }
                logger.info(
                    f"[KG-ENRICH] Claims found: {len(kg_claim_results)}, "
                    f"with entities: {sum(1 for c in kg_claim_results if c.get('entity_names'))}, "
                    f"with tensions: {sum(1 for c in kg_claim_results if any(t for t in c.get('contradiction_texts', []) if t))}"
                )
        except Exception as e:
            logger.warning(f"[KG-ENRICH] Claims search failed (non-blocking): {e}")

    # Retrieval Qdrant (RAG pur — invariant, identique pour toutes les questions)
    retrieval_result = _retrieve_chunks(
        question=query,
        query_vector=query_vector,
        qdrant_client=qdrant_client,
        settings=settings,
        top_k=TOP_K,
        score_threshold=SCORE_THRESHOLD,
        solution_filter=solution,
        release_filter=release_id,
    )

    if not retrieval_result.chunks:
        return {
            "status": "no_results",
            "results": [],
            "message": "Aucune information pertinente n'a été trouvée dans la base de connaissance.",
        }

    reranked_chunks = retrieval_result.chunks

    # Phase C light — KG Document Scoping
    # Ajouter des chunks des documents en tension absents du retrieval initial
    if kg_claim_results:
        tension_doc_ids = set()
        for claim in kg_claim_results:
            for tension_text in claim.get("contradiction_texts", []):
                if tension_text:
                    tension_doc_ids.add(claim.get("source_file", ""))

        missing_tension_docs = tension_doc_ids - retrieval_result.docs_involved - {""}
        if not missing_tension_docs:
            claim_doc_ids = set(c.get("source_file", "") for c in kg_claim_results if c.get("source_file"))
            if len(claim_doc_ids) > 1:
                missing_tension_docs = claim_doc_ids - retrieval_result.docs_involved - {""}

        if missing_tension_docs:
            try:
                tension_retrieval = _retrieve_chunks(
                    question=query,
                    query_vector=query_vector,
                    qdrant_client=qdrant_client,
                    settings=settings,
                    top_k=3,
                    score_threshold=SCORE_THRESHOLD * 0.8,
                    doc_filter=list(missing_tension_docs),
                )
                if tension_retrieval.chunks:
                    existing_texts = {c.get("text", "")[:80] for c in reranked_chunks}
                    added = 0
                    for tc in tension_retrieval.chunks:
                        text_key = tc.get("text", "")[:80]
                        if text_key not in existing_texts:
                            reranked_chunks.append(tc)
                            existing_texts.add(text_key)
                            added += 1
                    if added > 0:
                        logger.info(
                            f"[KG-SCOPE] Added {added} chunks from {len(missing_tension_docs)} "
                            f"tension documents: {[d[:30] for d in missing_tension_docs]}"
                        )
            except Exception as e:
                logger.debug(f"[KG-SCOPE] Tension doc search failed (non-blocking): {e}")

    # PROPOSITION A — Enrichissement KG post-Qdrant (conforme PHASE_B doc)
    # INVARIANT : les chunks Qdrant sont IDENTIQUES au RAG. Le KG ne modifie PAS les chunks.
    # Le KG produit un BLOC CONTEXTE SEPARE injecté dans le prompt de synthèse.
    kg_context_block = ""
    if kg_claim_results and reranked_chunks:
        kg_context_block = _build_kg_context_block(kg_claim_results, reranked_chunks)
        # Propager entity_names et contradiction_texts sur les chunks pour le frontend
        # (metadata seulement, pas dans le texte du chunk)
        _enrich_chunks_with_kg(reranked_chunks, kg_claim_results, kg_enrichment_map)

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

    # 🌊 OSMOSE: Enrichissement Knowledge Graph
    # Le KG context block est un bloc séparé, pas mélangé dans les chunks (PHASE_B doc)
    graph_context_text = kg_context_block  # Bloc KG séparé (entités, tensions, supplements)
    graph_context_data = None
    # DÉSACTIVÉ: graph_guided_search dépend de CanonicalConcept + index concept_search
    # + collection osmos_concepts (OSMOSE semantic pipeline) qui n'existent pas en mode
    # ClaimFirst. L'enrichissement KG passe désormais uniquement par le KG traversal
    # CHAINS_TO ci-dessous (Entity → Claim → CHAINS_TO → cross-doc).

    # 🔗 OSMOSE: Traversée multi-hop CHAINS_TO pour raisonnement transitif cross-document
    chain_signals = {}
    if use_kg_traversal:
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

    # 🔄 Phase B.4: LatestSelector boost — préférer la version la plus récente
    if use_latest and not release_id and reranked_chunks:
        try:
            # Extraire les release_ids distincts des chunks
            release_ids_in_results = set()
            for c in reranked_chunks:
                rid = c.get("axis_release_id")
                if rid:
                    release_ids_in_results.add(rid)

            if len(release_ids_in_results) >= 2:
                # Tri numérique simple pour inférer l'ordre
                sorted_releases = sorted(release_ids_in_results, key=lambda x: (
                    # Essayer de parser comme nombre pour tri numérique
                    float(x) if x.replace(".", "").replace("-", "").isdigit() else 0,
                    x  # fallback alphabétique
                ))
                latest_release = sorted_releases[-1]

                # Boost ×1.3 pour les chunks de la release la plus récente
                boosted = 0
                for c in reranked_chunks:
                    if c.get("axis_release_id") == latest_release:
                        c["score"] = c.get("score", 0) * 1.3
                        boosted += 1

                # Re-trier par score
                reranked_chunks.sort(key=lambda c: c.get("score", 0), reverse=True)

                if boosted:
                    logger.info(
                        f"[OSMOSE:LatestBoost] Boosted {boosted} chunks for latest release "
                        f"'{latest_release}' (among {sorted_releases})"
                    )
        except Exception as e:
            logger.warning(f"[OSMOSE:LatestBoost] Failed (non-blocking): {e}")

    # 🔬 QS Cross-Doc: Enrichissement comparaisons cross-document
    qs_crossdoc_text = ""
    qs_crossdoc_data = []
    try:
        qs_crossdoc_text, qs_crossdoc_data = _get_qs_crossdoc_context(query, tenant_id)
        if qs_crossdoc_text:
            graph_context_text += "\n\n" + qs_crossdoc_text
            logger.info(
                f"[QS-CROSSDOC] Injected {len(qs_crossdoc_data)} comparisons into synthesis context"
            )
    except Exception as e:
        logger.warning(f"[QS-CROSSDOC] Failed (non-blocking): {e}")

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

    # Signal-driven KG injection : detecter les signaux puis appliquer la policy
    retrieval_doc_ids = set()
    if reranked_chunks:
        for c in reranked_chunks:
            doc_id = c.get("doc_id", c.get("source_file", ""))
            if doc_id:
                retrieval_doc_ids.add(doc_id)

    signal_report = detect_signals(
        kg_claims=kg_claim_results,
        retrieval_doc_ids=retrieval_doc_ids,
        qs_crossdoc_data=qs_crossdoc_data,
        question=query,
        chunks=reranked_chunks,
    )
    signal_policy = build_policy(signal_report)

    # Ajouter les instructions signal-driven au contexte de synthese
    if signal_policy.synthesis_additions:
        signal_context = "\n".join(f"- {a}" for a in signal_policy.synthesis_additions)
        graph_context_text = f"\n\n## Signal-driven analysis\n{signal_context}" + graph_context_text

    # Signal de confiance retrieval — prevenir le LLM si les chunks sont peu pertinents
    if reranked_chunks:
        chunk_scores = [c.get("score", 0) for c in reranked_chunks if c.get("score")]
        avg_score = sum(chunk_scores) / len(chunk_scores) if chunk_scores else 0
        max_score = max(chunk_scores) if chunk_scores else 0
        if max_score < 0.35:
            graph_context_text += (
                "\n\n## Retrieval confidence WARNING\n"
                "The retrieved sources have LOW relevance scores to this question. "
                "This means the corpus may NOT contain information about this specific topic. "
                "If you cannot find a clear answer in the sources, say so honestly rather than guessing."
            )
            logger.info(f"[RETRIEVAL-CONFIDENCE] Low confidence: avg={avg_score:.3f}, max={max_score:.3f}")

    # Construire le ContradictionEnvelope pour forcer la divulgation des tensions
    contradiction_envelope = _build_contradiction_envelope(kg_claim_results, signal_report)
    if contradiction_envelope.has_tension:
        logger.info(
            f"[ENVELOPE] ContradictionEnvelope built: {len(contradiction_envelope.pairs)} pairs, "
            f"mode={contradiction_envelope.synthesis_mode}"
        )

    # Court-circuit UNANSWERABLE — pas de synthese LLM
    if signal_policy.unanswerable:
        logger.info(f"[SEARCH] UNANSWERABLE — skipping LLM synthesis")
        unanswerable_answer = (
            f"Les documents disponibles ne contiennent pas d'information sur ce sujet specifique. "
            f"{signal_policy.unanswerable_reason} "
            f"Le corpus couvre principalement la documentation technique du domaine "
            f"mais pas les aspects demandes dans cette question."
        )
        return {
            "status": "ok",
            "results": reranked_chunks[:5],
            "synthesis": {
                "synthesized_answer": unanswerable_answer,
                "gate_decision": "UNANSWERABLE",
                "gate_reason": signal_policy.unanswerable_reason,
                "missing_terms": signal_policy.unanswerable_missing_terms,
            },
            "includes_visual_interpretation": False,
            "signal_report": {
                "signals": [{"type": s.type, "strength": s.strength} for s in signal_report.signals],
            },
            "contradiction_envelope": None,
            "visibility": {"chunks_count": len(reranked_chunks)},
            "knowledge_proof": None,
            "confidence": 0.0,
            "reasoning_trace": ["question_context_gap → UNANSWERABLE"],
        }

    # Generate synthesized response + instrumented answer in parallel (if both needed)
    if use_instrumented:
        from .instrumented_answer_builder import build_instrumented_answer

        kg_relations = graph_context_data.get("related_concepts", []) if graph_context_data else []

        def _run_synthesis():
            return synthesize_response(
                query,
                reranked_chunks,
                graph_context_text,
                session_context_text,
                kg_signals,
                chain_signals=chain_signals,
                contradiction_envelope=contradiction_envelope,
            )

        def _run_instrumented():
            return build_instrumented_answer(
                question=query,
                chunks=reranked_chunks,
                language="fr",
                session_context=session_context_text,
                retrieval_stats={
                    "candidates_considered": len(reranked_chunks),
                    "top_k_used": TOP_K,
                    "kg_nodes_touched": len(graph_context_data.get("query_concepts", [])) if graph_context_data else 0,
                    "kg_edges_touched": len(graph_context_data.get("typed_edges", [])) if graph_context_data else 0,
                },
                kg_relations=kg_relations,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            synthesis_future = executor.submit(_run_synthesis)
            instrumented_future = executor.submit(_run_instrumented)

            synthesis_result = synthesis_future.result()

            try:
                instrumented_answer, build_metadata = instrumented_future.result()
            except Exception as e:
                logger.warning(f"[OSMOSE:Instrumented] Failed to build instrumented answer (non-blocking): {e}")
                import traceback
                logger.debug(f"[OSMOSE:Instrumented] Traceback: {traceback.format_exc()}")
                instrumented_answer = None
                build_metadata = None

    else:
        synthesis_result = synthesize_response(
            query,
            reranked_chunks,
            graph_context_text,
            session_context_text,
            kg_signals,
            chain_signals=chain_signals,
            contradiction_envelope=contradiction_envelope,
        )
        instrumented_answer = None
        build_metadata = None

    # Detecter si des chunks contiennent du contenu visuel interprete
    includes_visual_interpretation = any(
        "\u2550\u2550\u2550 VISUAL CONTENT" in (c.get("text", "") or "")
        for c in reranked_chunks
    )

    response = {
        "status": "success",
        "results": reranked_chunks,
        "synthesis": synthesis_result,
        "includes_visual_interpretation": includes_visual_interpretation,
    }

    if instrumented_answer is not None:
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

    # 🔬 QS Cross-Doc: Ajouter les comparaisons dans la réponse
    if qs_crossdoc_data:
        response["cross_doc_comparisons"] = qs_crossdoc_data

    # Signal report dans la reponse (pour debug/frontend)
    if not signal_report.is_silent:
        response["signal_report"] = {
            "signals": [{"type": s.type, "strength": s.strength} for s in signal_report.signals],
            "claims_analyzed": signal_report.claims_analyzed,
        }

    # ContradictionEnvelope dans la reponse (pour debug/frontend)
    if contradiction_envelope.has_tension:
        response["contradiction_envelope"] = {
            "has_tension": True,
            "requires_disclosure": contradiction_envelope.requires_disclosure,
            "pairs_count": len(contradiction_envelope.pairs),
            "synthesis_mode": contradiction_envelope.synthesis_mode,
            # Le champ tension_disclosed est dans synthesis_result["contradiction_envelope"]
            "tension_disclosed": synthesis_result.get("contradiction_envelope", {}).get("tension_disclosed", True),
            "fallback_appended": synthesis_result.get("contradiction_envelope", {}).get("fallback_appended", False),
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

    # 🌊 Atlas Convergence: Chat ↔ Atlas — articles liés + insight hints
    try:
        related_articles = _find_related_articles(query, reranked_chunks, tenant_id)
        if related_articles:
            response["related_articles"] = related_articles
            logger.info(
                f"[ATLAS] Related articles: {len(related_articles)} found "
                f"({', '.join(a['slug'] for a in related_articles)})"
            )

        insight_hints = _generate_insight_hints(
            query, reranked_chunks, related_articles, tenant_id
        )
        if insight_hints:
            response["insight_hints"] = insight_hints
            logger.info(
                f"[ATLAS] Insight hints: {len(insight_hints)} generated "
                f"(types: {', '.join(h['type'] for h in insight_hints)})"
            )
    except Exception as e:
        logger.warning(f"[ATLAS] Convergence failed (non-blocking): {e}")

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


def _find_related_articles(
    question: str,
    reranked_chunks: list[dict[str, Any]],
    tenant_id: str = "default",
) -> list[dict[str, Any]]:
    """
    Atlas Convergence — Trouve les articles Wiki liés aux entités de la réponse.

    Extrait les entity_names depuis les claims/chunks retournés, puis cherche
    les WikiArticle correspondants dans Neo4j. Applique un boost contextuel
    basé sur la présence dans la question et le nombre de claims.
    """
    try:
        from knowbase.common.clients.neo4j_client import get_neo4j_client

        # Collecter les entity_names depuis les chunks (claims vector search)
        entity_names_set: set[str] = set()
        entity_mention_count: dict[str, int] = {}
        for chunk in reranked_chunks:
            names = chunk.get("entity_names", [])
            if isinstance(names, list):
                for name in names:
                    if name:
                        entity_names_set.add(name)
                        entity_mention_count[name] = entity_mention_count.get(name, 0) + 1

        # Fallback : si aucun entity_name dans les chunks (path Qdrant/hybrid),
        # chercher les articles directement depuis la question
        if not entity_names_set:
            client = get_neo4j_client()
            with client.driver.session(database=client.database) as session:
                # Stratégie 1 : match par titre d'article (le plus précis)
                # Chercher si la question contient un titre d'article connu
                title_result = session.run(
                    """
                    MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})
                    WHERE toLower($question) CONTAINS toLower(wa.title)
                    RETURN wa.slug AS slug, wa.title AS title,
                           wa.importance_tier AS importance_tier,
                           wa.importance_score AS importance_score,
                           wa.title AS matched_entity
                    ORDER BY size(wa.title) DESC, wa.importance_score DESC
                    LIMIT 3
                    """,
                    tid=tenant_id,
                    question=question.lower(),
                )
                articles = []
                seen_slugs: set[str] = set()
                for r in title_result:
                    slug = r["slug"]
                    if slug not in seen_slugs:
                        seen_slugs.add(slug)
                        articles.append({
                            "slug": slug,
                            "title": r["title"],
                            "importance_tier": r["importance_tier"] or 3,
                            "matched_entity": r["matched_entity"] or "",
                            "is_recommended": len(articles) == 0,
                        })

                if articles:
                    return articles[:3]

                # Stratégie 2 : match par nom d'entité (fallback)
                # Chercher les entités dont le nom apparaît dans la question
                entity_result = session.run(
                    """
                    MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e:Entity)
                    WHERE toLower($question) CONTAINS toLower(e.name)
                      AND size(e.name) >= 5
                    WITH wa, e, size(e.name) AS name_len
                    ORDER BY name_len DESC, wa.importance_score DESC
                    RETURN DISTINCT wa.slug AS slug, wa.title AS title,
                           wa.importance_tier AS importance_tier,
                           wa.importance_score AS importance_score,
                           e.name AS matched_entity
                    LIMIT 5
                    """,
                    tid=tenant_id,
                    question=question.lower(),
                )
                for r in entity_result:
                    slug = r["slug"]
                    if slug not in seen_slugs:
                        seen_slugs.add(slug)
                        articles.append({
                            "slug": slug,
                            "title": r["title"],
                            "importance_tier": r["importance_tier"] or 3,
                            "matched_entity": r["matched_entity"] or "",
                            "is_recommended": len(articles) == 0,
                        })

                return articles[:3]

        entity_names = list(entity_names_set)
        # Normaliser pour matching flexible
        normalized_names = [n.lower().replace(" ", "_") for n in entity_names]

        client = get_neo4j_client()
        with client.driver.session(database=client.database) as session:
            result = session.run(
                """
                MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e:Entity)
                WHERE e.name IN $entity_names OR e.normalized_name IN $normalized_names
                RETURN wa.slug AS slug, wa.title AS title,
                       wa.importance_tier AS importance_tier,
                       wa.importance_score AS importance_score,
                       e.name AS matched_entity
                ORDER BY wa.importance_score DESC
                LIMIT 5
                """,
                tid=tenant_id,
                entity_names=entity_names,
                normalized_names=normalized_names,
            )

            articles = []
            seen_slugs: set[str] = set()
            question_lower = question.lower()

            for record in result:
                slug = record["slug"]
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                matched = record["matched_entity"] or ""
                # Boost contextuel
                boost = 0.0
                if matched.lower() in question_lower:
                    boost += 2.0
                boost += min(entity_mention_count.get(matched, 0), 3)

                articles.append({
                    "slug": slug,
                    "title": record["title"],
                    "importance_tier": record["importance_tier"] or 3,
                    "matched_entity": matched,
                    "importance_score": (record["importance_score"] or 0) + boost,
                    "is_recommended": False,
                })

            # Trier par score total et limiter à 3
            articles.sort(key=lambda a: a["importance_score"], reverse=True)
            articles = articles[:3]

            # Marquer le premier comme recommandé
            if articles:
                articles[0]["is_recommended"] = True

            # Nettoyer le champ de tri interne
            for a in articles:
                del a["importance_score"]

            return articles

    except Exception as e:
        logger.warning(f"[ATLAS] Related articles lookup failed (non-blocking): {e}")
        return []


def _generate_insight_hints(
    question: str,
    reranked_chunks: list[dict[str, Any]],
    related_articles: list[dict[str, Any]],
    tenant_id: str = "default",
) -> list[dict[str, Any]]:
    """
    Atlas Convergence — Génère des insight hints proactifs.

    Types d'insights :
    1. Contradictions entre claims
    2. Concept structurant (tier 1-2 avec article)
    3. Concepts liés non mentionnés dans la question
    4. Couverture faible (< 2 sources)
    """
    hints: list[dict[str, Any]] = []

    # Collecter claim_ids et entity_names
    claim_ids = [c.get("claim_id") for c in reranked_chunks if c.get("claim_id")]
    entity_names = set()
    for chunk in reranked_chunks:
        names = chunk.get("entity_names", [])
        if isinstance(names, list):
            for n in names:
                if n:
                    entity_names.add(n)

    question_lower = question.lower()
    question_entities = {n for n in entity_names if n.lower() in question_lower}

    # --- 1. Contradictions (filtrées par show_in_chat) ---
    if claim_ids:
        try:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            client = get_neo4j_client()
            with client.driver.session(database=client.database) as session:
                result = session.run(
                    """
                    MATCH (c:Claim)-[r:CONTRADICTS|REFINES|QUALIFIES]-(other:Claim)
                    WHERE c.claim_id IN $claim_ids
                      AND (r.show_in_chat = true OR r.show_in_chat IS NULL)
                      AND (r.tension_level IS NULL OR r.tension_level <> 'none')
                    RETURN c.text AS text_a, other.text AS text_b,
                           c.doc_id AS doc_a, other.doc_id AS doc_b,
                           type(r) AS relation_type,
                           r.tension_nature AS tension_nature,
                           r.tension_level AS tension_level
                    LIMIT 5
                    """,
                    claim_ids=claim_ids,
                )
                for record in result:
                    text_a = (record["text_a"] or "")[:120]
                    text_b = (record["text_b"] or "")[:120]
                    doc_a = (record.get("doc_a") or "")
                    doc_b = (record.get("doc_b") or "")
                    relation_type = record.get("relation_type", "CONTRADICTS")
                    tension_nature = record.get("tension_nature")

                    # Adapter le message selon le type de relation
                    if relation_type == "REFINES":
                        msg = f"Ce point est precise par un autre document : « {text_a} » → « {text_b} »"
                        hint_type = "evolution"
                    elif relation_type == "QUALIFIES":
                        msg = f"Ce point est nuance par un autre document : « {text_a} » vs « {text_b} »"
                        hint_type = "context_nuance"
                    elif tension_nature == "scope_conflict":
                        msg = f"Cette valeur varie selon le contexte : « {text_a} » vs « {text_b} »"
                        hint_type = "context_nuance"
                    elif tension_nature == "temporal_conflict":
                        msg = f"La recommandation a évolué : « {text_a} » vs « {text_b} »"
                        hint_type = "contradiction"
                    else:
                        msg = f"Attention, des documents divergent sur ce point : « {text_a} » vs « {text_b} »"
                        hint_type = "contradiction"

                    # Ajouter les sources si dispo
                    if doc_a and doc_b and doc_a != doc_b:
                        short_a = doc_a.split("_")[1] if "_" in doc_a else doc_a[:30]
                        short_b = doc_b.split("_")[1] if "_" in doc_b else doc_b[:30]
                        msg += f" (sources: {short_a} / {short_b})"

                    hints.append({
                        "type": hint_type,
                        "message": msg,
                        "priority": 1 if relation_type == "CONTRADICTS" else 2,
                    })
        except Exception as e:
            logger.debug(f"[ATLAS:Insights] Contradiction check failed: {e}")

    # --- 2. Concept structurant (article tier 1-2) ---
    for art in related_articles:
        tier = art.get("importance_tier", 3)
        if tier <= 2:
            hints.append({
                "type": "structuring_concept",
                "message": f"Vous devriez aussi regarder {art['title']} — ce concept est central dans ce sujet",
                "priority": 2,
                "action_label": f"Lire l'article {art['title']}",
                "action_href": f"/wiki/{art['slug']}",
            })
            break  # Un seul suffit

    # --- 3. Concepts liés non mentionnés ---
    if claim_ids:
        try:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            client = get_neo4j_client()
            with client.driver.session(database=client.database) as session:
                result = session.run(
                    """
                    MATCH (c:Claim)-[:ABOUT]->(e1:Entity), (c)-[:ABOUT]->(e2:Entity)
                    WHERE c.claim_id IN $claim_ids AND NOT e2.name IN $question_entities
                    WITH e2.name AS name, count(c) AS co_count
                    WHERE co_count >= 2
                    RETURN name, co_count ORDER BY co_count DESC LIMIT 3
                    """,
                    claim_ids=claim_ids,
                    question_entities=list(question_entities),
                )
                for record in result:
                    name = record["name"]
                    hints.append({
                        "type": "related_concept",
                        "message": f"Le concept {name} est fortement lié et pourrait compléter votre analyse",
                        "priority": 3,
                    })
        except Exception as e:
            logger.debug(f"[ATLAS:Insights] Related concepts check failed: {e}")

    # --- 4. Couverture faible ---
    doc_ids = set()
    for chunk in reranked_chunks:
        doc_id = chunk.get("source_file") or chunk.get("doc_id")
        if doc_id:
            doc_ids.add(doc_id)

    if len(doc_ids) < 2:
        hints.append({
            "type": "low_coverage",
            "message": f"Ce point ne repose que sur {len(doc_ids)} source — à vérifier",
            "priority": 3,
        })

    # Trier par priorité et limiter à 3
    hints.sort(key=lambda h: h["priority"])
    return hints[:3]


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
                 join_key: COALESCE(rel.join_key_name, rel.join_key),
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

    # B.3: Requête SAME_CANON_AS pour expansion cross-doc via entités canoniques
    canon_cypher = """
    UNWIND $candidates AS candidate
    MATCH (e:Entity {tenant_id: $tid})
    WHERE toLower(e.normalized_name) CONTAINS toLower(candidate)
       OR toLower(e.name) CONTAINS toLower(candidate)
    WITH e, candidate ORDER BY size(e.name) DESC LIMIT 5
    MATCH (e)-[:SAME_CANON_AS]->(ce:CanonicalEntity)
          <-[:SAME_CANON_AS]-(e2:Entity)
    WHERE e2 <> e
    MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e2)
    WHERE c.doc_id <> e.doc_id AND NOT coalesce(c.archived, false)
    RETURN candidate,
           ce.canonical_name AS canon_name,
           collect(DISTINCT c.doc_id)[..5] AS related_doc_ids,
           collect(DISTINCT {text: c.text, doc_id: c.doc_id, type: c.claim_type})[..8] AS related_claims
    LIMIT 10
    """

    try:
        with driver.session() as session:
            result = session.run(cypher, tid=tenant_id, candidates=candidates)
            records = [dict(r) for r in result]

            # B.3: Exécuter la requête SAME_CANON_AS dans la même session
            canon_result = session.run(canon_cypher, tid=tenant_id, candidates=candidates)
            canon_records = [dict(r) for r in canon_result]
    finally:
        driver.close()

    if not records and not canon_records:
        return "", [], {}

    # 3. Filtrer : ne garder que les chaînes cross-doc (le vrai apport du KG)
    cross_doc_records = []
    for rec in records:
        steps = rec["chain_steps"]
        docs_in_chain = list(dict.fromkeys(s.get("doc_id", "") for s in steps))
        if len(docs_in_chain) > 1:
            rec["_docs"] = docs_in_chain
            cross_doc_records.append(rec)

    if not cross_doc_records and not canon_records:
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

    # B.3: Formater les résultats SAME_CANON_AS (entités canoniques cross-doc)
    if canon_records:
        lines.append("### Cross-doc (entités canoniques)\n")
        for rec in canon_records:
            canon_name = rec.get("canon_name", "?")
            related_doc_ids = rec.get("related_doc_ids", [])
            related_claims = rec.get("related_claims", [])

            if not related_claims:
                continue

            lines.append(f"**{canon_name}** — {len(related_doc_ids)} documents liés")
            for claim in related_claims[:5]:
                text = claim.get("text", "").strip()
                doc = claim.get("doc_id", "?")
                short_doc = _short_doc_name(doc)
                lines.append(f"  • {text} *(source: {short_doc})*")
            lines.append("")

            # Ajouter les doc_ids cross-doc au pool
            for did in related_doc_ids:
                all_chain_doc_ids.add(did)

    if not all_chain_doc_ids:
        return "", [], {}

    # Signaux de qualité des chaînes pour le scoring de confiance
    chain_signals = {
        "chain_count": len(seen_chains),
        "distinct_docs_count": len(all_chain_doc_ids),
        "max_hops": max(chain_hops_list) if chain_hops_list else 0,
        "avg_hops": sum(chain_hops_list) / len(chain_hops_list) if chain_hops_list else 0,
        "canon_expansions": len(canon_records),
    }

    return "\n".join(lines), list(all_chain_doc_ids), chain_signals


def _get_qs_crossdoc_context(query: str, tenant_id: str) -> tuple[str, list[dict]]:
    """
    Enrichissement QS Cross-Doc : trouve les QuestionSignatures pertinentes
    pour la query et retourne les comparaisons cross-doc (évolution, contradiction, accord).

    Stratégie :
    1. Extraire les termes-clés de la query
    2. Chercher les QuestionDimension dont la canonical_question matche
    3. Pour chaque dimension trouvée, charger les QS associées
    4. Comparer les paires et formater en markdown

    Retourne:
        - texte markdown pour injection dans le contexte LLM
        - liste de dicts avec les comparaisons structurées (pour la réponse JSON)
    """
    import re
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    try:
        client = get_neo4j_client()
    except Exception as e:
        logger.warning(f"[QS-CROSSDOC] Neo4j client failed: {e}")
        return "", []

    # 1. Extraire les termes de recherche (mots significatifs 3+ chars)
    stop_words = {
        "les", "des", "une", "que", "pour", "dans", "par", "sur", "avec", "est",
        "sont", "qui", "the", "for", "and", "with", "how", "what", "does", "which",
        "quels", "quelles", "quel", "quelle", "comment", "quoi",
    }
    words = re.findall(r'\b[A-Za-z_/\-]{3,}\b', query)
    search_terms = [w for w in words if w.lower() not in stop_words]

    if not search_terms:
        return "", []

    # 2. Chercher les dimensions pertinentes via full-text sur canonical_question
    #    + les QS liées avec leurs valeurs
    search_pattern = "|".join(re.escape(t) for t in search_terms[:8])

    cypher = """
    MATCH (qd:QuestionDimension {tenant_id: $tid})
    WHERE qd.status <> 'merged'
    AND any(term IN $terms WHERE
        toLower(qd.canonical_question) CONTAINS toLower(term)
        OR toLower(qd.dimension_key) CONTAINS toLower(term)
    )
    WITH qd,
         size([term IN $terms WHERE
             toLower(qd.canonical_question) CONTAINS toLower(term)
             OR toLower(qd.dimension_key) CONTAINS toLower(term)
         ]) AS term_hits
    ORDER BY term_hits DESC, qd.doc_count DESC
    LIMIT 10
    MATCH (qs:QuestionSignature {tenant_id: $tid, dimension_id: qd.dimension_id})
    WHERE qs.confidence >= 0.6
    WITH qd.dimension_key AS dimension_key,
         qd.canonical_question AS canonical_question,
         collect({
             qs_id: qs.qs_id,
             doc_id: qs.doc_id,
             extracted_value: qs.extracted_value,
             value_normalized: qs.value_normalized,
             operator: qs.operator,
             scope_anchor_label: qs.scope_anchor_label,
             confidence: qs.confidence
         }) AS signatures
    RETURN dimension_key, canonical_question, signatures
    ORDER BY size(signatures) DESC
    """

    try:
        with client.driver.session(database=client.database) as session:
            result = session.run(cypher, tid=tenant_id, terms=search_terms[:8])
            records = [dict(r) for r in result]
    except Exception as e:
        logger.warning(f"[QS-CROSSDOC] Neo4j query failed: {e}")
        return "", []

    if not records:
        return "", []

    def _short_name(doc_id: str) -> str:
        """Raccourcit un doc_id pour l'affichage."""
        if not doc_id:
            return "?"
        name = doc_id.replace("_", " ")
        return name[:50] + "…" if len(name) > 50 else name

    # 3. Ranking de pertinence (top 5 comparaisons)
    search_terms_lower = {t.lower() for t in search_terms}

    def _rank_record(rec):
        """Score de pertinence pour trier les dimensions."""
        dim_key = rec["dimension_key"]
        sigs = rec["signatures"]
        # P1 : match terme exact dans dimension_key
        key_match = 1 if any(t in dim_key.lower() for t in search_terms_lower) else 0
        # P2 : nombre de QS
        qs_count = len(sigs)
        # P3 : confiance moyenne
        confidences = [s.get("confidence", 0) or 0 for s in sigs]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0
        return (key_match, qs_count, avg_conf)

    records.sort(key=_rank_record, reverse=True)

    # 4. Analyser les résultats : détecter évolutions, contradictions, accords
    lines = [
        "## Comparaisons cross-document (QuestionSignatures)\n",
        "Cette section présente les **faits comparables** détectés entre documents. "
        "Utilise ces données pour signaler les évolutions, contradictions ou confirmations "
        "entre versions/documents.\n",
    ]
    comparisons_data = []
    displayed_count = 0
    MAX_DISPLAYED = 5

    for rec in records:
        dim_key = rec["dimension_key"]
        canonical_q = rec["canonical_question"]
        sigs = rec["signatures"]

        if len(sigs) < 2:
            continue

        # Confiance moyenne pour affichage
        confidences = [s.get("confidence", 0) or 0 for s in sigs]
        avg_conf = int(100 * sum(confidences) / len(confidences)) if confidences else 0

        # Grouper par scope d'abord pour ne comparer que des QS du même scope
        by_scope = {}
        for s in sigs:
            scope = (s.get("scope_anchor_label") or "general").strip().lower()
            by_scope.setdefault(scope, []).append(s)

        # Analyser chaque groupe de scope séparément
        scope_comparisons = []
        for scope_key, scope_sigs in by_scope.items():
            # Déduplique par (extracted_value, doc_id) pour éviter les doublons
            seen = set()
            deduped = []
            for s in scope_sigs:
                key = (
                    (s.get("extracted_value") or "").strip().lower(),
                    s.get("doc_id", ""),
                )
                if key not in seen:
                    seen.add(key)
                    deduped.append(s)
            scope_sigs = deduped

            by_val = {}
            for s in scope_sigs:
                val = (s.get("value_normalized") or s.get("extracted_value") or "").strip().lower()
                by_val.setdefault(val, []).append(s)

            scope_docs = list({s["doc_id"] for s in scope_sigs if s.get("doc_id")})
            scope_label = scope_sigs[0].get("scope_anchor_label") or "general"

            if len(by_val) == 1 and len(scope_docs) >= 2:
                # Même valeur, même scope, docs différents → ACCORD
                val = list(by_val.keys())[0]
                raw_val = scope_sigs[0].get("extracted_value", val)
                scope_comparisons.append(("AGREEMENT", scope_label, raw_val, None, scope_docs))
            elif len(by_val) >= 2 and len(scope_docs) >= 2:
                # Valeurs différentes, même scope, docs différents → potentielle ÉVOLUTION
                import re as _re
                def _extract_year(doc_id: str) -> int:
                    m = _re.search(r'20\d{2}', doc_id or "")
                    return int(m.group()) if m else 9999

                val_entries = []
                for val, val_sigs_inner in by_val.items():
                    docs = list({s["doc_id"] for s in val_sigs_inner if s.get("doc_id")})
                    min_year = min(_extract_year(d) for d in docs) if docs else 9999
                    raw_val = val_sigs_inner[0].get("extracted_value", val)
                    val_entries.append((raw_val, docs, min_year))
                val_entries.sort(key=lambda x: x[2])

                # Vérifier que oldest et newest sont réellement différents
                old_val_lower = val_entries[0][0].strip().lower() if val_entries[0][0] else ""
                new_val_lower = val_entries[-1][0].strip().lower() if val_entries[-1][0] else ""
                if old_val_lower != new_val_lower:
                    scope_comparisons.append(("EVOLUTION", scope_label, val_entries[0], val_entries[-1], scope_docs))
                else:
                    # Mêmes valeurs brutes malgré normalisation différente → ACCORD
                    raw_val = val_entries[0][0]
                    scope_comparisons.append(("AGREEMENT", scope_label, raw_val, None, scope_docs))
            elif len(by_val) >= 2 and len(scope_docs) == 1:
                # Valeurs différentes, même scope, même doc → CONTRADICTION
                vals = list({vs[0].get("extracted_value", v) for v, vs in by_val.items()})
                if len(vals) >= 2:  # Skip si dédupliqué à 1 valeur
                    scope_comparisons.append(("CONTRADICTION", scope_label, vals, None, scope_docs))

        # Cross-scope : si toutes les valeurs identiques à travers scopes différents → ACCORD global
        all_vals = set()
        for s in sigs:
            val = (s.get("value_normalized") or s.get("extracted_value") or "").strip().lower()
            all_vals.add(val)
        all_docs = list({s["doc_id"] for s in sigs if s.get("doc_id")})

        if not scope_comparisons and len(all_vals) == 1 and len(all_docs) >= 2:
            val = list(all_vals)[0]
            raw_val = sigs[0].get("extracted_value", val)
            if displayed_count < MAX_DISPLAYED:
                doc_labels = [_short_name(d) for d in all_docs[:4]]
                lines.append(f"**✓ ACCORD** — {canonical_q} (confiance: {avg_conf}%)")
                lines.append(f"  Valeur : **{raw_val}** "
                             f"(confirmé dans {len(all_docs)} documents : {', '.join(doc_labels)})")
                lines.append("")
                displayed_count += 1
            comparisons_data.append({
                "type": "AGREEMENT",
                "dimension_key": dim_key,
                "question": canonical_q,
                "value": raw_val,
                "doc_count": len(all_docs),
                "docs": all_docs[:4],
                "avg_confidence": avg_conf,
            })
            continue

        if not scope_comparisons:
            # Scopes différents, valeurs différentes — pas de comparaison fiable
            continue

        # Formatter les comparaisons par scope
        for comp in scope_comparisons:
            if displayed_count >= MAX_DISPLAYED:
                break
            comp_type = comp[0]
            scope_label = comp[1]

            if comp_type == "AGREEMENT":
                raw_val, _, scope_docs = comp[2], comp[3], comp[4]
                doc_labels = [_short_name(d) for d in scope_docs[:3]]
                lines.append(f"**✓ ACCORD** — {canonical_q} (confiance: {avg_conf}%)")
                lines.append(f"  Valeur : **{raw_val}** pour {scope_label} "
                             f"(confirmé dans {len(scope_docs)} documents : {', '.join(doc_labels)})")
                lines.append("")
                displayed_count += 1
                comparisons_data.append({
                    "type": "AGREEMENT",
                    "dimension_key": dim_key,
                    "question": canonical_q,
                    "scope": scope_label,
                    "value": raw_val,
                    "doc_count": len(scope_docs),
                    "docs": scope_docs[:4],
                    "avg_confidence": avg_conf,
                })

            elif comp_type == "EVOLUTION":
                oldest, newest, scope_docs = comp[2], comp[3], comp[4]
                old_val, old_docs, _ = oldest
                new_val, new_docs, _ = newest
                old_doc_str = ", ".join(_short_name(d) for d in old_docs[:2])
                new_doc_str = ", ".join(_short_name(d) for d in new_docs[:2])
                lines.append(f"**↗ ÉVOLUTION** — {canonical_q} (confiance: {avg_conf}%)")
                lines.append(f"  Scope : {scope_label}")
                lines.append(f"  AVANT : **{old_val}** — {old_doc_str}")
                lines.append(f"  APRÈS : **{new_val}** — {new_doc_str}")
                lines.append("")
                displayed_count += 1
                comparisons_data.append({
                    "type": "EVOLUTION",
                    "dimension_key": dim_key,
                    "question": canonical_q,
                    "scope": scope_label,
                    "old_value": old_val,
                    "new_value": new_val,
                    "old_docs": old_docs[:3],
                    "new_docs": new_docs[:3],
                    "avg_confidence": avg_conf,
                })

            elif comp_type == "CONTRADICTION":
                vals, _, scope_docs = comp[2], comp[3], comp[4]
                doc_labels = [_short_name(d) for d in scope_docs[:3]]
                lines.append(f"**⚠ CONTRADICTION** — {canonical_q} (confiance: {avg_conf}%)")
                lines.append(f"  Scope : {scope_label}")
                for v in vals[:4]:
                    lines.append(f"  • **{v}** — {', '.join(doc_labels)}")
                lines.append("")
                displayed_count += 1
                comparisons_data.append({
                    "type": "CONTRADICTION",
                    "dimension_key": dim_key,
                    "question": canonical_q,
                    "scope": scope_label,
                    "values": vals[:4],
                    "docs": scope_docs[:3],
                    "avg_confidence": avg_conf,
                })

    if not comparisons_data:
        return "", []

    if len(comparisons_data) > MAX_DISPLAYED:
        lines.append(f"_({len(comparisons_data) - MAX_DISPLAYED} comparaisons supplémentaires dans les données JSON)_\n")

    logger.info(
        f"[QS-CROSSDOC] Found {len(comparisons_data)} cross-doc comparisons "
        f"(showing top {min(displayed_count, MAX_DISPLAYED)}) "
        f"for query: {query[:60]}..."
    )

    return "\n".join(lines), comparisons_data


__all__ = ["search_documents", "get_available_solutions", "TOP_K", "SCORE_THRESHOLD"]
