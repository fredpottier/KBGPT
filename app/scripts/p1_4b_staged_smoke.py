#!/usr/bin/env python
"""
p1_4b_staged_smoke.py — Smoke intégré P1.4-bis : pipeline staged (Sélection -> Décomposition
-> Grounding) vs legacy (méga-prompt), de bout en bout via ClaimExtractor.extract(), sur de
vrais passages et le LLM réel (router KNOWLEDGE_EXTRACTION = DeepInfra si burst off).

Attendu :
- Énumération catalogue : LEGACY sur-décompose (N claims) ; STAGED -> 1 claim avec la liste.
- Boilerplate juridique : STAGED le jette (Stage A) ; LEGACY le garde.
- Faits + identifiants : conservés ; grounding flag marginal si identifiant non ancré.

Usage:
    docker compose exec app python scripts/p1_4b_staged_smoke.py
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

# (passage_id, item_type, texte)
PASSAGES = [
    ("p1", "paragraph",
     "Master Data Governance is available for Custom Objects, Financials, Supplier, "
     "Customer, and Material domains."),
    ("p2", "paragraph",
     "SAP shall not be liable for any damages caused by the use of such content unless "
     "damages have been caused by SAP's gross negligence or willful misconduct."),
    ("p3", "paragraph",
     "Transaction CG5Z is used to delete batch records. The deletion requires the "
     "authorization object S_TABU_DIS and cannot be undone."),
]


def make_passages():
    return [
        SimpleNamespace(passage_id=pid, text=txt, item_type=it, section_title="")
        for pid, it, txt in PASSAGES
    ]


def run(staged: bool):
    from knowbase.claimfirst.extractors.claim_extractor import ClaimExtractor
    ext = ClaimExtractor(llm_client=None, use_staged_pipeline=staged)
    claims, _ = ext.extract(
        make_passages(), tenant_id="default", doc_id="smoke_p14b",
        doc_title="Smoke", doc_type="technical", doc_subject="SAP",
    )
    return ext, claims


def main():
    for staged in (False, True):
        label = "STAGED (A->B->grounding)" if staged else "LEGACY (méga-prompt)"
        try:
            ext, claims = run(staged)
        except Exception as exc:
            print(f"\n### {label} : ERREUR {exc}")
            continue
        print(f"\n{'='*90}\n### {label} : {len(claims)} claims "
              f"(llm_calls={ext.stats.get('llm_calls')}, "
              f"rejected={ext.stats.get('claims_rejected')}, "
              f"grounding_marginal={ext.stats.get('grounding_marginal', 0)})\n{'='*90}")
        # regrouper par passage source
        for c in claims:
            qs = c.quality_scores or {}
            gm = qs.get("grounding_marginal")
            ge = qs.get("grounding_entail")
            sf = c.structured_form or {}
            obj = sf.get("object", "")
            print(f"  [{c.claim_type.value:<11}] {c.text[:88]}")
            if obj:
                print(f"      SF: {sf.get('subject','')[:24]} | {sf.get('predicate','')[:18]} | obj='{obj[:60]}'")
            if gm is not None:
                print(f"      grounding: marginal={gm} entail={ge}")
    print("\nLecture : p1 énumération (STAGED ~1 claim objects-liste vs LEGACY N) ; "
          "p2 boilerplate (STAGED jeté Stage A) ; p3 faits+identifiants conservés.")


if __name__ == "__main__":
    main()
