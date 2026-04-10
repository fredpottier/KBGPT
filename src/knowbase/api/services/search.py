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


def _summarize_tension_pairs(pairs: list[dict]) -> list[dict]:
    """Genere un resume humain pour chaque paire de tension via un appel LLM.

    Un seul appel batch pour toutes les paires (economie de latence).
    Si le LLM echoue, les paires sont retournees sans resume.
    """
    if not pairs:
        return pairs

    import json as _json

    provider = os.environ.get("OSMOSIS_SYNTHESIS_PROVIDER", "anthropic")
    prompt_lines = [
        "Pour chaque paire de claims ci-dessous, ecris UNE phrase qui explique la divergence de maniere claire et comprehensible pour un non-expert.",
        "Reponds en JSON array avec un objet par paire : [{\"summary\": \"...\"}]",
        ""
    ]
    for i, p in enumerate(pairs):
        prompt_lines.append(f"Paire {i+1}:")
        prompt_lines.append(f"  Document A ({p['doc_a']}): {p['claim_a'][:150]}")
        prompt_lines.append(f"  Document B ({p['doc_b']}): {p['claim_b'][:150]}")
        prompt_lines.append(f"  Type: {p['axis']}")
        prompt_lines.append("")

    prompt = "\n".join(prompt_lines)

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
            model = os.environ.get("OSMOSIS_SYNTHESIS_MODEL", "claude-haiku-4-5-20251001")
            resp = client.messages.create(
                model=model, max_tokens=500, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
        else:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
            model = os.environ.get("OSMOSIS_SYNTHESIS_MODEL", "gpt-4o-mini")
            resp = client.chat.completions.create(
                model=model, max_tokens=500, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content

        # Parser le JSON
        raw = raw.strip()
        if "```" in raw:
            raw = raw.split("```")[1].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        summaries = _json.loads(raw)

        for i, s in enumerate(summaries):
            if i < len(pairs):
                pairs[i]["summary"] = s.get("summary", "")

    except Exception as e:
        logger.warning(f"[TENSION:SUMMARY] LLM summary failed: {e}")

    return pairs


def _clean_source_name_simple(doc_id: str) -> str:
    """Nom lisible court d'un doc_id pour l'UI."""
    import re
    name = doc_id.split("/")[-1]
    name = re.sub(r"_[a-f0-9]{6,}$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^\d{3}_(\d+_)?", "", name)
    name = re.sub(r"\.\w+$", "", name)
    name = name.replace("_", " ").replace("-", " ").strip()
    return re.sub(r"\s+", " ", name) or doc_id


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


def _build_tension_constraints(
    kg_claims: List[Dict],
    signal_report,
    chunks: List[Dict],
) -> str:
    """V3 Mode TENSION : contraintes structurelles courtes (max 3 lignes).

    Le KG ne fournit pas de texte narratif — il emet des regles procedurales
    que le LLM doit suivre pour structurer sa reponse.
    """
    # Identifier les docs en tension
    tension_docs = set()
    tension_topics = []
    for claim in kg_claims:
        for t in claim.get("contradiction_texts", []):
            if t:
                doc_id = claim.get("doc_id") or claim.get("source_file", "")
                if doc_id:
                    tension_docs.add(doc_id)
                # Extraire le sujet de la tension (entites du claim)
                for e in claim.get("entity_names", []):
                    if e and e not in tension_topics:
                        tension_topics.append(e)

    if not tension_docs or len(tension_docs) < 2:
        return ""

    # Noms courts des docs
    doc_names = []
    for d in list(tension_docs)[:2]:
        short = d.split("_", 1)[1] if "_" in d else d
        short = short.replace("_", " ").replace("-", " ")[:40]
        doc_names.append(short)

    topic = tension_topics[0] if tension_topics else "ce sujet"

    # Max 2-3 lignes procedurales
    lines = [
        f"Les documents \"{doc_names[0]}\" et \"{doc_names[1]}\" presentent des positions differentes sur {topic}.",
        "Presente les deux positions separement avec leurs sources.",
    ]
    return "\n".join(lines)


def _build_structured_facts_block(
    qs_crossdoc_data: List[Dict] | None,
    kg_claims: List[Dict],
) -> str:
    """V3 Mode STRUCTURED_FACT : faits structures, 1 par ligne.

    Format machine-stable pour que le LLM reformule sans inventer.
    """
    if not qs_crossdoc_data:
        return ""

    lines = []
    for i, entry in enumerate(qs_crossdoc_data[:8], 1):
        question = entry.get("canonical_question", "")
        comparison_type = entry.get("comparison_type", "")
        docs = entry.get("documents", [])

        for doc in docs[:2]:
            doc_id = doc.get("doc_id", "")
            value = doc.get("extracted_value", "")
            version = doc.get("version", "")
            short_doc = doc_id.split("_", 1)[1].replace("_", " ")[:40] if "_" in doc_id else doc_id
            version_str = f" | Version: {version}" if version else ""
            lines.append(f"FAIT {i}: {question} = {value} | Source: {short_doc}{version_str}")

        if comparison_type:
            lines.append(f"  -> Type: {comparison_type}")

    return "\n".join(lines) if lines else ""


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
    response_mode_override: str | None = None,  # 🎯 V3: Override du mode (admin/benchmark)
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

    # Query Decomposition V2 — detecte comparison/cross-version/enumeration/multi-facettes
    from .query_decomposer import decompose_query, check_plan_integrity, build_integrity_message
    decomposition = decompose_query(enriched_query)

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

    # Multi-facet / comparison retrieval V2 : si la question a ete decomposee,
    # retriever chaque sous-query avec son propre scope_filter (release_id, etc.)
    # puis fusionner les chunks (deduplication par chunk_id, garder le meilleur score)
    plan = decomposition.plan  # QueryPlan V2 (None pour legacy)

    if decomposition.is_decomposed and plan and plan.is_decomposed:
        # V2 path : utiliser les SubQuery avec scope_filter
        seen_chunk_ids = set()
        for chunk in retrieval_result.chunks:
            cid = chunk.get("chunk_id") or chunk.get("id") or id(chunk)
            seen_chunk_ids.add(cid)

        extra_chunks = []
        retrieval_counts: dict[str, int] = {}
        # Tag les chunks initiaux avec leur sub_query_group
        for chunk in retrieval_result.chunks:
            chunk["_sub_query_group"] = plan.sub_queries[0].id if plan.sub_queries else "q0"
        retrieval_counts[plan.sub_queries[0].id if plan.sub_queries else "q0"] = len(retrieval_result.chunks)

        # QD-4 : Retrieval adaptatif — budget et seuil ajustes par sous-query
        ADAPTIVE_MIN_CHUNKS = 3      # seuil pour retry avec budget elargi
        ADAPTIVE_EXPANDED_TOP_K = TOP_K  # budget elargi = budget total
        ADAPTIVE_RELAXED_THRESHOLD = max(SCORE_THRESHOLD - 0.05, 0.50)

        for sq in plan.sub_queries[1:]:  # skip [0] = premiere sous-query (deja fait)
            try:
                # QD-2 : scope_filter domain-agnostic → axis_filters dict
                sq_axis_filters = sq.scope_filter if sq.scope_filter else None

                sub_vector = embed_query(sq.text, embedding_model)
                base_top_k = TOP_K // len(plan.sub_queries)

                sub_result = _retrieve_chunks(
                    question=sq.text,
                    query_vector=sub_vector,
                    qdrant_client=qdrant_client,
                    settings=settings,
                    top_k=base_top_k,
                    score_threshold=SCORE_THRESHOLD,
                    solution_filter=solution,
                    axis_filters=sq_axis_filters,
                    release_filter=release_id if not sq_axis_filters else None,
                )

                # QD-4 : si trop peu de chunks, retry adaptatif
                if len(sub_result.chunks) < ADAPTIVE_MIN_CHUNKS:
                    # Strategie 1 : elargir le budget (plus de chunks)
                    sub_result_expanded = _retrieve_chunks(
                        question=sq.text,
                        query_vector=sub_vector,
                        qdrant_client=qdrant_client,
                        settings=settings,
                        top_k=ADAPTIVE_EXPANDED_TOP_K,
                        score_threshold=ADAPTIVE_RELAXED_THRESHOLD,
                        solution_filter=solution,
                        axis_filters=sq_axis_filters,
                        release_filter=release_id if not sq_axis_filters else None,
                    )
                    if len(sub_result_expanded.chunks) > len(sub_result.chunks):
                        logger.info(
                            f"[DECOMPOSE:ADAPTIVE] {sq.id}: {len(sub_result.chunks)} → "
                            f"{len(sub_result_expanded.chunks)} chunks after expanding "
                            f"(top_k {base_top_k}→{ADAPTIVE_EXPANDED_TOP_K}, "
                            f"threshold {SCORE_THRESHOLD}→{ADAPTIVE_RELAXED_THRESHOLD})"
                        )
                        sub_result = sub_result_expanded

                    # Strategie 2 : si toujours peu ET scope_filter actif, retry sans filtre
                    if len(sub_result.chunks) < ADAPTIVE_MIN_CHUNKS and sq_axis_filters:
                        sub_result_unfiltered = _retrieve_chunks(
                            question=sq.text,
                            query_vector=sub_vector,
                            qdrant_client=qdrant_client,
                            settings=settings,
                            top_k=base_top_k,
                            score_threshold=SCORE_THRESHOLD,
                            solution_filter=solution,
                        )
                        if len(sub_result_unfiltered.chunks) > len(sub_result.chunks):
                            logger.info(
                                f"[DECOMPOSE:ADAPTIVE] {sq.id}: axis_filter removed, "
                                f"{len(sub_result.chunks)} → {len(sub_result_unfiltered.chunks)} chunks"
                            )
                            sub_result = sub_result_unfiltered

                sq_count = 0
                for chunk in sub_result.chunks:
                    cid = chunk.get("chunk_id") or chunk.get("id") or id(chunk)
                    if cid not in seen_chunk_ids:
                        seen_chunk_ids.add(cid)
                        chunk["_sub_query_group"] = sq.id
                        extra_chunks.append(chunk)
                        retrieval_result.docs_involved.add(
                            chunk.get("doc_id", chunk.get("source_file", ""))
                        )
                    sq_count += 1
                retrieval_counts[sq.id] = sq_count

            except Exception as e:
                logger.warning(f"[DECOMPOSE] Sub-query {sq.id} retrieval failed: {e}")
                retrieval_counts[sq.id] = 0

        # Integrity check : verifier que chaque sous-query a des resultats
        plan = check_plan_integrity(plan, retrieval_counts)

        if plan.integrity_issue == "partial_coverage":
            # Clarification interactive : on renvoie le message au lieu de synthetiser
            integrity_msg = build_integrity_message(plan)
            logger.info(f"[DECOMPOSE:INTEGRITY] Partial coverage detected, returning clarification")
            return {
                "status": "clarification_needed",
                "results": retrieval_result.chunks[:5],  # quelques chunks pour contexte
                "synthesis": {"synthesized_answer": integrity_msg},
                "response_mode": "CLARIFICATION",
                "query_plan": {
                    "plan_type": plan.plan_type,
                    "sub_queries": [
                        {"id": sq.id, "text": sq.text, "scope_filter": sq.scope_filter,
                         "chunk_count": sq.chunk_count, "has_results": sq.has_results}
                        for sq in plan.sub_queries
                    ],
                    "integrity_issue": plan.integrity_issue,
                },
            }
        elif plan.integrity_issue == "no_results_at_all":
            integrity_msg = build_integrity_message(plan)
            return {
                "status": "no_results",
                "results": [],
                "synthesis": {"synthesized_answer": integrity_msg},
                "response_mode": "CLARIFICATION",
                "message": integrity_msg,
            }

        if extra_chunks:
            retrieval_result.chunks.extend(extra_chunks)
            retrieval_result.chunks = rerank_chunks(
                query, retrieval_result.chunks, top_k=TOP_K
            )
            logger.info(
                f"[DECOMPOSE:V2] {plan.plan_type} — added {len(extra_chunks)} extra chunks from "
                f"{len(plan.sub_queries) - 1} sub-queries "
                f"(counts: {retrieval_counts}), "
                f"total docs: {len(retrieval_result.docs_involved)}"
            )

        # QD-6 : Chainage iteratif — evaluer si le retrieval est complet
        # et lancer des sous-queries supplementaires si necessaire
        if plan.plan_type in ("comparison", "enumeration", "chronological") and not plan.integrity_issue:
            try:
                from .query_decomposer import evaluate_retrieval_completeness, MAX_ITERATIONS

                for iteration in range(MAX_ITERATIONS):
                    # Construire un resume par sous-query
                    retrieval_summaries = {}
                    for sq in plan.sub_queries:
                        sq_chunks = [c for c in retrieval_result.chunks if c.get("_sub_query_group") == sq.id]
                        if sq_chunks:
                            top_terms = set()
                            for c in sq_chunks[:3]:
                                text = (c.get("text") or "")[:100]
                                top_terms.update(w for w in text.split()[:5] if len(w) > 4)
                            retrieval_summaries[sq.id] = f"{len(sq_chunks)} chunks, topics: {', '.join(list(top_terms)[:5])}"
                        else:
                            retrieval_summaries[sq.id] = "0 chunks"

                    follow_ups = evaluate_retrieval_completeness(
                        query, plan, retrieval_summaries
                    )

                    if not follow_ups:
                        break  # retrieval suffisant

                    # Retriever les follow-ups
                    for sq in follow_ups:
                        try:
                            sq_axis_filters = sq.scope_filter if sq.scope_filter else None
                            fup_vector = embed_query(sq.text, embedding_model)
                            fup_result = _retrieve_chunks(
                                question=sq.text,
                                query_vector=fup_vector,
                                qdrant_client=qdrant_client,
                                settings=settings,
                                top_k=TOP_K // 4,
                                score_threshold=SCORE_THRESHOLD,
                                solution_filter=solution,
                                axis_filters=sq_axis_filters,
                            )
                            for chunk in fup_result.chunks:
                                cid = chunk.get("chunk_id") or chunk.get("id") or id(chunk)
                                if cid not in seen_chunk_ids:
                                    seen_chunk_ids.add(cid)
                                    chunk["_sub_query_group"] = sq.id
                                    retrieval_result.chunks.append(chunk)
                                    retrieval_result.docs_involved.add(
                                        chunk.get("doc_id", chunk.get("source_file", ""))
                                    )
                            plan.sub_queries.append(sq)
                            logger.info(
                                f"[DECOMPOSE:ITERATIVE] iter={iteration+1}, {sq.id}: "
                                f"+{len(fup_result.chunks)} chunks"
                            )
                        except Exception as e:
                            logger.warning(f"[DECOMPOSE:ITERATIVE] {sq.id} failed: {e}")

                    # Re-rank apres ajout des follow-ups
                    retrieval_result.chunks = rerank_chunks(
                        query, retrieval_result.chunks, top_k=TOP_K
                    )
            except Exception as e:
                logger.debug(f"[DECOMPOSE:ITERATIVE] Skipped: {e}")

        # QD-5 : A/B shadow mode — comparer decompose vs mono-query (logging only)
        # On compare le set de doc_ids couverts, pas la qualite des reponses
        try:
            mono_doc_ids = set()
            for chunk in retrieval_result.chunks[:TOP_K]:
                did = chunk.get("doc_id", chunk.get("source_file", ""))
                if did:
                    mono_doc_ids.add(did)
            # Le retrieval initial (avant decomposition) = premiere sous-query
            initial_doc_ids = set()
            for chunk in retrieval_result.chunks:
                if chunk.get("_sub_query_group") == (plan.sub_queries[0].id if plan.sub_queries else ""):
                    did = chunk.get("doc_id", chunk.get("source_file", ""))
                    if did:
                        initial_doc_ids.add(did)
            decomposed_doc_ids = retrieval_result.docs_involved
            new_docs = decomposed_doc_ids - initial_doc_ids
            logger.info(
                f"[DECOMPOSE:AB] Shadow comparison — "
                f"mono_docs={len(initial_doc_ids)}, decomposed_docs={len(decomposed_doc_ids)}, "
                f"new_docs_from_decomposition={len(new_docs)}: {list(new_docs)[:5]}"
            )
        except Exception:
            pass

    elif decomposition.is_decomposed:
        # V1 fallback : sous-queries textuelles sans scope_filter
        seen_chunk_ids = set()
        for chunk in retrieval_result.chunks:
            cid = chunk.get("chunk_id") or chunk.get("id") or id(chunk)
            seen_chunk_ids.add(cid)

        extra_chunks = []
        for sub_query in decomposition.sub_queries[1:]:
            try:
                sub_vector = embed_query(sub_query, embedding_model)
                sub_result = _retrieve_chunks(
                    question=sub_query,
                    query_vector=sub_vector,
                    qdrant_client=qdrant_client,
                    settings=settings,
                    top_k=TOP_K // 2,
                    score_threshold=SCORE_THRESHOLD,
                    solution_filter=solution,
                    release_filter=release_id,
                )
                for chunk in sub_result.chunks:
                    cid = chunk.get("chunk_id") or chunk.get("id") or id(chunk)
                    if cid not in seen_chunk_ids:
                        seen_chunk_ids.add(cid)
                        extra_chunks.append(chunk)
                        retrieval_result.docs_involved.add(
                            chunk.get("doc_id", chunk.get("source_file", ""))
                        )
            except Exception as e:
                logger.warning(f"[DECOMPOSE] Sub-query retrieval failed: {e}")

        if extra_chunks:
            retrieval_result.chunks.extend(extra_chunks)
            retrieval_result.chunks = rerank_chunks(
                query, retrieval_result.chunks, top_k=TOP_K
            )
            logger.info(
                f"[DECOMPOSE:V1] Added {len(extra_chunks)} extra chunks from "
                f"{len(decomposition.sub_queries) - 1} sub-queries, "
                f"total docs: {len(retrieval_result.docs_involved)}"
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
    signal_policy = build_policy(
        signal_report,
        kg_claims=kg_claim_results,
        retrieval_doc_ids=retrieval_doc_ids,
        qs_crossdoc_data=qs_crossdoc_data,
        question=query,
        embedding_model=embedding_model,
    )

    # ══════════════════════════════════════════════════════════════
    # Consultation Perspectives + LLM decisionnel de strategie
    #
    # Les Perspectives sont consultees systematiquement des qu'un sujet
    # est resolu. La decision (direct vs structured) est prise par un LLM
    # informe par la topologie des preuves (strategy_analyzer).
    #
    # Consultation = quasi-systematique (si sujets resolus)
    # Injection = conditionnelle (si LLM dit "structured")
    # ══════════════════════════════════════════════════════════════
    from .signal_policy import ResponseMode

    # Etat des Perspectives consultees (preservees pour reutilisation en aval)
    _perspectives_consulted: list = []
    _perspectives_subject_ids: list = []
    _perspectives_resolution_mode: str = "fallback"
    _strategy_decision = None

    modes_enabled = os.environ.get("OSMOSIS_RESPONSE_MODES", "false").lower() == "true"
    perspective_enabled = os.environ.get("MODE_PERSPECTIVE_ENABLED", "true").lower() == "true"

    # On consulte les Perspectives uniquement si :
    # - les Response Modes V3 sont actifs
    # - le mode PERSPECTIVE est active
    # - le signal_policy a decide DIRECT (pas TENSION / STRUCTURED_FACT)
    if (modes_enabled and perspective_enabled
            and signal_policy.response_mode == ResponseMode.DIRECT):
        try:
            import time as _time
            _persp_start = _time.time()

            from knowbase.perspectives.scorer import (
                resolve_subject_ids_from_claims,
                load_all_perspectives,
                score_perspectives,
            )
            from knowbase.perspectives.strategy_analyzer import analyze_response_strategy
            import asyncio as _asyncio

            # 1. Resoudre les sujets (signal de boost, pas filtre)
            subject_ids, resolution_mode = resolve_subject_ids_from_claims(
                kg_claim_results, tenant_id
            )
            _perspectives_subject_ids = subject_ids
            _perspectives_resolution_mode = resolution_mode

            # 2. Charger TOUTES les Perspectives du tenant (theme-scoped V2)
            #    Le subject_id est utilise comme boost dans le scoring, pas comme filtre.
            _load_start = _time.time()
            perspectives = load_all_perspectives(tenant_id)
            _load_ms = int((_time.time() - _load_start) * 1000)

            if perspectives:
                _score_start = _time.time()
                scored = score_perspectives(
                    question_embedding=query_vector,
                    question=query,
                    perspectives=perspectives,
                    boost_subject_ids=subject_ids,
                )
                _score_ms = int((_time.time() - _score_start) * 1000)
                _perspectives_consulted = scored

                # 3. LLM decisionnel informe
                try:
                    loop = _asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(
                                lambda: _asyncio.new_event_loop().run_until_complete(
                                    analyze_response_strategy(
                                        question=query,
                                        kg_claims=kg_claim_results,
                                        reranked_chunks=reranked_chunks,
                                        scored_perspectives=scored,
                                        subject_ids=subject_ids,
                                        subject_resolution_mode=resolution_mode,
                                    )
                                )
                            )
                            _strategy_decision = future.result(timeout=30)
                    else:
                        _strategy_decision = _asyncio.run(
                            analyze_response_strategy(
                                question=query,
                                kg_claims=kg_claim_results,
                                reranked_chunks=reranked_chunks,
                                scored_perspectives=scored,
                                subject_ids=subject_ids,
                                subject_resolution_mode=resolution_mode,
                            )
                        )
                except RuntimeError:
                    _strategy_decision = _asyncio.run(
                        analyze_response_strategy(
                            question=query,
                            kg_claims=kg_claim_results,
                            reranked_chunks=reranked_chunks,
                            scored_perspectives=scored,
                            subject_ids=subject_ids,
                            subject_resolution_mode=resolution_mode,
                        )
                    )

                _total_persp_ms = int((_time.time() - _persp_start) * 1000)

                logger.info(
                    f"[PERSPECTIVE:COSTS] neo4j_load_ms={_load_ms} "
                    f"scoring_ms={_score_ms} total_ms={_total_persp_ms} "
                    f"perspectives={len(perspectives)}"
                )

                # 4. Appliquer la decision
                if _strategy_decision and _strategy_decision.strategy == "structured":
                    signal_policy.response_mode = ResponseMode.PERSPECTIVE
                    signal_policy.candidate_mode = ResponseMode.PERSPECTIVE
                    signal_policy.response_mode_reason = (
                        f"llm_strategy: {_strategy_decision.reasoning[:100]}"
                    )
                    logger.info(
                        f"[PERSPECTIVE:DECISION] structured "
                        f"(confidence={_strategy_decision.confidence}, "
                        f"llm_ms={_strategy_decision.llm_latency_ms})"
                    )
                else:
                    logger.info(
                        f"[PERSPECTIVE:DECISION] direct "
                        f"(downgraded={_strategy_decision.downgraded if _strategy_decision else False}, "
                        f"veto={_strategy_decision.veto_reason if _strategy_decision else 'none'})"
                    )
            else:
                logger.info("[PERSPECTIVE:CONSULT] no perspectives loaded")

        except Exception as e:
            logger.warning(f"[PERSPECTIVE:CONSULT] Failed (non-blocking): {e}")
            import traceback
            logger.debug(traceback.format_exc())

    # ══════════════════════════════════════════════════════════════
    # V3 Response Mode — branchement du graph_context_text par mode
    # ══════════════════════════════════════════════════════════════
    resolved_mode = signal_policy.response_mode

    # Override admin/benchmark si fourni
    modes_enabled = os.environ.get("OSMOSIS_RESPONSE_MODES", "false").lower() == "true"
    if response_mode_override and modes_enabled:
        try:
            resolved_mode = ResponseMode(response_mode_override)
            logger.info(f"[OSMOSIS:MODE] Override applied: {response_mode_override}")
        except ValueError:
            logger.warning(f"[OSMOSIS:MODE] Invalid override '{response_mode_override}', using auto-detected")

    if resolved_mode == ResponseMode.DIRECT:
        # RAG pur : zero KG dans le prompt
        graph_context_text = ""
        logger.info("[MODE:DIRECT] No KG context injected")

    elif resolved_mode == ResponseMode.AUGMENTED:
        # KG a deja agi via doc expansion (lignes 845-884) et chunk enrichment (ligne 894)
        # Pas de texte KG narratif dans le prompt — le KG agit via les chunks
        graph_context_text = ""
        # Garde-fou : ne pas elargir si RAG deja tres bon
        if reranked_chunks:
            top_score = max((c.get("score", 0) for c in reranked_chunks), default=0)
            if top_score > 0.8:
                logger.info(f"[MODE:AUGMENTED] Top score {top_score:.3f} > 0.8, skipping doc expansion benefit")
        logger.info("[MODE:AUGMENTED] KG acted via chunk selection, no text injected")

    elif resolved_mode == ResponseMode.TENSION:
        # B' doc injection : si l'override a identifie des docs manquants, les injecter maintenant
        logger.info(
            f"[MODE:TENSION:B'] Check: fetch={signal_policy.fetch_missing_tension_docs}, "
            f"tension_doc_ids={[d[:30] for d in signal_policy.tension_doc_ids] if signal_policy.tension_doc_ids else 'empty'}"
        )
        if signal_policy.fetch_missing_tension_docs and signal_policy.tension_doc_ids:
            existing_doc_ids = set(
                c.get("source_file", "") for c in reranked_chunks
            )
            missing_for_tension = signal_policy.tension_doc_ids - existing_doc_ids - {""}
            if missing_for_tension:
                try:
                    tension_inject = _retrieve_chunks(
                        question=query,
                        query_vector=query_vector,
                        qdrant_client=qdrant_client,
                        settings=settings,
                        top_k=3,
                        score_threshold=SCORE_THRESHOLD * 0.5,  # seuil bas pour trouver les chunks
                        doc_filter=list(missing_for_tension),
                    )
                    if tension_inject.chunks:
                        existing_texts = {c.get("text", "")[:80] for c in reranked_chunks}
                        added = 0
                        for tc in tension_inject.chunks:
                            if tc.get("text", "")[:80] not in existing_texts:
                                reranked_chunks.append(tc)
                                existing_texts.add(tc.get("text", "")[:80])
                                added += 1
                        if added:
                            logger.info(
                                f"[MODE:TENSION:B'] Injected {added} chunks from "
                                f"missing tension docs: {[d[:30] for d in missing_for_tension]}"
                            )
                except Exception as e:
                    logger.warning(f"[MODE:TENSION:B'] Doc injection failed: {e}")

        # Contraintes structurelles courtes, pas de texte narratif
        graph_context_text = _build_tension_constraints(
            kg_claim_results, signal_report, reranked_chunks
        )
        logger.info(f"[MODE:TENSION] Constraints injected ({len(graph_context_text)} chars)")

    elif resolved_mode == ResponseMode.STRUCTURED_FACT:
        # Faits structures
        graph_context_text = _build_structured_facts_block(qs_crossdoc_data, kg_claim_results)
        logger.info(f"[MODE:STRUCTURED_FACT] Facts block injected ({len(graph_context_text)} chars)")

    elif resolved_mode == ResponseMode.PERSPECTIVE:
        # Preuves groupees par axes thematiques
        # Reutilise les Perspectives deja consultees/scorees en amont
        # pour eviter un double chargement Neo4j.
        # Phase B6 : on passe query_vector pour permettre le re-ranking
        # des claims dans chaque Perspective selon la similarite a la question.
        try:
            from knowbase.perspectives.runtime import assemble_perspective_context
            graph_context_text, perspective_metadata = assemble_perspective_context(
                question=query,
                scored_perspectives=_perspectives_consulted,
                subject_ids=_perspectives_subject_ids,
                subject_resolution_mode=_perspectives_resolution_mode,
                question_embedding=query_vector,
            )
            if not perspective_metadata.get("activated"):
                # Fallback DIRECT si Perspectives insuffisantes
                graph_context_text = ""
                logger.info(
                    f"[MODE:PERSPECTIVE] Fallback DIRECT: "
                    f"{perspective_metadata.get('fallback_reason', 'unknown')}"
                )
            else:
                logger.info(f"[MODE:PERSPECTIVE] Context injected ({len(graph_context_text)} chars)")
        except Exception as e:
            logger.warning(f"[MODE:PERSPECTIVE] Failed (non-blocking): {e}")
            graph_context_text = ""

    else:
        # Fallback : comportement existant (feature flag off)
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

    # QD-1 : Synthese structuree — contexte groupe par sous-question
    # Au lieu de passer les chunks en vrac, on construit un contexte structure
    # qui aide le synthetiseur a comparer point par point
    if plan and plan.is_decomposed and plan.synthesis_strategy in ("compare", "chronological", "aggregate"):
        # Regrouper les chunks par sous-question grace au tag _sub_query_group
        sq_by_id = {sq.id: sq for sq in plan.sub_queries}
        grouped_sections = []
        ungrouped_chunks = []

        for sq in plan.sub_queries:
            sq_chunks = [c for c in reranked_chunks if c.get("_sub_query_group") == sq.id]
            if sq_chunks:
                label = sq.rationale or sq.text[:80]
                scope_info = ""
                if sq.scope_filter:
                    scope_info = " (" + ", ".join(f"{k}={v}" for k, v in sq.scope_filter.items()) + ")"
                grouped_sections.append(
                    f"=== {sq.id}: {label}{scope_info} ==="
                )

        # Chunks sans tag (retrieval initial avant decomposition)
        n_ungrouped = sum(1 for c in reranked_chunks if not c.get("_sub_query_group"))

        strategy_instructions = {
            "compare": (
                "Structure ta reponse en comparant explicitement les groupes point par point. "
                "Pour chaque aspect, indique ce que dit chaque groupe. "
                "Si un groupe n'a pas d'information sur un aspect, dis-le clairement."
            ),
            "chronological": (
                "Structure ta reponse chronologiquement en montrant l'evolution entre les groupes. "
                "Pour chaque aspect, montre comment il a change d'un groupe a l'autre."
            ),
            "aggregate": (
                "Synthetise les informations de tous les groupes en un tout coherent. "
                "Si des groupes se contredisent ou apportent des nuances, mentionne-le."
            ),
        }

        synthesis_hint = (
            f"\n## Contexte structurel de la question\n"
            f"Cette question a ete decomposee en {len(plan.sub_queries)} sous-questions ({plan.plan_type}).\n"
            f"Les chunks ci-dessous sont groupes par sous-question :\n"
            + "\n".join(f"- {s}" for s in grouped_sections) + "\n"
            + (f"- ({n_ungrouped} chunks non-groupes du retrieval initial)\n" if n_ungrouped else "")
            + f"\n**Instruction** : {strategy_instructions.get(plan.synthesis_strategy, strategy_instructions['compare'])}\n"
        )
        session_context_text = synthesis_hint + session_context_text

        # Trier les chunks pour que le synthetiseur les recoit groupes
        def _sq_sort_key(chunk):
            group = chunk.get("_sub_query_group", "zzz")
            sq_order = {sq.id: i for i, sq in enumerate(plan.sub_queries)}
            return sq_order.get(group, 999)

        reranked_chunks = sorted(reranked_chunks, key=_sq_sort_key)

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
                response_mode=resolved_mode.value if hasattr(resolved_mode, 'value') else str(resolved_mode),
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
            response_mode=resolved_mode.value if hasattr(resolved_mode, 'value') else str(resolved_mode),
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
        "response_mode": resolved_mode.value if hasattr(resolved_mode, 'value') else str(resolved_mode),
        "response_mode_metadata": {
            "candidate_mode": signal_policy.candidate_mode.value if hasattr(signal_policy.candidate_mode, 'value') else "DIRECT",
            "resolved_mode": resolved_mode.value if hasattr(resolved_mode, 'value') else str(resolved_mode),
            "confidence": signal_policy.response_mode_confidence,
            "reason": signal_policy.response_mode_reason,
            "kg_trust_score": signal_policy.kg_trust_score,
            "fallback_to_direct": signal_policy.forced_fallback_to_direct,
        },
    }

    # Exposer le graph_context_text injecte dans le prompt de synthese (piste 2 RAGAS)
    # Permet au benchmark de construire un "faith_total" incluant le KG comme evidence
    if graph_context_text:
        response["graph_context_text"] = graph_context_text

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

    # Query Decomposition V2 : ajouter le plan dans la reponse (observabilite)
    if plan and plan.is_decomposed:
        response["query_plan"] = {
            "plan_type": plan.plan_type,
            "synthesis_strategy": plan.synthesis_strategy,
            "reasoning": plan.reasoning,
            "sub_queries": [
                {"id": sq.id, "text": sq.text, "scope_filter": sq.scope_filter,
                 "rationale": sq.rationale, "chunk_count": sq.chunk_count}
                for sq in plan.sub_queries
            ],
        }

    # ContradictionEnvelope dans la reponse (pour debug/frontend)
    if contradiction_envelope.has_tension:
        tension_pairs = []
        for p in contradiction_envelope.pairs[:5]:
            doc_a = _clean_source_name_simple(p.get("doc_a", ""))
            doc_b = _clean_source_name_simple(p.get("doc_b", ""))
            tension_pairs.append({
                "claim_a": p.get("claim_a", "")[:200],
                "claim_b": p.get("claim_b", "")[:200],
                "doc_a": doc_a,
                "doc_b": doc_b,
                "axis": p.get("axis", "tension"),
                "summary": "",
            })

        # Generer des resumes humains pour les tensions (1 appel LLM batch)
        try:
            tension_pairs = _summarize_tension_pairs(tension_pairs)
        except Exception as e:
            logger.warning(f"[TENSION] Summary generation failed (non-blocking): {e}")

        response["contradiction_envelope"] = {
            "has_tension": True,
            "requires_disclosure": contradiction_envelope.requires_disclosure,
            "pairs_count": len(contradiction_envelope.pairs),
            "synthesis_mode": contradiction_envelope.synthesis_mode,
            "tension_disclosed": synthesis_result.get("contradiction_envelope", {}).get("tension_disclosed", True),
            "fallback_appended": synthesis_result.get("contradiction_envelope", {}).get("fallback_appended", False),
            "pairs": tension_pairs,
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
    lines = ["## Cross-document reasoning (supplementary notes)\n"]
    lines.append("The following fact chains were detected across multiple documents. "
                 "Use them ONLY if relevant to the user's question. Ignore if off-topic.\n")
    seen_chains = set()
    all_chain_doc_ids = set()
    chain_hops_list = []  # hops de chaque chaîne retenue (pour signaux qualité)

    MAX_CHAINS_INJECTED = 3  # Limiter le bruit — seules les 3 premieres chaines cross-doc

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

        # Limiter les chaines injectees dans le prompt (les doc_ids continuent d'etre collectes)
        if len(seen_chains) > MAX_CHAINS_INJECTED:
            for doc_id in docs_in_chain:
                all_chain_doc_ids.add(doc_id)
            continue

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
        for rec in canon_records[:3]:  # Max 3 entites canoniques
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
