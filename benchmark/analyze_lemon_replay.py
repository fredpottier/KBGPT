"""Analyse comparative AVANT/APRES CH-31 sur les 12 lemon questions."""
import io
import json
import sys
import textwrap

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DATA = json.load(open(r"C:/Projects/SAP_KB/benchmark/lemon_replay_ch32.json", encoding="utf-8"))


def gt_excerpt(gt) -> str:
    if not isinstance(gt, dict):
        return ""
    pieces = []
    if gt.get("expected_answer"):
        pieces.append(f"expected_answer: {str(gt['expected_answer'])[:200]}")
    if gt.get("expected_doc_id"):
        pieces.append(f"expected_doc_id: {gt['expected_doc_id']}")
    if gt.get("claim_a"):
        ca = gt["claim_a"] if isinstance(gt["claim_a"], str) else json.dumps(gt["claim_a"], ensure_ascii=False)
        pieces.append(f"claim_a: {ca[:180]}")
    if gt.get("claim_b"):
        cb = gt["claim_b"] if isinstance(gt["claim_b"], str) else json.dumps(gt["claim_b"], ensure_ascii=False)
        pieces.append(f"claim_b: {cb[:180]}")
    if gt.get("expected_no_hallucination") is not None:
        pieces.append(f"expected_no_hallucination: {gt['expected_no_hallucination']}")
    if gt.get("rejected_premise"):
        pieces.append(f"rejected_premise: {gt['rejected_premise']}")
    if gt.get("expected_anchor"):
        pieces.append(f"expected_anchor: {gt['expected_anchor']}")
    if gt.get("expected_active_doc"):
        pieces.append(f"expected_active_doc: {gt['expected_active_doc']}")
    return "\n  ".join(pieces) if pieces else "(no GT fields exposed)"


# Heuristic verdict per task
def verdict(r):
    task = r["task"]
    new = r["new_run"]
    gt = r.get("ground_truth") or {}
    ans = (new.get("synthesized_answer") or "").lower()
    docs = new.get("authoritative_doc_ids") or []
    expected_doc = gt.get("expected_doc_id") or gt.get("expected_active_doc")
    cited_correct = False
    if expected_doc:
        cited_correct = any(expected_doc.split("_")[0] in d for d in docs) or any(
            expected_doc in (new.get("synthesized_answer") or "") for d in docs
        )

    # Detect abstention markers (idk)
    idk_markers = [
        "ne contient pas",
        "n'est pas explicitement mentionn",
        "n'est pas directement",
        "ne fournit pas",
        "does not contain",
        "is not explicitly",
        "is not directly",
        "n'est pas précis",
    ]
    is_idk = any(m in ans for m in idk_markers)

    # Detect hallucination signals (premise rejection in T6)
    rejection_markers = [
        "prémisse",
        "premise",
        "n'interdit pas",
        "does not prohibit",
        "n'exige pas",
        "ne prévoit pas",
        "incorrect",
    ]
    rejects_premise = any(m in ans for m in rejection_markers)

    if task == "T1_provenance":
        if is_idk:
            return "STILL_IDK", "Abstient encore alors que GT donne reponse"
        if cited_correct:
            return "IMPROVED", f"Cite bon doc"
        return "PARTIAL", f"Pas d'idk mais doc cite incertain (cite {docs[:2]} vs expected {expected_doc})"

    if task == "T6_robustness":
        if rejects_premise:
            return "IMPROVED", "Rejette la premisse fausse"
        if is_idk:
            return "PARTIAL", "Abstient (mieux que halluciner mais ne rejette pas explicitement)"
        return "STILL_FAIL", "Ne rejette pas la premisse"

    if task == "T7_v2_anchor":
        # Vérifie si l'anchor cité correspond à l'attendu (présence dans la réponse ou docs)
        expected = gt.get("expected_active_doc") or gt.get("expected_anchor") or ""
        if expected and (expected in ans or any(expected in d for d in docs)):
            return "IMPROVED", f"Anchor correct ({expected})"
        if cited_correct:
            return "PARTIAL", f"Cite un doc plausible mais anchor non confirmé"
        return "STILL_FAIL", f"Anchor incorrect (cite {docs[:2]})"

    if task == "T2_contradictions":
        # Contradictions : on regarde si la réponse mentionne 2+ docs (surfaces_both_sides)
        n_doc_cit = ans.count("[doc=")
        if n_doc_cit >= 2:
            return "IMPROVED", f"{n_doc_cit} docs cites (probable both_sides)"
        if is_idk:
            return "STILL_FAIL", "Idk au lieu de surfacer 2 cotes"
        return "PARTIAL", f"{n_doc_cit} doc cite (un seul cote probablement)"

    return "?", ""


print("\n" + "=" * 100)
print("ANALYSE COMPARATIVE — 12 LEMON QUESTIONS — AVANT vs APRES CH-31")
print("=" * 100 + "\n")

verdicts = {"IMPROVED": 0, "PARTIAL": 0, "STILL_IDK": 0, "STILL_FAIL": 0, "?": 0}

for i, r in enumerate(DATA, 1):
    qid = r["question_id"]
    task = r["task"]
    q = r["question"]
    prev = r["previous_judgment"]
    new = r["new_run"]
    gt = r.get("ground_truth") or {}

    v, why = verdict(r)
    verdicts[v] += 1

    print(f"\n[{i}/12] {qid} ({task})  --> {v}  ({why})")
    print(f"Q: {q[:200]}")
    print()
    print(f"GT:")
    print(f"  {gt_excerpt(gt)}")
    print()
    print(f"AVANT: factual={prev.get('factual_correctness','?')}, "
          f"correct_doc={prev.get('correct_doc_cited','?')}, "
          f"says_idk={prev.get('says_idk_when_info_exists','?')}, "
          f"no_hall={prev.get('no_hallucination','?')}, "
          f"answers={prev.get('answers_correctly','?')}")
    print()
    print("APRES (CH-31):")
    print(f"  decomposer: shape={new.get('answer_shape')} hyde={new.get('has_hyde')} "
          f"must={new.get('must_contain')}")
    print(f"  filter: in={new.get('filter_in')} kept={new.get('filter_kept')} "
          f"dropped={new.get('filter_dropped')} called={new.get('filter_called')} "
          f"fb={new.get('filter_fallback')}")
    print(f"  docs: {(new.get('authoritative_doc_ids') or [])[:3]}")
    print(f"  gap={new.get('answer_gap_classification')} trust={new.get('trust_score')}")
    print(f"  ANSWER:")
    ans = new.get("synthesized_answer") or ""
    for line in textwrap.wrap(ans, 110):
        print(f"    {line}")

print("\n" + "=" * 100)
print("RECAPITULATIF")
print("=" * 100)
total = len(DATA)
for k, v in verdicts.items():
    pct = (v * 100 / total) if total else 0
    print(f"  {k:12s}: {v}/{total} ({pct:.0f}%)")
print()
print("Lecture :")
print("  IMPROVED   = comportement clairement meilleur (cite bon doc, rejette fausse premisse, anchor correct...)")
print("  PARTIAL    = ameliore mais pas optimal")
print("  STILL_IDK  = abstient encore alors que GT donne reponse")
print("  STILL_FAIL = meme echec qu'avant")
