"""P1.3 smoke — extract→link de procédures, flux complet sans Neo4j.

Construit des sections procédurales synthétiques (passages + claims PROCEDURAL,
mimant la sortie ClaimFirst), lance ProcedureExtractor (LLM réel) + ProcedureLinker,
et reporte procedures / STEP_OF / PREREQUISITE_OF / HAS_OUTCOME.

Dé-risque l'intégration avant la ré-ingestion (ADR_PHASE_B §9). Domain-agnostic :
sections SAP + médical + procédure générique.

Usage (dans le container, DEEPINFRA_API_KEY présent) :
    docker exec knowbase-app sh -c 'cd /app && python -u scripts/p1_3_smoke_procedures.py'
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.WARNING)

from knowbase.claimfirst.models.claim import Claim, ClaimType  # noqa: E402
from knowbase.claimfirst.models.passage import Passage  # noqa: E402
from knowbase.claimfirst.v6.procedure_extractor import ProcedureExtractor  # noqa: E402
from knowbase.claimfirst.v6.procedure_linker import ProcedureLinker  # noqa: E402


def _claim(cid, text, pid):
    return Claim(
        claim_id=cid, tenant_id="default", doc_id="smoke_doc", text=text,
        claim_type=ClaimType.PROCEDURAL, verbatim_quote=text, passage_id=pid,
    )


def _passage(pid, sid, text, order):
    return Passage(
        passage_id=pid, tenant_id="default", doc_id="smoke_doc", text=text,
        section_id=sid, reading_order_index=order,
    )


# Sections procédurales synthétiques (multi-corpus)
SECTIONS = [
    {
        "sid": "sec_sso",
        "text": "To configure single sign-on, first register the identity provider "
                "by uploading its metadata. Then activate the SAML trust relationship "
                "between the application and the provider. Finally, assign the relevant "
                "users to the application role so they can authenticate. Once these "
                "steps are done, single sign-on is active for the tenant.",
        "claims": [
            "Register the identity provider by uploading its metadata",
            "Activate the SAML trust relationship between application and provider",
            "Assign the relevant users to the application role",
            "Single sign-on is active for the tenant once configured",
        ],
    },
    {
        "sid": "sec_breach",
        "text": "When a personal data breach occurs, the controller must follow this "
                "procedure. First, identify and document the nature of the breach. "
                "Next, assess the risk to the rights of the affected individuals. "
                "Then notify the supervisory authority within 72 hours. Finally, if the "
                "risk is high, communicate the breach to the data subjects without delay.",
        "claims": [
            "Identify and document the nature of the data breach",
            "Assess the risk to the rights of affected individuals",
            "Notify the supervisory authority within 72 hours",
            "Communicate the breach to data subjects if the risk is high",
        ],
    },
    {
        "sid": "sec_cache",
        "text": "To initialize the Expert cache, open transaction CG5Z. Then select the "
                "target component from the list. Click the Initialize button to start "
                "the rebuild. Wait until the status shows completed before closing the "
                "transaction. The Expert cache is then ready for use.",
        "claims": [
            "Open transaction CG5Z to start cache initialization",
            "Select the target component from the list",
            "Click the Initialize button to start the rebuild",
            "Wait until the status shows completed",
        ],
    },
]


def main():
    passages = []
    claims = []
    order = 0
    for i, s in enumerate(SECTIONS):
        pid = f"p{i}"
        passages.append(_passage(pid, s["sid"], s["text"], order))
        order += 1
        for j, ct in enumerate(s["claims"]):
            claims.append(_claim(f"c{i}_{j}", ct, pid))

    linker = ProcedureLinker(extractor=ProcedureExtractor(), tenant_id="default")
    res = linker.link(claims=claims, passages=passages, doc_id="smoke_doc")

    print("=== P1.3 smoke extract→link (3 sections procédurales) ===\n")
    for sid, proc in res.procedures:
        print(f"[{sid}] Procedure: {proc.name!r} ({len(proc.steps)} steps)")
        print(f"    goal: {proc.goal}")
        for st in proc.steps:
            print(f"      {st.step_number}. {st.action}")
        if proc.prerequisites:
            print(f"    prerequisites: {proc.prerequisites}")
    print("\n--- STEP_OF (claim → procedure) ---")
    for cid, pid, order in res.step_of_links:
        print(f"    {cid} → {pid} (order={order})")
    print("\n--- PREREQUISITE_OF (claim → claim) ---")
    for r in res.prerequisite_relations:
        print(f"    {r.source_claim_id} → {r.target_claim_id}")
    print("\n--- HAS_OUTCOME (procedure → claim) ---")
    for pid, cid in res.outcome_links:
        print(f"    {pid} → {cid}")

    print("\n=== Stats ===")
    for k, v in res.stats.items():
        print(f"  {k}: {v}")

    n_proc = res.stats["procedures_extracted"]
    n_step = res.stats["step_of_links"]
    n_prereq = res.stats["prerequisite_of"]
    print("\n--- Verdict smoke (extrapolé corpus complet) ---")
    print(f"  Procedures sur 3 sections : {n_proc}  (gate corpus ≥5)")
    print(f"  STEP_OF sur 3 sections    : {n_step}  (gate corpus ≥20)")
    print(f"  PREREQUISITE_OF           : {n_prereq}  (gate corpus ≥5)")
    if n_proc >= 2 and n_step >= 6 and n_prereq >= 3:
        print("  ✅ Flux extract→link fonctionnel — gate corpus atteignable à la ré-ingestion.")
    elif n_proc >= 1:
        print("  🟡 Procédures extraites mais matching faible — vérifier le seuil Jaccard.")
    else:
        print("  🛑 Aucune procédure extraite — vérifier le prompt/LLM avant P1.4.")


if __name__ == "__main__":
    main()
