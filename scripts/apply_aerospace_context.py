"""
Apply aerospace_compliance pack context to DomainContextProfile in DB.

Cause : l'activation du pack aerospace_compliance n'a fait qu'ajouter le pack à
active_packs, sans mettre à jour le contenu du profil (qui est resté SAP).
Conséquence : tous les LLM calls reçoivent un contexte SAP injecté dans le prompt
malgré le corpus aerospace → {"claims": []} systématique.

Ce script charge aerospace_compliance/context_defaults.json et met à jour le
profil pour tenant 'default' (industry, llm_injection_prompt, common_acronyms,
key_concepts, versioning_hints, identification_semantics, domain_summary).

Usage (depuis un container app/worker) :
    python scripts/apply_aerospace_context.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACK_DIR = Path("/app/src/knowbase/domain_packs/aerospace_compliance")
CONTEXT_DEFAULTS = PACK_DIR / "context_defaults.json"
TENANT = "default"


def build_llm_injection_prompt(defaults: dict) -> str:
    """Construit le bloc llm_injection_prompt complet à partir du JSON."""
    lines: list[str] = []
    lines.append("[DOMAIN CONTEXT - Aerospace Export Control]")
    lines.append("")
    lines.append(f"BUSINESS CONTEXT: {defaults['domain_summary']}")
    lines.append("")
    lines.append("KEY DOMAINS: EASA Certification Specifications (CS-25 Large Aeroplanes), "
                 "EU Dual-Use Regulation 2021/821, EU Delegated Regulations Annex I, "
                 "International export control regimes (Wassenaar/MTCR/NSG/Australia Group)")
    lines.append("")
    concepts_top = ", ".join(defaults["key_concepts"][:12])
    lines.append(f"KEY CONCEPTS: {concepts_top}")
    lines.append("")
    lines.append("Use this context to correctly interpret aerospace certification "
                 "and dual-use export control terminology. Treat regulation IDs, "
                 "amendment numbers, ED Decisions and CS-25 paragraph references "
                 "as primary subjects. Recognise EASA/FAA/ICAO authorities and "
                 "Wassenaar/MTCR/NSG/AG regimes.")
    return "\n".join(lines)


VERSIONING_HINTS_AEROSPACE = (
    "Aerospace versioning axes: (1) CS-25 Amendment number (Amdt 22..28) — "
    "version of the certification specification, ordered chronologically. "
    "(2) ED Decision YYYY/NNN/R — Executive Director Decision identifying the "
    "amendment (e.g. ED Decision 2023/021/R = Amdt 28). "
    "(3) Regulation publication year (2021/821, 428/2009) — distinct from Amdt. "
    "(4) Delegated Regulation date (2024/2547, 2023/996) — annual modification "
    "of the dual-use Annex I, ordered by year/number."
)

IDENT_SEMANTICS_AEROSPACE = (
    "Rule: '(EU) YYYY/NNN' or '(EC) No NNNN/YYYY' immediately preceded by 'Regulation' "
    "or 'Council Regulation' → regulation_id (e.g. 'Regulation (EU) 2021/821').\n"
    "Rule: 'Amendment NN' or 'Amdt NN' with NN in 22..28 → cs25_amendment.\n"
    "Rule: 'ED Decision YYYY/NNN/R' → easa_decision_id, NOT a date.\n"
    "Rule: 'CS 25.NNN' or 'CS-25.NNN' with NNN numeric → cs25_paragraph_id.\n"
    "Counter-example: '2025' alone in copyright/legal → publication date, NOT regulation_id.\n"
    "Counter-example: ISO date YYYY-MM-DD → temporal date."
)


def main() -> int:
    if not CONTEXT_DEFAULTS.exists():
        print(f"ERROR: context_defaults.json not found at {CONTEXT_DEFAULTS}", file=sys.stderr)
        return 1

    with CONTEXT_DEFAULTS.open(encoding="utf-8") as f:
        defaults = json.load(f)

    from knowbase.ontology.domain_context_store import get_domain_context_store
    from knowbase.ontology.domain_context import DomainContextProfile

    store = get_domain_context_store()
    existing = store.get_profile(TENANT)

    if not existing:
        print(f"ERROR: no profile for tenant '{TENANT}' — create one first via UI", file=sys.stderr)
        return 1

    # Preserve fields we should not touch
    preserved_active_packs = existing.active_packs or ["aerospace_compliance"]
    preserved_axis_policy = existing.axis_policy or ""
    preserved_axis_reclassification = existing.axis_reclassification_rules or ""

    summary = defaults["domain_summary"]
    if len(summary) > 500:
        summary = summary[:497] + "..."

    new_profile = DomainContextProfile(
        tenant_id=TENANT,
        domain_summary=summary,
        industry=defaults["industry"],
        sub_domains=[
            "Aerospace Certification (EASA CS-25)",
            "Dual-Use Export Control (EU 2021/821)",
            "International Export Control Regimes",
        ],
        target_users=[
            "Certification engineers",
            "Compliance officers",
            "Export control officers",
            "Legal counsels",
        ],
        document_types=[
            "Certification Specification",
            "Regulation",
            "Delegated Regulation",
            "ED Decision",
            "Amendment",
        ],
        common_acronyms=defaults["common_acronyms"],
        key_concepts=defaults["key_concepts"],
        context_priority="high",
        llm_injection_prompt=build_llm_injection_prompt(defaults),
        versioning_hints=VERSIONING_HINTS_AEROSPACE,
        identification_semantics=IDENT_SEMANTICS_AEROSPACE,
        axis_reclassification_rules=preserved_axis_reclassification,
        axis_policy=preserved_axis_policy,
        active_packs=preserved_active_packs,
    )

    store.save_profile(new_profile)

    print(f"OK profile updated for tenant '{TENANT}'")
    print(f"  industry: {new_profile.industry}")
    print(f"  active_packs: {new_profile.active_packs}")
    print(f"  acronyms: {len(new_profile.common_acronyms)}")
    print(f"  key_concepts: {len(new_profile.key_concepts)}")
    print(f"  prompt length: {len(new_profile.llm_injection_prompt)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
