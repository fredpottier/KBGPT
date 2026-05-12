"""CH-50 Phase 1 — Construction gold-set v5 par mapping des fichiers source T1/T2/T5/T6/T7.

Format de sortie unifié (multi-tag per D-TR.4) :
{
  "id": "GOLD_v5_<source_id>",
  "source_id": "<original task id>",
  "source_task": "T6_robustness" | ...,
  "source_category": "<original category>",
  "question": "...",
  "language": "fr" | "en",
  "primary_type": "list" | "factual" | "temporal" | "causal" | "comparison" | "multi_hop" | "false_premise" | "unanswerable",
  "secondary_types": [...],
  "flags": ["negation", "kg_centric", "temporal", "conditional", "hypothetical", "lifecycle", ...],
  "ground_truth": {
    "answer": "...",  // texte de référence
    "exact_identifiers": [...],  // codes/dates/regs (extraction lexicale auto, à enrichir LLM en Phase 2)
    "list_items_expected": [...] | None,
    "supporting_doc_ids": [...],
    "answerability": "answerable" | "partial" | "unanswerable",
    "evidence_claim": "...",
    "evidence_quote": "...",
    // Type-specific (T2, T7, T5)
    "claim_a": {...}, "claim_b": {...}, "tension_nature": "...", "expected_resolution": "...",
    "expected_lifecycle_kind": "...", "expected_lifecycle_source": "...", "expected_lifecycle_target": "...",
    "chain": [...],
  },
  "annotation_meta": {
    "source": "auto_mapping_from_<task>",
    "build_date": "...",
    "confidence": "high" | "medium" | "low",
    "needs_review": true | false
  }
}
"""
from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path

QUESTIONS_DIR = Path("/app/benchmark/questions")
OUT_PATH = QUESTIONS_DIR / "gold_set_v5.json"

BUILD_DATE = datetime.now().strftime("%Y-%m-%d")


# =============================================================================
# Category → primary_type + flags mapping (basé sur l'analyse §1-§5 CH-49)
# =============================================================================

T6_CATEGORY_MAPPING = {
    # category: (primary_type, secondary_types, flags)
    "false_premise":       ("factual",       [],            ["false_premise"]),
    "hypothetical":        ("causal",        ["temporal"],  ["hypothetical"]),
    "multi_hop":           ("multi_hop",     [],            ["multi_step"]),
    "conditional":         ("factual",       ["causal"],    ["conditional"]),
    "causal_why":          ("causal",        [],            []),
    "set_list":            ("list",          [],            []),
    "synthesis_large":     ("list",          ["causal"],    ["synthesis", "multi_step"]),
    "temporal_evolution":  ("temporal",      [],            ["lifecycle"]),
    "negation":            ("factual",       [],            ["negation"]),
    "unanswerable":        ("unanswerable",  [],            []),
}

T7_CATEGORY_MAPPING = {
    "lifecycle_supersedes":           ("temporal",   [],            ["kg_centric", "lifecycle"]),
    "lifecycle_evolves_from":         ("temporal",   [],            ["kg_centric", "lifecycle"]),
    "lifecycle_filtering_active":     ("temporal",   [],            ["kg_centric", "active_version"]),
    "lifecycle_vs_conflict":          ("comparison", ["temporal"],  ["kg_centric", "lifecycle"]),
    "anchor_applicability_temporal":  ("temporal",   [],            ["temporal"]),
    "anchor_scope_hierarchy":         ("factual",    [],            ["scope_hierarchy"]),
}


def _detect_language(text: str) -> str:
    """Détection langue basique (FR vs EN). Fallback FR si ambigu."""
    if not text:
        return "fr"
    fr_markers = re.findall(r"\b(le|la|les|du|de|des|est|sont|une|qu|qui|que|où|à|aux|pour|dans|sur|par|avec)\b", text.lower())
    en_markers = re.findall(r"\b(the|is|are|of|to|and|or|in|on|by|with|which|what|when|where|how|why)\b", text.lower())
    return "fr" if len(fr_markers) >= len(en_markers) else "en"


def _extract_identifiers(text: str) -> list[str]:
    """Extraction LEXICALE basique des identifiants (regex). Phase 2 LLM enrichira."""
    if not text:
        return []
    out = set()
    # Numéros de règlements EU
    for m in re.finditer(r"\b(?:Règlement|Reg(?:ulation)?|Council Reg|CE|UE|EU|EC)[\s.,()°N°]*([0-9]{2,4}/[0-9]{1,4})\b", text):
        out.add(m.group(1))
    for m in re.finditer(r"\b\d{4}/\d{1,4}\b", text):
        out.add(m.group(0))
    # CS-25 paragraphes/amendments
    for m in re.finditer(r"\b(?:CS|AMC)\s*25\.\d+(?:[(\.][a-z0-9]+\)?)?\b", text):
        out.add(m.group(0))
    for m in re.finditer(r"\b(?:CS-25\s+)?(?:Amendment|Amdt|amdt)\s*\d{1,3}\b", text, re.IGNORECASE):
        out.add(m.group(0))
    # Dates ISO et françaises
    for m in re.finditer(r"\b\d{4}-\d{2}-\d{2}\b", text):
        out.add(m.group(0))
    for m in re.finditer(r"\b\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre|January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b", text, re.IGNORECASE):
        out.add(m.group(0))
    # Annex/Annexe
    for m in re.finditer(r"\b(?:Annex(?:e)?\s*[IVX]+(?:\s*Partie\s*\d)?)\b", text):
        out.add(m.group(0))
    # NPA
    for m in re.finditer(r"\bNPA\s*\d{4}-\d+\b", text):
        out.add(m.group(0))
    return sorted(out)


def _build_base(source_id: str, source_task: str, source_category: str, question: str) -> dict:
    """Squelette d'entrée gold v5."""
    return {
        "id": f"GOLD_v5_{source_id}",
        "source_id": source_id,
        "source_task": source_task,
        "source_category": source_category,
        "question": question,
        "language": _detect_language(question),
        "primary_type": None,
        "secondary_types": [],
        "flags": [],
        "ground_truth": {},
        "annotation_meta": {
            "source": f"auto_mapping_from_{source_task}",
            "build_date": BUILD_DATE,
            "confidence": "high",
            "needs_review": False,
        },
    }


# =============================================================================
# Mappers per task
# =============================================================================

def map_t1(q: dict) -> dict:
    """T1 provenance → primary=factual, flags depuis category."""
    cat = q.get("category", "?")
    entry = _build_base(q["id"], "T1_provenance", cat, q["question"])
    entry["primary_type"] = "factual"
    entry["flags"] = ["provenance"]
    if "definition" in cat:
        entry["secondary_types"] = ["definition"]
    if "anchor" in cat:
        entry["flags"].append("anchor")
    if "exemption" in cat or "exclusion" in cat:
        entry["flags"].append("exemption")
    if "negation" in cat or "exclusion" in cat:
        entry["flags"].append("negation")

    answer = q.get("ground_truth_answer", "")
    doc_id = q.get("ground_truth_doc_id", "")
    quote = q.get("verbatim_quote", "")

    entry["ground_truth"] = {
        "answer": answer,
        "exact_identifiers": _extract_identifiers(answer + " " + quote),
        "list_items_expected": None,
        "supporting_doc_ids": [doc_id] if doc_id else [],
        "answerability": "answerable",
        "evidence_quote": quote,
    }
    return entry


def map_t2(q: dict) -> dict:
    """T2 contradictions → primary=comparison, flags=[contradiction, ...]."""
    cat = q.get("category", "?")
    entry = _build_base(q["id"], "T2_contradictions", cat, q["question"])
    entry["primary_type"] = "comparison"
    entry["flags"] = ["contradiction"]
    if "numeric" in cat:
        entry["flags"].append("numeric_evolution")
    if "lifecycle" in cat or q.get("ground_truth", {}).get("expected_resolution") == "lifecycle_supersedes":
        entry["flags"].append("lifecycle")

    gt = q.get("ground_truth", {})
    claim_a = gt.get("claim_a", {})
    claim_b = gt.get("claim_b", {})
    grading = q.get("grading_rules", {})

    # Construit answer composite si has_real_tension
    has_tension = gt.get("has_real_tension", True)
    if has_tension:
        a_val = claim_a.get("value", claim_a.get("text", ""))
        b_val = claim_b.get("value", claim_b.get("text", ""))
        a_doc = claim_a.get("doc_id", "")
        b_doc = claim_b.get("doc_id", "")
        answer = (
            f"Il existe une divergence entre deux sources : {a_val} ({a_doc}) "
            f"vs {b_val} ({b_doc}). "
            f"Résolution attendue : {gt.get('expected_resolution', 'unspecified')}."
        )
    else:
        answer = "Pas de tension réelle — divergence apparente."

    # Inclut directement les must_mention_both_values dans exact_identifiers
    must_values = grading.get("must_mention_both_values", []) or []
    auto_ids = _extract_identifiers(
        (claim_a.get("text", "") or "") + " " +
        (claim_b.get("text", "") or "") + " " +
        (claim_a.get("value", "") or "") + " " +
        (claim_b.get("value", "") or "")
    )
    exact_ids = sorted(set(must_values + auto_ids))

    entry["ground_truth"] = {
        "answer": answer,
        "exact_identifiers": exact_ids,
        "list_items_expected": None,
        "supporting_doc_ids": grading.get("must_surface_both_docs", []),
        "answerability": "answerable" if has_tension else "partial",
        "claim_a": claim_a,
        "claim_b": claim_b,
        "tension_nature": gt.get("tension_nature"),
        "expected_resolution": gt.get("expected_resolution"),
        "must_mention_both_values": must_values,
    }
    return entry


def map_t5(q: dict) -> dict:
    """T5 cross-doc → primary=multi_hop, flags=[cross_doc, lifecycle souvent]."""
    cat = q.get("category", "?")
    entry = _build_base(q["id"], "T5_cross_doc", cat, q["question"])
    entry["primary_type"] = "multi_hop"
    entry["flags"] = ["cross_doc"]
    if any(x in cat for x in ("evolution", "lifecycle", "succession", "evolution_chronological")):
        entry["flags"].append("lifecycle")
        entry["secondary_types"] = ["temporal"]
    if "synthesis" in cat:
        entry["flags"].append("synthesis")
    if "audit" in cat:
        entry["flags"].append("audit")

    gt = q.get("ground_truth", {})
    chain = gt.get("chain", [])
    grading = q.get("grading_rules", {})

    # Build answer summarising the chain
    chain_summary = " → ".join(c.get("text", "")[:80] for c in chain[:5]) if chain else ""
    answer = chain_summary if chain_summary else gt.get("correct_fact", "")
    doc_ids = [c.get("doc_id") for c in chain if c.get("doc_id")] or grading.get("must_cite_docs", [])

    list_items = [c.get("text", "")[:120] for c in chain] if chain else None

    entry["ground_truth"] = {
        "answer": answer,
        "exact_identifiers": _extract_identifiers(" ".join(c.get("text", "") for c in chain)),
        "list_items_expected": list_items,
        "supporting_doc_ids": list({d for d in doc_ids if d}),
        "answerability": "answerable",
        "chain": chain,
    }
    return entry


def map_t6(q: dict) -> dict:
    """T6 robustness → primary depuis category mapping."""
    cat = q.get("category", "?")
    entry = _build_base(q["id"], "T6_robustness", cat, q["question"])
    primary, secondary, flags = T6_CATEGORY_MAPPING.get(cat, ("factual", [], [cat]))
    entry["primary_type"] = primary
    entry["secondary_types"] = secondary
    entry["flags"] = flags

    gt = q.get("ground_truth", {})
    grading = q.get("grading_rules", {})
    expected_behavior = gt.get("expected_behavior", "answer")
    correct_fact = gt.get("correct_fact", "")
    evidence_claim = gt.get("evidence_claim", "")
    evidence_doc = gt.get("evidence_doc", "")

    # Answerability mapping
    if expected_behavior in ("abstain", "decline", "no_answer"):
        answerability = "unanswerable"
    elif expected_behavior == "reject_premise":
        answerability = "answerable"  # mais avec correction de prémisse
    elif expected_behavior == "partial_answer":
        answerability = "partial"
    else:
        answerability = "answerable"

    entry["ground_truth"] = {
        "answer": correct_fact,
        "exact_identifiers": _extract_identifiers(correct_fact + " " + evidence_claim),
        "list_items_expected": None,  # Phase 2 LLM si applicable (pour list/synthesis)
        "supporting_doc_ids": [evidence_doc] if evidence_doc else [],
        "answerability": answerability,
        "expected_behavior": expected_behavior,
        "evidence_claim": evidence_claim,
        "grading_rules": grading,
    }
    if cat == "negation":
        entry["ground_truth"]["answerability"] = "answerable"  # négation = répondre par exemptions
    return entry


def map_t7(q: dict) -> dict:
    """T7 V2 anchor → primary depuis category mapping (lifecycle dominante)."""
    cat = q.get("category", "?")
    entry = _build_base(q["id"], "T7_v2_anchor", cat, q["question"])
    primary, secondary, flags = T7_CATEGORY_MAPPING.get(cat, ("temporal", [], ["kg_centric", "lifecycle"]))
    entry["primary_type"] = primary
    entry["secondary_types"] = secondary
    entry["flags"] = flags

    gt = q.get("ground_truth", {})
    grading = q.get("grading_rules", {})
    correct_fact = gt.get("correct_fact", "")
    evidence_quote = gt.get("evidence_quote", "")
    expected_anchor = gt.get("expected_anchor", "")

    docs = []
    if expected_anchor:
        docs.append(expected_anchor)
    if gt.get("expected_lifecycle_source") and gt["expected_lifecycle_source"] != expected_anchor:
        docs.append(gt["expected_lifecycle_source"])
    if gt.get("expected_lifecycle_target") and gt["expected_lifecycle_target"] != expected_anchor:
        docs.append(gt["expected_lifecycle_target"])

    entry["ground_truth"] = {
        "answer": correct_fact,
        "exact_identifiers": _extract_identifiers(correct_fact + " " + evidence_quote),
        "list_items_expected": None,
        "supporting_doc_ids": list(dict.fromkeys(docs)),
        "answerability": "answerable",
        "evidence_quote": evidence_quote,
        "expected_anchor": expected_anchor,
        "expected_lifecycle_kind": gt.get("expected_lifecycle_kind"),
        "expected_lifecycle_source": gt.get("expected_lifecycle_source"),
        "expected_lifecycle_target": gt.get("expected_lifecycle_target"),
        "grading_rules": grading,
    }
    return entry


# =============================================================================
# Driver
# =============================================================================

SOURCES = [
    ("aero_t1_provenance.json",     map_t1, "T1"),
    ("aero_t2_contradictions.json", map_t2, "T2"),
    ("aero_t5_cross_doc.json",      map_t5, "T5"),
    ("aero_t6_robustness.json",     map_t6, "T6"),
    ("aero_t7_v2_anchor.json",      map_t7, "T7"),
]


def main():
    all_entries = []
    stats = {}
    for fname, mapper, label in SOURCES:
        path = QUESTIONS_DIR / fname
        if not path.exists():
            print(f"⚠️  {fname} introuvable")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        n_in = len(data)
        n_ok = 0
        n_err = 0
        for q in data:
            try:
                entry = mapper(q)
                all_entries.append(entry)
                n_ok += 1
            except Exception as exc:
                print(f"❌ {q.get('id','?')}: {exc}")
                n_err += 1
        stats[label] = {"in": n_in, "ok": n_ok, "err": n_err}
        print(f"{label}: {n_ok}/{n_in} mapped ({n_err} errors)")

    # Stats globales
    print(f"\n=== TOTAL : {len(all_entries)} entries ===")
    type_count = {}
    flag_count = {}
    for e in all_entries:
        type_count[e["primary_type"]] = type_count.get(e["primary_type"], 0) + 1
        for f in e["flags"]:
            flag_count[f] = flag_count.get(f, 0) + 1
    print("\nDistribution primary_type:")
    for t, n in sorted(type_count.items(), key=lambda x: -x[1]):
        print(f"  {t:25s} : {n:3d}")
    print("\nDistribution flags (top 15):")
    for f, n in sorted(flag_count.items(), key=lambda x: -x[1])[:15]:
        print(f"  {f:25s} : {n:3d}")

    # Persist
    OUT_PATH.write_text(json.dumps(all_entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ Persisted → {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
