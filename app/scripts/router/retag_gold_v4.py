"""
Phase 1 (ADR §9.6) — Re-tag gold_set_v4 avec 3 nouveaux champs taxonomie distribuée.

Règles automatiques basées sur :
  - stratum existant (révèle la nature : kg_over_*, *_T7_supersedes, false_premise_T6, etc.)
  - ground_truth.answerability / false_premise / contradiction_vs_supersession / causal_chain
  - patterns linguistiques universels (marqueurs comparatifs/causal/temporal explicites)

Output : benchmark/questions/gold_set_v4_retagged.json (132q avec 3 nouveaux champs).
+ Rapport markdown des cas borderline pour spot-check.
"""
from __future__ import annotations
import json
import re
from collections import Counter
from pathlib import Path

INPUT_PATH = Path("/app/benchmark/questions/gold_set_v4.json")
OUTPUT_PATH = Path("/app/benchmark/questions/gold_set_v4_retagged.json")
REPORT_PATH = Path("/app/data/router/retag_report.md")

# Patterns linguistiques universels (annotation, pas runtime)
# Causal d'abord (priorité sur comparison pour « pourquoi distingue-t-elle X et Y »)
CAUSAL_EXPLICIT_PATTERNS = [
    r"^pourquoi\b", r"^why\b", r"^why,",
    r"\bpour quelle raison\b", r"\bfor what reason\b",
    r"\bquelle cause\b", r"\bwhat caused\b", r"\bwhat causes?\b",
    r"\bwhat reason\b", r"\bhow come\b", r"\bwhat motivated\b",
    r"\bwhat led to\b",
]
COMPARISON_EXPLICIT_PATTERNS = [
    r"\b(vs|versus)\b", r"\bdifférence entre\b", r"\bdifference between\b",
    r"\bcompare[rd]?\b", r"\bcompared to\b", r"\bdiffèrent\b", r"\bdiffer\b",
    r"\bdistingue\b", r"\bdistinguishes?\b",
    # « X ou Y ? » / « X or Y? » incluant identifiants avec /
    r"\b\S+ ou \S+\s*\?", r"\b\S+ or \S+\s*\?",
    # « est-ce que X et Y... contradictoires »
    r"\bcontradiction\b.*\bentre\b",
    r"\b\w+ et \w+ \w+-(elles|ils|t-il|t-elle)\b",  # « X et Y sont-ils »
]
TEMPORAL_EXPLICIT_PATTERNS = [
    r"\bquand\b", r"\bwhen\b",
    r"\ben quelle année\b", r"\bwhat year\b", r"\bin what year\b",
    r"\bquelle (version|édition|amendment|amdt)\b",
    r"\bquelle était la version\b", r"\bquelle est la version\b",
    r"\bwhich (version|edition|amendment)\b",
    r"\blatest\b", r"\bplus récent\b", r"\bla plus récente\b",
    r"\bantérieur(e)? à\b", r"\bprior to\b", r"\bbefore\b(?! the)",
    r"\bsuccesseur\b", r"\bsuccessor\b",
    r"\bremplac(e|é|er|ée)\b", r"\breplaces?\b", r"\breplaced\b",
    r"\babroge\b", r"\babrog[éée]\b", r"\babolish\b", r"\bsupersedes?\b",
    r"\bdepuis\b", r"\bsince\b",
    r"\bversion (la plus récente|currently|actuelle)\b",
    r"\btoujours en vigueur\b", r"\bstill in force\b",
    r"\bétait[ -]il en vigueur\b", r"\bétait[ -]elle en vigueur\b",
    r"\bs[' ]?appliquait\b", r"\bapplicable en\b", r"\bau moment de\b",
    r"\bapplicable au moment\b",
    r"\b(EVOLVES_FROM|SUPERSEDES|LIFECYCLE_RELATION)\b",
    r"\bchronologie\b", r"\bchronologi(que|cal)\b", r"\bhistorique\b",
    r"\bcertification basis\b", r"\bverrouillée comme\b",
    r"\b(\d{4}/\d+|\d{4}-\d+)\b.*\bavant\b", r"\bavant\b.*\b(\d{4}/\d+|\d{4}-\d+)\b",
]
LIST_EXPLICIT_PATTERNS = [
    r"\bliste\b", r"\blist (the|all|dual-use|some)\b", r"^list \w",
    r"\bquels sont les\b", r"\bquelles sont les\b",
    r"\bwhat are the\b",
    r"\bénumère\b", r"\bénumérer\b", r"\benumerate\b",
    r"\bname (the|all|three|four|five|two|several)\b",
    r"\b(quels|quelles) \w+ \w+",  # « Quels actes délégués » heuristique faible
]


def matches_any(text: str, patterns: list[str]) -> bool:
    text_lc = text.lower().strip()
    return any(re.search(p, text_lc, re.IGNORECASE) for p in patterns)


def derive_epistemic_status(q: dict) -> str:
    gt = q.get("ground_truth", {}) or {}
    if gt.get("false_premise"):
        return "false_premise"
    if gt.get("answerability") == "unanswerable":
        return "unanswerable"
    return "answerable"


def derive_corpus_signal(q: dict) -> str:
    """Détermine quel signal corpus est requis pour trancher le label final."""
    gt = q.get("ground_truth", {}) or {}
    stratum = (q.get("stratum") or "").lower()
    text = q.get("question", "").lower()

    # Meta-KG questions (introspection KG)
    if any(kw in text for kw in ["dans le kg", "in the kg", "matérialisé", "materialised",
                                  "supersedes dans le corpus", "lifecycle_relation",
                                  "evolves_from", "logical_relation", "vue d'ensemble"]):
        return "kg_meta"
    if "synthesis_large" in stratum or "kg_meta" in stratum:
        return "kg_meta"

    # Comparison émergent du KG (incluant trap_classifier_false_positive sur T2)
    if "kg_over" in stratum or "real_tension" in stratum:
        return "contradiction"
    if stratum.startswith("comparison_") or "trap_classifier_false_positive" in stratum:
        return "contradiction"

    # Supersession explicite ou implicite
    if gt.get("contradiction_vs_supersession") == "SUPERSESSION":
        return "supersession"
    if gt.get("contradiction_vs_supersession") == "CONTRADICTION":
        return "contradiction"

    # Questions de coverage check sur le corpus (« y a-t-il un X qui... »)
    if re.search(r"\by a-t-il (un|une|des) \w+ .* qui (ne |n[' ])", text):
        return "missing_info"  # vérification absence dans corpus
    if re.search(r"\bexiste-t-il une chaîne\b", text):
        return "kg_meta"

    # Audit retrospectif (transaction passée → quelle version applicable)
    if re.search(r"\b(audit|transaction|exporté|certification).{0,80}\b(20\d{2})\b", text):
        return "supersession"
    # « était en vigueur le X » / « applicable en X »
    if re.search(r"\b(était|était-il|était-elle|était en vigueur|applicable (en|au))\b.{0,60}\b(20\d{2})\b", text):
        return "supersession"
    if re.search(r"\bs[' ]?appliquait au moment\b", text):
        return "supersession"

    # Unanswerable (info hors corpus)
    if gt.get("answerability") == "unanswerable":
        return "missing_info"

    # False_premise (vérification corpus)
    if gt.get("false_premise"):
        return "premise_check"

    return "none"


def derive_answer_shape(q: dict) -> str:
    """Détermine answer_shape depuis la formulation seule (5 classes)."""
    text = q.get("question", "")
    primary = q.get("primary_type", "")
    stratum = (q.get("stratum") or "").lower()

    # Comparison EXPLICIT (formulation a un marqueur comparatif)
    if matches_any(text, COMPARISON_EXPLICIT_PATTERNS):
        return "comparison_explicit"

    # Causal EXPLICIT (formulation a un marqueur causal)
    if matches_any(text, CAUSAL_EXPLICIT_PATTERNS):
        return "causal_explicit"

    # Temporal EXPLICIT (marqueurs temporels)
    if matches_any(text, TEMPORAL_EXPLICIT_PATTERNS):
        return "temporal"

    # List EXPLICIT (énumération attendue)
    if matches_any(text, LIST_EXPLICIT_PATTERNS):
        return "list"

    # Heuristique faible : « Quels X » sans autre marqueur, parfois list parfois factual
    # On regarde si le primary original est list, sinon scalar_factual
    if re.search(r"^(quels|quelles|which) \w+", text, re.IGNORECASE):
        # Ambigu : si gold a list_items_expected > 0 → list, sinon scalar_factual
        gt = q.get("ground_truth", {}) or {}
        if gt.get("list_items_expected") and len(gt["list_items_expected"]) >= 2:
            return "list"
        return "scalar_factual"

    return "scalar_factual"


def main():
    questions = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(questions)} gold_set_v4 questions")

    retagged = []
    borderline = []
    stats_shape = Counter()
    stats_status = Counter()
    stats_signal = Counter()
    primary_to_shape = Counter()

    for q in questions:
        ans_shape = derive_answer_shape(q)
        epistemic = derive_epistemic_status(q)
        signal = derive_corpus_signal(q)

        stats_shape[ans_shape] += 1
        stats_status[epistemic] += 1
        stats_signal[signal] += 1
        primary_to_shape[(q.get("primary_type"), ans_shape)] += 1

        new_q = dict(q)
        new_q["gold_answer_shape"] = ans_shape
        new_q["gold_epistemic_status"] = epistemic
        new_q["gold_corpus_signal_required"] = signal
        retagged.append(new_q)

        # Repérer cas borderline pour spot-check
        primary = q.get("primary_type")
        is_divergence = False
        if primary == "comparison" and ans_shape != "comparison_explicit":
            is_divergence = True  # comparison émergent KG
        elif primary == "causal" and ans_shape != "causal_explicit":
            is_divergence = True
        elif primary == "factual" and ans_shape == "list":
            is_divergence = True
        elif primary == "list" and ans_shape == "scalar_factual":
            is_divergence = True
        elif primary == "temporal" and ans_shape != "temporal":
            is_divergence = True
        elif primary == "false_premise" and epistemic != "false_premise":
            is_divergence = True
        elif primary == "unanswerable" and epistemic != "unanswerable":
            is_divergence = True

        if is_divergence:
            borderline.append({
                "id": q["id"],
                "language": q["language"],
                "question": q["question"][:200],
                "primary_type": primary,
                "secondary_type": q.get("secondary_type"),
                "stratum": q.get("stratum"),
                "gold_answer_shape": ans_shape,
                "gold_epistemic_status": epistemic,
                "gold_corpus_signal_required": signal,
            })

    # Persist
    OUTPUT_PATH.write_text(json.dumps(retagged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted retagged → {OUTPUT_PATH}")
    print(f"\n=== STATS ===")
    print(f"answer_shape       : {dict(stats_shape)}")
    print(f"epistemic_status   : {dict(stats_status)}")
    print(f"corpus_signal      : {dict(stats_signal)}")

    print(f"\nDivergences primary_type → answer_shape (cas où nouveau ≠ ancien) :")
    for (primary, shape), n in sorted(primary_to_shape.items(), key=lambda x: -x[1]):
        marker = " ← divergence" if not (
            (primary == "factual" and shape == "scalar_factual") or
            (primary == "list" and shape == "list") or
            (primary == "temporal" and shape == "temporal") or
            (primary == "comparison" and shape == "comparison_explicit") or
            (primary == "causal" and shape == "causal_explicit") or
            primary in ("unanswerable", "false_premise")  # pas de mapping direct shape pour ces 2
        ) else ""
        print(f"  {primary:<14} → {shape:<22} : {n:>3}{marker}")

    # Rapport borderline
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Re-tag gold_set_v4 — Cas borderline pour spot-check\n",
             f"\n**{len(borderline)}/{len(questions)} cas divergents** (primary_type ≠ projection automatique).\n",
             "\nValide manuellement les cas où la projection automatique pourrait être fausse.\n\n---\n\n"]
    for b in borderline:
        lines.append(f"## [{b['id']}] {b['language']}\n")
        lines.append(f"**Q** : {b['question']}\n\n")
        lines.append(f"- primary_type (legacy) : `{b['primary_type']}` (secondary `{b['secondary_type']}`)\n")
        lines.append(f"- stratum : `{b['stratum']}`\n")
        lines.append(f"- → answer_shape : `{b['gold_answer_shape']}`\n")
        lines.append(f"- → epistemic_status : `{b['gold_epistemic_status']}`\n")
        lines.append(f"- → corpus_signal_required : `{b['gold_corpus_signal_required']}`\n\n")
    REPORT_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"\nBorderline cases report → {REPORT_PATH} ({len(borderline)} cases)")


if __name__ == "__main__":
    main()
