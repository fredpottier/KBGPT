#!/usr/bin/env python3
"""
Pipeline QS Cross-Doc v2 — Orchestrateur complet.

5 étapes :
0. Candidate gating v2 (déterministe, signaux élargis)
1. LLM comparability gate
2. LLM extraction structurée
3. Dimension mapping v2 (embeddings) + scope resolution v2 (LLM)
4. Persistence

Usage:
    # Dry-run (pas de LLM, gating seulement)
    docker exec knowbase-app python scripts/extract_question_signatures_v2.py --gating-only --sample 500

    # Pipeline complet avec vLLM burst
    docker exec knowbase-app python scripts/extract_question_signatures_v2.py --vllm-url http://IP:8000 --dry-run --sample 100

    # Exécution réelle (embeddings + LLM scope)
    docker exec knowbase-app python scripts/extract_question_signatures_v2.py --vllm-url http://IP:8000 --execute

    # Sans embeddings (mode léger, mapper v1)
    docker exec knowbase-app python scripts/extract_question_signatures_v2.py --vllm-url http://IP:8000 --no-embeddings --execute

    # Sans LLM scope (scope v1)
    docker exec knowbase-app python scripts/extract_question_signatures_v2.py --vllm-url http://IP:8000 --no-llm-scope --execute
"""

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, "/app/src")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("[OSMOSE] qs_pipeline_v2")


@dataclass
class SimpleClaim:
    claim_id: str
    text: str
    doc_id: str
    claim_type: Optional[str] = None
    structured_form: Optional[Dict] = None


def load_claims_sync(client, tenant_id: str, sample: int = 0) -> List[SimpleClaim]:
    """Charge les claims avec entités ABOUT depuis Neo4j (synchrone)."""
    query = """
    MATCH (c:Claim {tenant_id: $tenant_id})
    OPTIONAL MATCH (c)-[:ABOUT]->(e)
    WITH c, collect(DISTINCT e.name) AS entity_names
    RETURN c.claim_id AS claim_id,
           c.text AS text,
           c.doc_id AS doc_id,
           c.claim_type AS claim_type,
           c.structured_form_json AS structured_form_json,
           entity_names
    """
    if sample > 0:
        query += f" LIMIT {sample}"

    with client.driver.session(database=client.database) as session:
        result = session.run(query, tenant_id=tenant_id)
        records = [dict(r) for r in result]

    claims = []
    for rec in records:
        sf = None
        sf_json = rec.get("structured_form_json")
        if sf_json:
            try:
                sf = json.loads(sf_json) if isinstance(sf_json, str) else sf_json
            except (json.JSONDecodeError, TypeError):
                sf = None

        entity_names = rec.get("entity_names") or []
        if entity_names:
            if sf is None:
                sf = {}
            sf["entities"] = [{"name": n} for n in entity_names if n]

        claims.append(SimpleClaim(
            claim_id=rec["claim_id"],
            text=rec.get("text") or "",
            doc_id=rec.get("doc_id") or "",
            claim_type=rec.get("claim_type"),
            structured_form=sf,
        ))
    return claims


def load_doc_contexts_sync(client, tenant_id: str) -> Dict:
    """Charge les DocumentContext depuis Neo4j (synchrone)."""
    from knowbase.claimfirst.models.document_context import DocumentContext

    query = """
    MATCH (dc:DocumentContext {tenant_id: $tenant_id})
    RETURN dc.doc_id AS doc_id, dc.primary_subject AS primary_subject
    """
    with client.driver.session(database=client.database) as session:
        result = session.run(query, tenant_id=tenant_id)
        records = [dict(r) for r in result]

    @dataclass
    class SimpleDocCtx:
        doc_id: str
        primary_subject: Optional[str] = None

    contexts = {}
    for rec in records:
        doc_id = rec.get("doc_id")
        if doc_id:
            contexts[doc_id] = SimpleDocCtx(
                doc_id=doc_id,
                primary_subject=rec.get("primary_subject"),
            )
    return contexts


def load_dimension_registry_sync(client, tenant_id: str) -> List:
    """Charge le registre de QuestionDimension depuis Neo4j (synchrone)."""
    from knowbase.claimfirst.models.question_dimension import QuestionDimension

    query = """
    MATCH (qd:QuestionDimension {tenant_id: $tenant_id})
    WHERE qd.status IN ['candidate', 'validated']
    RETURN properties(qd) AS props
    """
    with client.driver.session(database=client.database) as session:
        result = session.run(query, tenant_id=tenant_id)
        records = [dict(r) for r in result]

    dims = []
    for rec in records:
        props = rec.get("props", {})
        if props:
            try:
                dims.append(QuestionDimension.from_neo4j_record(props))
            except Exception:
                pass
    return dims


def persist_results_sync(client, question_signatures, new_dimensions, tenant_id):
    """Persiste les QS et QuestionDimension dans Neo4j (synchrone)."""
    with client.driver.session(database=client.database) as session:
        # Constraint
        session.run(
            "CREATE CONSTRAINT IF NOT EXISTS FOR (qd:QuestionDimension) "
            "REQUIRE qd.dimension_id IS UNIQUE"
        )

        # QuestionDimensions
        for dim in new_dimensions:
            props = dim.to_neo4j_properties()
            session.run(
                "MERGE (qd:QuestionDimension {dimension_id: $dimension_id}) "
                "SET qd += $props",
                dimension_id=props["dimension_id"],
                props=props,
            )

        # QuestionSignatures
        for qs in question_signatures:
            props = qs.to_neo4j_properties()
            session.run(
                "MERGE (qs:QuestionSignature {qs_id: $qs_id}) "
                "SET qs += $props",
                qs_id=props["qs_id"],
                props=props,
            )
            session.run(
                "MATCH (c:Claim {claim_id: $claim_id}) "
                "MATCH (qs:QuestionSignature {qs_id: $qs_id}) "
                "MERGE (c)-[:HAS_QUESTION_SIG]->(qs)",
                claim_id=qs.claim_id,
                qs_id=qs.qs_id,
            )
            if qs.dimension_id:
                session.run(
                    "MATCH (qs:QuestionSignature {qs_id: $qs_id}) "
                    "MATCH (qd:QuestionDimension {dimension_id: $dim_id}) "
                    "MERGE (qs)-[:ANSWERS]->(qd)",
                    qs_id=qs.qs_id,
                    dim_id=qs.dimension_id,
                )

    logger.info("Persisté: %d QS, %d dimensions", len(question_signatures), len(new_dimensions))


async def run_pipeline(
    dry_run: bool = True,
    gating_only: bool = False,
    sample: int = 0,
    tenant_id: str = "default",
    max_concurrent: int = 5,
    vllm_url: str = None,
    use_embeddings: bool = True,
    use_llm_scope: bool = True,
):
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.claimfirst.extractors.comparability_gate import candidate_gate
    from knowbase.claimfirst.extractors.scope_resolver import resolve_scope, resolve_scope_v2
    from knowbase.claimfirst.extractors.dimension_mapper import map_to_dimension, DimensionMapperV2
    from knowbase.claimfirst.models.question_dimension import QuestionDimension
    from knowbase.claimfirst.models.question_signature import (
        QuestionSignature,
        QSValueType,
        QSExtractionMethod,
    )

    client = get_neo4j_client()

    # ── Chargement ─────────────────────────────────────────────────────
    claims = load_claims_sync(client, tenant_id, sample)
    logger.info("Claims chargées: %d", len(claims))

    doc_contexts = load_doc_contexts_sync(client, tenant_id)
    logger.info("DocumentContexts: %d", len(doc_contexts))

    registry = load_dimension_registry_sync(client, tenant_id)
    logger.info("Dimensions existantes: %d", len(registry))

    # ── Init DimensionMapperV2 (si embeddings activés) ─────────────────
    mapper_v2 = None
    if use_embeddings:
        try:
            mapper_v2 = DimensionMapperV2()
            mapper_v2.preload_registry(registry)
            logger.info("DimensionMapperV2 initialisé avec embeddings")
        except Exception as e:
            logger.warning("DimensionMapperV2 init failed, fallback v1: %s", e)
            mapper_v2 = None

    # ── Étape 0 : Candidate Gating ─────────────────────────────────────
    gating_results = {}
    retained_claims = []
    signal_counter = Counter()

    for claim in claims:
        gr = candidate_gate(claim)
        gating_results[claim.claim_id] = gr
        if gr.retained:
            retained_claims.append(claim)
            for sig in gr.signals:
                signal_counter[sig] += 1

    logger.info("Étape 0 — Gating: %d/%d retenues (%.1f%%)",
                len(retained_claims), len(claims),
                100 * len(retained_claims) / max(len(claims), 1))
    for sig, count in signal_counter.most_common(10):
        logger.info("  %s: %d", sig, count)

    if not retained_claims or gating_only:
        logger.info("Fin (gating only ou aucune claim retenue).")
        return

    # ── Activer burst mode si vLLM URL fournie ─────────────────────────
    if vllm_url:
        from knowbase.common.llm_router import get_llm_router
        router = get_llm_router()
        router.enable_burst_mode(vllm_url)
        logger.info("Burst mode activé: %s", vllm_url)

    # ── Étape 1 : LLM Comparability Gate ───────────────────────────────
    from knowbase.claimfirst.extractors.qs_llm_extractor import (
        llm_comparability_gate,
        llm_extract_qs,
    )

    logger.info("Étape 1 — LLM gate sur %d claims...", len(retained_claims))
    gate_results = await llm_comparability_gate(retained_claims, tenant_id, max_concurrent)

    gate_counter = Counter(label for _, label in gate_results)
    logger.info("Étape 1 — Résultats: %s", dict(gate_counter))

    comparable_ids = {cid for cid, label in gate_results if label == "COMPARABLE_FACT"}
    comparable_claims = [c for c in retained_claims if c.claim_id in comparable_ids]
    logger.info("Étape 1 — %d COMPARABLE_FACT", len(comparable_claims))

    if not comparable_claims:
        logger.info("Aucune claim COMPARABLE. Fin.")
        return

    # ── Étape 2 : LLM Extraction ──────────────────────────────────────
    gating_info_clean = {}
    for c in comparable_claims:
        gr = gating_results.get(c.claim_id)
        signals = gr.signals if gr else []
        gating_info_clean[c.claim_id] = ("COMPARABLE_FACT", signals)

    logger.info("Étape 2 — Extraction LLM sur %d claims...", len(comparable_claims))
    candidates = await llm_extract_qs(
        comparable_claims, doc_contexts, tenant_id, max_concurrent, gating_info_clean,
    )
    logger.info("Étape 2 — %d QSCandidate valides", len(candidates))

    # ── Étape 3 : Dimension mapping + Scope resolution ─────────────────
    new_dimensions = []
    final_qs = []
    scope_counter = Counter()
    match_counter = Counter()
    trace_strategies = Counter()

    for cand in candidates:
        # 3a : Dimension mapping (v2 avec embeddings si dispo, sinon v1)
        if mapper_v2:
            dim_id, score, trace = mapper_v2.map_to_dimension(
                cand.candidate_dimension_key,
                cand.candidate_question,
                cand.value_type,
                cand.operator,
                registry,
            )
            trace_strategies[trace.match_strategy] += 1
        else:
            dim_id, score = map_to_dimension(
                cand.candidate_dimension_key,
                cand.candidate_question,
                cand.value_type,
                cand.operator,
                registry,
            )

        if dim_id:
            match_counter["matched"] += 1
        else:
            dim_id = QuestionDimension.make_id(tenant_id, cand.candidate_dimension_key)
            new_dim = QuestionDimension(
                dimension_id=dim_id,
                dimension_key=cand.candidate_dimension_key,
                canonical_question=cand.candidate_question,
                value_type=cand.value_type,
                allowed_operators=[cand.operator],
                value_comparable="strict" if cand.operator in ("=", ">=", "<=") else "loose",
                tenant_id=tenant_id,
            )
            registry.append(new_dim)
            new_dimensions.append(new_dim)
            match_counter["created"] += 1

        # 3b : Scope resolution (v2 async avec LLM si activé, sinon v1)
        source_claim = next((c for c in comparable_claims if c.claim_id == cand.claim_id), None)
        effective_claim = source_claim or SimpleClaim(claim_id=cand.claim_id, text="", doc_id=cand.doc_id)

        if use_llm_scope and vllm_url:
            scope = await resolve_scope_v2(
                claim=effective_claim,
                scope_evidence=cand.scope_evidence,
                doc_context=doc_contexts.get(cand.doc_id),
                use_llm=True,
            )
        else:
            scope = resolve_scope(
                claim=effective_claim,
                scope_evidence=cand.scope_evidence,
                doc_context=doc_contexts.get(cand.doc_id),
            )
        scope_counter[scope.scope_basis] += 1

        # Construire QS finale
        qs = QuestionSignature(
            qs_id=f"qs_{cand.claim_id}_{cand.candidate_dimension_key[:20]}",
            claim_id=cand.claim_id,
            doc_id=cand.doc_id,
            tenant_id=tenant_id,
            question=cand.candidate_question,
            dimension_key=cand.candidate_dimension_key,
            dimension_id=dim_id,
            canonical_question=cand.candidate_question,
            value_type=QSValueType(cand.value_type),
            extracted_value=cand.value_raw,
            value_normalized=cand.value_normalized,
            operator=cand.operator,
            extraction_method=QSExtractionMethod.LLM_LEVEL_B,
            confidence=cand.confidence,
            gate_label=cand.gate_label,
            gating_signals=cand.gating_signals,
        )
        qs.set_resolved_scope(scope)
        final_qs.append(qs)

    logger.info("Étape 3 — Dimensions: %s", dict(match_counter))
    if trace_strategies:
        logger.info("Étape 3 — Strategies: %s", dict(trace_strategies))
    logger.info("Étape 3 — Scope: %s", dict(scope_counter))
    logger.info("QS finales: %d", len(final_qs))

    # ── Audit ─────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("AUDIT COMPLET")
    logger.info("=" * 60)
    logger.info("Claims total: %d", len(claims))
    logger.info("Gating retenues: %d (%.1f%%)", len(retained_claims),
                100 * len(retained_claims) / max(len(claims), 1))
    logger.info("LLM gate COMPARABLE: %d", len(comparable_claims))
    logger.info("Extraction valides: %d", len(candidates))
    logger.info("QS finales: %d", len(final_qs))
    logger.info("Nouvelles dimensions: %d (total registre: %d)", len(new_dimensions), len(registry))
    logger.info("Mapper: %s", "v2 (embeddings)" if mapper_v2 else "v1 (déterministe)")
    logger.info("Scope: %s", "v2 (LLM)" if (use_llm_scope and vllm_url) else "v1 (cascade)")

    # Exemples
    for qs in final_qs[:5]:
        rs = qs.get_resolved_scope()
        logger.info("  [%s] %s = %s %s (scope: %s, basis: %s)",
                     qs.dimension_key, qs.question, qs.operator, qs.extracted_value,
                     rs.primary_anchor_label if rs else "?",
                     rs.scope_basis if rs else "?")

    # ── Persistence ───────────────────────────────────────────────────
    if dry_run:
        logger.info("DRY RUN — Pas de persistence")
    else:
        persist_results_sync(client, final_qs, new_dimensions, tenant_id)
        logger.info("Persistence terminée.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline QS Cross-Doc v2")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--gating-only", action="store_true", help="Étape 0 seulement (pas de LLM)")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--tenant-id", type=str, default="default")
    parser.add_argument("--max-concurrent", type=int, default=5)
    parser.add_argument("--vllm-url", type=str, default=None, help="URL du vLLM EC2 (ex: http://IP:8000)")
    parser.add_argument("--no-embeddings", action="store_true", help="Désactiver DimensionMapperV2 (fallback v1)")
    parser.add_argument("--no-llm-scope", action="store_true", help="Désactiver scope LLM (fallback v1)")
    args = parser.parse_args()

    asyncio.run(run_pipeline(
        dry_run=not args.execute,
        gating_only=args.gating_only,
        sample=args.sample,
        tenant_id=args.tenant_id,
        max_concurrent=args.max_concurrent,
        vllm_url=args.vllm_url,
        use_embeddings=not args.no_embeddings,
        use_llm_scope=not args.no_llm_scope,
    ))
