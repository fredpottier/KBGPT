#!/usr/bin/env python
"""
p1_phase_timing_probe.py — Chronométrage par-phase de process_and_persist (1 doc).

Patche les méthodes des composants de l'orchestrateur pour mesurer le temps passé dans
CHAQUE phase per-doc (extraction, gates, enrichment, subject indexer, entités,
canonicalisation, facets, clustering, linking, embeddings…). persist OFF.

But : savoir précisément quelle phase coûte → où placer la frontière extraction-only.

    docker exec knowbase-app python scripts/p1_phase_timing_probe.py <doc_id>
"""
from __future__ import annotations

import functools
import os
import sys
import time

TIMES: dict[str, float] = {}


def patch(cls, name, label):
    if cls is None or not hasattr(cls, name):
        print(f"[probe] SKIP {label} ({name} absent)")
        return
    orig = getattr(cls, name)

    @functools.wraps(orig)
    def w(self, *a, **k):
        t = time.perf_counter()
        try:
            return orig(self, *a, **k)
        finally:
            TIMES[label] = TIMES.get(label, 0.0) + (time.perf_counter() - t)
    setattr(cls, name, w)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: p1_phase_timing_probe.py <doc_id>")
    doc_id = sys.argv[1]
    os.environ["CLAIMFIRST_STAGED_PIPELINE"] = "1"
    os.environ.setdefault("CLAIMFIRST_GROUNDING_GATE", "1")

    from knowbase.ingestion.burst.provider_switch import (
        get_burst_state_from_redis, activate_burst_providers, is_burst_mode_active,
    )
    st = get_burst_state_from_redis() or {}
    if st.get("vllm_url"):
        activate_burst_providers(st.get("vllm_url"), st.get("embeddings_url"), st.get("vllm_model"))
    print(f"[probe] burst_active={is_burst_mode_active()}")

    from knowbase.claimfirst.extractors.claim_extractor import ClaimExtractor
    from knowbase.claimfirst.quality import QualityGateRunner
    from knowbase.claimfirst.subject_indexer import SubjectIndexer
    from knowbase.claimfirst.extractors.entity_extractor import EntityExtractor
    from knowbase.claimfirst.extractors.entity_canonicalizer import EntityCanonicalizer
    from knowbase.claimfirst.extractors.facet_candidate_extractor import FacetCandidateExtractor
    from knowbase.claimfirst.linkers.facet_matcher import FacetMatcher
    from knowbase.claimfirst.linkers.entity_linker import EntityLinker
    from knowbase.claimfirst.linkers.passage_linker import PassageLinker
    from knowbase.claimfirst.clustering.claim_clusterer import ClaimClusterer
    from knowbase.claimfirst.composition.slot_enricher import SlotEnricher
    from knowbase.claimfirst.orchestrator import ClaimFirstOrchestrator
    try:
        from knowbase.claimfirst.extractors.noun_chunk_extractor import NounChunkExtractor
    except Exception:
        NounChunkExtractor = None

    patch(ClaimExtractor, "extract", "1_EXTRACTION")
    patch(QualityGateRunner, "run_verifiability_gate", "1.4_verif_gate")
    patch(QualityGateRunner, "run_deterministic_and_atomicity_gates", "1.6_det_gates")
    patch(QualityGateRunner, "run_independence_gate", "2.6_independence")
    patch(SlotEnricher, "enrich", "1.7_slot_enrich")
    patch(SubjectIndexer, "index_claims", "1.8_subject_idx")
    patch(EntityExtractor, "extract_from_claims", "2_entity_extract")
    if NounChunkExtractor:
        patch(NounChunkExtractor, "extract_from_claims", "2.1_nounchunk")
    patch(EntityCanonicalizer, "canonicalize", "2.5_CANONICALIZE")
    patch(FacetCandidateExtractor, "extract", "2.9_facet_extract")
    patch(FacetMatcher, "match", "3_facet_match")
    patch(EntityLinker, "link", "4_entity_link")
    patch(PassageLinker, "link", "4_passage_link")
    patch(ClaimClusterer, "cluster", "5_cluster")
    patch(ClaimFirstOrchestrator, "_generate_embeddings", "5_embeddings")
    patch(ClaimFirstOrchestrator, "_derive_subjects_from_entities", "2.8_derive_subj")
    patch(ClaimFirstOrchestrator, "_run_domain_pack_enrichment", "4.5_domain_pack")
    # Phase 0 (document-level, le « overhead » — investigation (a))
    patch(ClaimFirstOrchestrator, "_create_passages", "0_create_passages")
    patch(ClaimFirstOrchestrator, "_extract_document_context", "0.5_doc_context")
    patch(ClaimFirstOrchestrator, "_validate_new_subjects_llm", "0.5b_validate_subj")
    patch(ClaimFirstOrchestrator, "_resolve_comparable_subject", "0.55_comparable")
    patch(ClaimFirstOrchestrator, "_build_applicability_frame", "0.6_applic_frame")

    from knowbase.claimfirst.worker_job import _get_llm_client, _get_neo4j_driver, _build_cache_map
    from knowbase.stratified.pass0.cache_loader import load_pass0_from_cache

    orch = ClaimFirstOrchestrator(
        llm_client=_get_llm_client(), neo4j_driver=_get_neo4j_driver(),
        tenant_id="default", persist_enabled=False,
    )
    cache_path = _build_cache_map("/data/extraction_cache").get(doc_id)
    if not cache_path:
        raise SystemExit(f"pas de cache pour {doc_id}")
    cr = load_pass0_from_cache(cache_path, "default")

    t0 = time.perf_counter()
    orch.process_and_persist(doc_id=doc_id, cache_result=cr, tenant_id="default")
    wall = time.perf_counter() - t0

    print(f"\n=== PHASE TIMING {doc_id} | wall={wall:.0f}s (persist OFF) ===")
    for k, v in sorted(TIMES.items(), key=lambda x: -x[1]):
        print(f"  {v:7.1f}s ({100*v/wall:4.1f}%)  {k}")
    measured = sum(TIMES.values())
    print(f"  {wall-measured:7.1f}s ({100*(wall-measured)/max(wall,1):4.1f}%)  [autres/overhead non patché]")


if __name__ == "__main__":
    main()
