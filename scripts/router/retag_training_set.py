"""
Phase 2 (ADR §9.6) — Re-tag training set 14767q vers nouvelle taxonomie answer_shape.

Mapping par source :
  Mintaka complexityType :
    count/ordinal/intersection/generic/superlative/multihop/yesno → scalar_factual
    comparative/difference                                         → comparison_explicit
  Mintaka filtered (patterns) → answer_shape = primary_type direct (temporal/list/causal_explicit)
  SQuAD2 unanswerable → epistemic=unanswerable, answer_shape=scalar_factual
  SQuAD2 causal (filtré "Why") → answer_shape=causal_explicit, epistemic=answerable
  HotpotQA causal/list → answer_shape direct
  FalseQA → epistemic=false_premise, answer_shape via patterns linguistiques
  Manuel humain → primary_type direct (déjà 7 classes), mappé selon nos règles
  Translations FR → hérite du primary_type
"""
from __future__ import annotations
import json
import re
import sys
from collections import Counter
from pathlib import Path

INPUT_PATH = Path("/app/benchmark/questions/router_training_set_v2.json")
OUTPUT_PATH = Path("/app/benchmark/questions/router_training_set_v3.json")

# Patterns universels (mêmes que retag_gold_v4.py)
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
    r"\b\S+ ou \S+\s*\?", r"\b\S+ or \S+\s*\?",
]
TEMPORAL_EXPLICIT_PATTERNS = [
    r"\bquand\b", r"\bwhen\b",
    r"\ben quelle année\b", r"\bwhat year\b", r"\bin what year\b",
    r"\bquelle (version|édition|amendment|amdt)\b",
    r"\bwhich (version|edition|amendment)\b",
    r"\blatest\b", r"\bplus récent\b", r"\bla plus récente\b",
    r"\bantérieur(e)? à\b", r"\bprior to\b",
    r"\bsuccesseur\b", r"\bsuccessor\b",
    r"\bremplac(e|é|er|ée)\b", r"\breplaces?\b", r"\breplaced\b",
    r"\babroge\b", r"\babrog[éée]\b", r"\babolish\b", r"\bsupersedes?\b",
    r"\btoujours en vigueur\b", r"\bstill in force\b",
    r"\b(EVOLVES_FROM|SUPERSEDES|LIFECYCLE_RELATION)\b",
    r"\bchronologie\b", r"\bchronologi(que|cal)\b", r"\bhistorique\b",
]
LIST_EXPLICIT_PATTERNS = [
    r"\bliste\b", r"\blist (the|all|some)\b", r"^list \w",
    r"\bquels sont les\b", r"\bquelles sont les\b",
    r"\bwhat are the\b",
    r"\bénumère\b", r"\bénumérer\b", r"\benumerate\b",
    r"\bname (the|all|three|four|five|two|several)\b",
]


def matches_any(text: str, patterns: list[str]) -> bool:
    text_lc = (text or "").lower().strip()
    return any(re.search(p, text_lc, re.IGNORECASE) for p in patterns)


def derive_shape_from_text(text: str, primary_hint: str | None = None) -> str:
    """Détermine answer_shape depuis la formulation. Causal d'abord, puis comparison, etc."""
    if matches_any(text, CAUSAL_EXPLICIT_PATTERNS):
        return "causal_explicit"
    if matches_any(text, COMPARISON_EXPLICIT_PATTERNS):
        return "comparison_explicit"
    if matches_any(text, TEMPORAL_EXPLICIT_PATTERNS):
        return "temporal"
    if matches_any(text, LIST_EXPLICIT_PATTERNS):
        return "list"
    # Fallback : si primary_hint indique list, on accepte. Sinon scalar.
    if primary_hint == "list":
        return "list"
    return "scalar_factual"


def retag_question(q: dict) -> dict:
    """Ajoute gold_answer_shape + gold_epistemic_status + gold_corpus_signal_required."""
    text = q.get("question", "")
    source = q.get("source", "unknown")
    primary = q.get("primary_type", "")
    new_q = dict(q)

    # 1. epistemic_status
    if primary == "false_premise" or q.get("qualifiers", {}).get("has_false_premise"):
        epistemic = "false_premise"
    elif primary == "unanswerable":
        epistemic = "unanswerable"
    else:
        epistemic = "answerable"
    new_q["gold_epistemic_status"] = epistemic

    # 2. answer_shape — par source
    if source.startswith("mintaka") and not source.startswith("mintaka_filtered"):
        # Mintaka classique : utilise complexityType
        ct = q.get("complexity_type_orig", "")
        if ct in ("comparative", "difference"):
            shape = "comparison_explicit"
        else:
            # count, ordinal, intersection, generic, superlative, multihop, yesno
            shape = "scalar_factual"
            # exception : si "why" dans la question (multihop peut avoir "why")
            if matches_any(text, CAUSAL_EXPLICIT_PATTERNS):
                shape = "causal_explicit"
            elif matches_any(text, TEMPORAL_EXPLICIT_PATTERNS):
                shape = "temporal"
    elif source.startswith("mintaka_filtered"):
        # Mintaka filtered : primary_type est déjà l'answer_shape direct (temporal/list/causal)
        if primary == "causal":
            shape = "causal_explicit"
        elif primary == "list":
            shape = "list"
        elif primary == "temporal":
            shape = "temporal"
        else:
            shape = derive_shape_from_text(text, primary)
    elif source.startswith("squad2") and not source.startswith("squad2_filtered"):
        # SQuAD2 unanswerable
        shape = derive_shape_from_text(text, "scalar_factual")
        # Garde shape de la formulation, l'epistemic est déjà unanswerable
    elif source.startswith("squad2_filtered"):
        # SQuAD2 causal
        shape = "causal_explicit"
    elif source.startswith("hotpotqa"):
        if primary == "causal":
            shape = "causal_explicit"
        elif primary == "list":
            shape = "list"
        else:
            shape = derive_shape_from_text(text, primary)
    elif source.startswith("falseqa"):
        # FalseQA : epistemic=false_premise déjà fait, on prend la formulation
        shape = derive_shape_from_text(text, primary)
    elif source.startswith("manual_human"):
        # Mes 490 humaines : primary_type est déjà bien défini → mapper
        if primary == "causal":
            shape = "causal_explicit"
        elif primary == "comparison":
            shape = "comparison_explicit"
        elif primary == "temporal":
            shape = "temporal"
        elif primary == "list":
            shape = "list"
        elif primary == "factual":
            shape = "scalar_factual"
        elif primary in ("unanswerable", "false_premise"):
            # epistemic déjà set, on regarde la formulation pour shape
            shape = derive_shape_from_text(text, "scalar_factual")
        else:
            shape = derive_shape_from_text(text, primary)
    elif "_translated" in source:
        # Traductions FR : hérite du primary_type original
        if primary == "causal":
            shape = "causal_explicit"
        elif primary == "comparison":
            shape = "comparison_explicit"
        elif primary == "temporal":
            shape = "temporal"
        elif primary == "list":
            shape = "list"
        elif primary == "factual":
            shape = "scalar_factual"
        elif primary in ("unanswerable", "false_premise"):
            shape = derive_shape_from_text(text, "scalar_factual")
        else:
            shape = derive_shape_from_text(text, primary)
    else:
        shape = derive_shape_from_text(text, primary)

    new_q["gold_answer_shape"] = shape

    # 3. corpus_signal_required (training set : pas de signal corpus puisque pas dans corpus tenant)
    # On le met à "none" sauf cas évidents
    if epistemic == "unanswerable":
        new_q["gold_corpus_signal_required"] = "missing_info"
    elif epistemic == "false_premise":
        new_q["gold_corpus_signal_required"] = "premise_check"
    else:
        new_q["gold_corpus_signal_required"] = "none"

    return new_q


def main():
    data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    questions = data.get("questions") or data
    print(f"Loaded {len(questions)} training questions")

    retagged = [retag_question(q) for q in questions]

    # Stats
    print(f"\n=== answer_shape distribution ===")
    by_shape = Counter(q["gold_answer_shape"] for q in retagged)
    for s, n in sorted(by_shape.items(), key=lambda x: -x[1]):
        print(f"  {s:<22} : {n} ({n/len(retagged)*100:.1f}%)")

    print(f"\n=== epistemic_status distribution ===")
    for e, n in Counter(q["gold_epistemic_status"] for q in retagged).items():
        print(f"  {e:<22} : {n} ({n/len(retagged)*100:.1f}%)")

    print(f"\n=== answer_shape × language ===")
    by_shape_lang = Counter((q["gold_answer_shape"], q["language"]) for q in retagged)
    for (s, l), n in sorted(by_shape_lang.items()):
        print(f"  ({s:<22}, {l}) : {n}")

    # Persist
    output = {
        "schema_version": "router_training_v3",
        "description": "Training set re-taggé avec gold_answer_shape (5) + gold_epistemic_status (3). Pivot ADR §9.",
        "sources": data.get("sources", {}),
        "questions": retagged,
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
