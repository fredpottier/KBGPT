"""Construit le gold-set AÉRO (corpus sièges/crashworthiness) ancré sur le KG réel.

Produit, au schéma a38 exact (cf gold_set_a38_50q.json) :
    benchmark/questions/gold_set_aero_150q.json   — bench complet (variabilité réduite)
    benchmark/questions/gold_set_aero_50q.json    — sous-ensemble stratifié (évals régulières)
    benchmark/questions/gold_set_aero_cp.json      — paires de conflit (conflict_exposure)

PRINCIPE ANTI-HALLUCINATION
    Les `exact_identifiers`, `supporting_doc_ids` et la réponse de référence proviennent
    de claims RÉELS du KG (tenant=default). Le LLM ne fait que FORMULER une question
    naturelle dont la réponse est ce claim — il choisit ses identifiants dans la liste
    fournie (il ne peut pas en inventer). false_premise / unanswerable sont gabarités
    autour d'entités réelles du corpus (prémisse fausse plausible / hors-périmètre).

Distribution 150q :
    factual 45 · list 15 · lifecycle 20 · comparison 20 · multi_hop 15 ·
    contextual 10 · false_premise 15 · unanswerable 10
Le 50q est un sous-échantillon stratifié DU 150q (seed fixe) → cohérence.

Usage :
    docker exec knowbase-app python scripts/build_gold_set_aero.py            # plein (LLM)
    docker exec knowbase-app python scripts/build_gold_set_aero.py --no-llm   # gabarits seuls (dry)
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("build_gold_set_aero")

NEO4J_URI = "bolt://neo4j:7687"
NEO4J_AUTH = ("neo4j", "graphiti_neo4j_pass")
TENANT = "default"
OUT_DIR = ROOT / "benchmark" / "questions"

QUOTAS_150 = {
    "factual": 45, "list": 15, "lifecycle": 20, "comparison": 20,
    "multi_hop": 15, "contextual": 10, "false_premise": 15, "unanswerable": 10,
}
QUOTAS_50 = {
    "factual": 15, "list": 5, "lifecycle": 7, "comparison": 7,
    "multi_hop": 5, "contextual": 3, "false_premise": 5, "unanswerable": 3,
}

# ── Identifiants réglementaires aéro (regex) ────────────────────────────
ID_PATTERNS = [
    r'\bE?TSO-C\d+[a-z]?\b',                 # TSO-C127, ETSO-C127c
    r'\bAC \d+[.\-]\d+(?:-\d+)?[A-Z]?\b',    # AC 25.562-1B, AC 20-146A
    r'\b\d+\s?CFR\s?(?:part\s?)?\d+(?:\.\d+)?\b',  # 14 CFR 25.562
    r'\bCS[ -]?\d+(?:\.\d+)?\b',             # CS-25, CS 25.562
    r'§+\s?\d+\.\d+[a-z]?\b',                # § 25.562
    r'\b(?:ARP|AS)\s?\d+[A-Z]?\b',           # SAE ARP5526, AS8049C
    r'\bAmendment\s?\d+-\d+\b',              # Amendment 25-64
    r'\b\d{1,3}\s?g\b',                      # 16g, 14g, 9g
    r'\bHIC(?:\s?\d{2,4})?\b',               # HIC, HIC 1000
    # charges/vitesses/unités : gère séparateur de milliers + unités composées (in-lb)
    r'\b\d{1,3}(?:,\d{3})*\s?(?:lbf?|N|ft/s|fps|deg(?:rees)?|in(?:ch(?:es)?)?(?:[-\s]?lbf?)?|ms)\b',
    r'\b(?:19|20)\d{2}\b',                   # années
]


def extract_ids(text: str) -> List[str]:
    found: List[str] = []
    for pat in ID_PATTERNS:
        for m in re.findall(pat, text or "", flags=re.IGNORECASE):
            s = m.strip()
            if s and s.lower() not in (x.lower() for x in found):
                found.append(s)
    return found[:6]


# ── Accès KG ─────────────────────────────────────────────────────────────
def _driver():
    from neo4j import GraphDatabase
    return GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)


def fetch_claims(drv) -> List[Dict[str, Any]]:
    """Tous les claims du tenant avec texte/doc/sf/conditions/prédicat."""
    cy = """
    MATCH (c:Claim) WHERE c.tenant_id=$t AND c.text IS NOT NULL AND size(c.text) > 30
    RETURN c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id,
           c.subject_canonical AS subject, c.predicate AS predicate,
           c.claim_type AS ctype, c.scope_conditions AS conditions
    """
    with drv.session() as s:
        rows = [r.data() for r in s.run(cy, t=TENANT)]
    for r in rows:
        r["ids"] = extract_ids(r["text"])
    return rows


# ── Familles documentaires (pour comparaison FAA/EASA + lignée) ─────────
FAA_DOCS = ("AC_", "CFR_part25", "TSO")
EASA_DOCS = ("CS-25", "ETSO", "NPA")
def authority_of(doc_id: str) -> Optional[str]:
    if any(k in doc_id for k in ("CS-25", "ETSO", "NPA")):
        return "EASA"
    if any(doc_id.startswith(k) or k in doc_id for k in ("AC_", "CFR_part25", "TSO")):
        return "FAA"
    return None


# ── Formulation LLM (hébergée, hors-burst) ──────────────────────────────
_PHRASE_SYS = (
    "You are a benchmark author for an aircraft-seat certification knowledge base. "
    "Given a factual statement extracted from a regulatory document, write ONE natural, "
    "specific question (in English) whose correct answer IS that statement. The question "
    "must be answerable ONLY from the statement, mention the concrete subject, and NOT leak "
    "the answer. Return JSON only: {\"question\": \"...\", \"answer\": \"<concise factual answer>\"}."
)


def phrase_one(router, task_type, claim_text: str, type_hint: str) -> Optional[Dict[str, str]]:
    try:
        user = (
            f"QUESTION TYPE: {type_hint}\n"
            f"STATEMENT (from a real regulatory doc): \"{claim_text}\"\n\n"
            "Write the question + concise reference answer. JSON only."
        )
        raw = router.complete(
            task_type=task_type,
            messages=[{"role": "system", "content": _PHRASE_SYS}, {"role": "user", "content": user}],
            temperature=0.2, max_tokens=220,
        )
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if not m:
            return None
        obj = json.loads(m.group(0))
        q = (obj.get("question") or "").strip()
        a = (obj.get("answer") or "").strip()
        if len(q) < 12 or len(a) < 4:
            return None
        return {"question": q, "answer": a}
    except Exception as exc:
        logger.debug("phrase_one failed: %s", exc)
        return None


# ── Sélection de candidats par type ─────────────────────────────────────
def select_candidates(claims: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    rng = random.Random(1234)
    cand: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    id_bearing = [c for c in claims if c["ids"]]
    rng.shuffle(id_bearing)

    # factual : claim avec >=1 identifiant fort, texte court-moyen
    cand["factual"] = [c for c in id_bearing if 40 <= len(c["text"]) <= 240][:120]

    # list : énumérations (>=2 virgules ou mots-clés de liste)
    cand["list"] = [c for c in claims if (c["text"].count(",") >= 2 or
                    re.search(r"\b(following|include[sd]?|such as|listed)\b", c["text"], re.I))][:60]
    rng.shuffle(cand["list"])

    # lifecycle : prédicat de succession OU mention cancel/supersede/amend/replace
    cand["lifecycle"] = [c for c in claims if (c.get("predicate") in ("REPLACES", "AMENDS", "SUPERSEDES")
                         or re.search(r"\b(cancel+ed|supersed|replac|amend|redesignat|deleted)\b", c["text"], re.I))][:80]
    rng.shuffle(cand["lifecycle"])

    # contextual : claims porteurs de conditions
    cand["contextual"] = [c for c in claims if c.get("conditions")][:80]
    rng.shuffle(cand["contextual"])

    # multi_hop : claims à identifiant, on en chaînera 2 du même doc
    cand["multi_hop"] = id_bearing[:120]

    # comparison : appariement FAA/EASA fait à part (select_comparison)
    return cand


def topic_key(text: str) -> str:
    """Clé de sujet grossière pour apparier FAA vs EASA (concepts crashworthiness)."""
    t = text.lower()
    for kw in ["16g", "14g", "hic", "lumbar", "femur", "head injury", "emergency landing",
               "flammability", "flame", "dynamic test", "side-facing", "oblique", "restraint",
               "occupant", "seat belt", "pelvis", "spinal"]:
        if kw in t:
            return kw
    return ""


def select_comparison(claims: List[Dict[str, Any]], rng: random.Random) -> List[Dict[str, Any]]:
    """Paires (claim FAA, claim EASA) sur le même concept crashworthiness."""
    faa, easa = defaultdict(list), defaultdict(list)
    for c in claims:
        auth = authority_of(c["doc_id"]); tk = topic_key(c["text"])
        if not auth or not tk:
            continue
        (faa if auth == "FAA" else easa)[tk].append(c)
    pairs = []
    for tk in set(faa) & set(easa):
        rng.shuffle(faa[tk]); rng.shuffle(easa[tk])
        for a, b in zip(faa[tk][:3], easa[tk][:3]):
            pairs.append({"topic": tk, "faa": a, "easa": b})
    rng.shuffle(pairs)
    return pairs


# ── Gabarits false_premise / unanswerable (entités réelles, twist faux) ─
FALSE_PREMISE_SEEDS = [
    ("Which paragraph of AC 25.562-1C defines the 25g vertical sled test?",
     "There is no AC 25.562-1C: the current revision is AC 25.562-1B. The 25.562 dynamic tests are 16g (horizontal) and 14g (vertical), not a 25g vertical test."),
    ("How does TSO-C127d update the lumbar load limit compared to TSO-C127c?",
     "There is no TSO-C127d; the latest revision is TSO-C127c (EASA ETSO-C127c). The lumbar compressive load limit is 1,500 lb under § 25.562."),
    ("What is the 30g horizontal test pulse required by 14 CFR 25.562?",
     "14 CFR 25.562 does not require a 30g horizontal pulse: the horizontal dynamic test uses a minimum 16g peak deceleration."),
    ("Which CS-25 amendment introduced the mandatory 5-point harness for all transport seats?",
     "CS-25 does not mandate a 5-point harness for all transport seats; restraint requirements derive from CS 25.562/25.785 and depend on seat orientation."),
    ("Under AC 20-146A, what is the maximum allowed Head Injury Criterion value of 2000?",
     "The HIC limit under the 25.562 dynamic test is 1,000, not 2,000. AC 20-146A addresses certification by analysis, not a HIC of 2000."),
    ("What is the femur axial load limit of 3000 lb specified in § 25.562?",
     "The femur (tibia/femur) axial compressive load limit under 25.562 is 2,250 lb, not 3,000 lb."),
    ("Which annex of ETSO-C127c lists the 19g emergency landing condition?",
     "ETSO-C127c does not contain a 19g condition; the 25.562 emergency-landing dynamic conditions are 16g horizontal and 14g vertical."),
    ("Under TSO-C39c, what dynamic 16g sled test must transport seats pass?",
     "TSO-C39c covers 9g STATIC testing of transport seats, not a 16g dynamic sled test (the dynamic 16g/14g regime is TSO-C127 / § 25.562)."),
    ("What vertical velocity change of 45 ft/s does 14 CFR 25.562 require for the downward test?",
     "The downward (30° pitch) dynamic test specifies a velocity change of at least 35 ft/s, not 45 ft/s."),
    ("Which paragraph of AC 20-146B describes dynamic seat certification by analysis?",
     "There is no AC 20-146B; the current revision is AC 20-146A. It addresses certification by analysis (validation/verification of the seat dynamic model)."),
    ("How does AC 25.853-1 set the side-facing seat HIC limit at 700?",
     "AC 25.853-1 concerns flammability/fire protection, not occupant injury criteria; it does not set a HIC limit, and the dynamic-test HIC limit is 1,000."),
    ("Since CS-25 Amendment removed the lumbar load criterion, what replaced it?",
     "The lumbar compressive load criterion (1,500 lb) was not removed from CS 25.562; it remains an injury-acceptance criterion."),
    ("Which FAA rule mandates a 5th-percentile female ATD for every 25.562 dynamic test?",
     "The 25.562 dynamic tests use a 50th-percentile anthropomorphic test dummy (Hybrid II/equivalent); a 5th-percentile female ATD is not mandated for every test."),
    ("Under § 25.785, when did dynamic 16g testing replace the 9g static requirement entirely?",
     "Dynamic 16g testing (25.562) was added alongside, not as a replacement of, the 9g static emergency-landing loads of 25.561/25.785; both regimes coexist."),
    ("What is the maximum 0.5-second HIC window allowed by AC 20-146A?",
     "HIC is computed over a 36-millisecond window (HIC36), not a 0.5-second window; AC 20-146A does not redefine the HIC window."),
]
UNANSWERABLE_SEEDS = [
    ("What is the unit purchase price of a Safran Z600 business-class seat for Emirates?",
     "Commercial pricing of seat units is not contained in the regulatory corpus."),
    ("How many seats did Safran deliver to Airbus in 2024?",
     "Delivery volumes to a specific airframer are not part of the certification corpus."),
    ("Which specific aircraft tail numbers were used in the AC 25.562-1B dynamic test campaign?",
     "Individual aircraft tail numbers are not documented in the regulatory corpus."),
    ("What is the warranty period offered by seat manufacturers under FAA rules?",
     "Commercial warranty terms are not governed by the certification regulations in the corpus."),
    ("What is the production lead time for an ETSO-C127c certified seat?",
     "Manufacturing lead times are commercial data absent from the regulatory corpus."),
    ("Which test laboratory performed the validation campaign behind AC 20-146A?",
     "The identity of specific test laboratories is not recorded in the regulatory corpus."),
    ("What is the mass in kilograms of a typical ETSO-C127c certified economy seat?",
     "Seat unit weights are product-specific data not present in the certification corpus."),
    ("How many months does FAA certification of a new transport seat usually take?",
     "Certification programme timelines are not specified in the regulatory documents."),
    ("What market share does Safran hold in the aircraft-seat industry?",
     "Market-share figures are commercial data outside the regulatory corpus."),
    ("Which airlines have already retrofitted seats compliant with AC 25.562-1B?",
     "Airline-level fleet retrofit status is not contained in the regulatory corpus."),
]


def qid(prefix: str, i: int) -> str:
    return f"AERO_{prefix}_{i:04d}"


def make_item(qid_: str, qtype: str, question: str, answer: str,
              ids: List[str], doc_ids: List[str], answerability="answerable",
              false_premise=False, category="", secondary=None) -> Dict[str, Any]:
    return {
        "id": qid_, "question": question, "primary_type": qtype,
        "secondary_types": secondary or [], "language": "en",
        "ground_truth": {
            "answer": answer,
            "exact_identifiers": ids,
            "supporting_doc_ids": doc_ids,
            "answerability": answerability,
            "false_premise": false_premise,
        },
        "source_set": "aero_kg_grounded", "category": category or qtype,
    }


def build(no_llm: bool):
    drv = _driver()
    claims = fetch_claims(drv)
    logger.info("claims chargés: %d (avec identifiant: %d)", len(claims), sum(1 for c in claims if c["ids"]))
    rng = random.Random(1234)

    router = None
    task_type = None
    if not no_llm:
        from knowbase.common.llm_router import LLMRouter, TaskType
        router = LLMRouter(); task_type = TaskType.FAST_CLASSIFICATION

    cand = select_candidates(claims)
    comp_pairs = select_comparison(claims, rng)
    items: List[Dict[str, Any]] = []
    counter = defaultdict(int)

    def phrase(text, hint, fallback_q):
        if router is None:
            return {"question": fallback_q, "answer": text[:300]}
        r = phrase_one(router, task_type, text, hint)
        return r or {"question": fallback_q, "answer": text[:300]}

    # factual / list / lifecycle / contextual — 1 claim → 1 question ancrée
    simple_specs = [
        ("factual", QUOTAS_150["factual"], "factual identifier", "What does the document specify regarding {subj}?"),
        ("list", QUOTAS_150["list"], "list / enumeration", "What items are listed regarding {subj}?"),
        ("lifecycle", QUOTAS_150["lifecycle"], "version succession / supersession", "What changed for {subj} across revisions?"),
        ("contextual", QUOTAS_150["contextual"], "condition-dependent", "Under its stated condition, what applies to {subj}?"),
    ]
    for qtype, quota, hint, fb in simple_specs:
        pool = cand.get(qtype, [])
        for c in pool:
            if counter[qtype] >= quota:
                break
            subj = (c.get("subject") or "this provision")
            ph = phrase(c["text"], hint, fb.replace("{subj}", subj))
            ids = c["ids"] if qtype != "list" else (c["ids"] or [])
            counter[qtype] += 1
            items.append(make_item(
                qid(qtype[:4].upper(), counter[qtype]), qtype, ph["question"], ph["answer"],
                ids, [c["doc_id"]],
                answerability="answerable", category=qtype,
            ))

    # comparison FAA/EASA — paire de claims
    for p in comp_pairs:
        if counter["comparison"] >= QUOTAS_150["comparison"]:
            break
        faa, easa = p["faa"], p["easa"]
        merged_ids = (faa["ids"] + easa["ids"])[:6]
        fb = f"How do FAA and EASA differ on '{p['topic']}' for aircraft seats?"
        if router is not None:
            r = phrase_one(router, task_type,
                           f"FAA says: {faa['text']}\nEASA says: {easa['text']}", "FAA vs EASA comparison")
            q = r["question"] if r else fb
            a = r["answer"] if r else f"FAA: {faa['text'][:140]} | EASA: {easa['text'][:140]}"
        else:
            q, a = fb, f"FAA: {faa['text'][:140]} | EASA: {easa['text'][:140]}"
        counter["comparison"] += 1
        items.append(make_item(
            qid("CMP", counter["comparison"]), "comparison", q, a, merged_ids,
            [faa["doc_id"], easa["doc_id"]], category="faa_easa_comparison",
            secondary=["contradiction"],
        ))

    # multi_hop — 2 claims du même doc (chaîne)
    by_doc = defaultdict(list)
    for c in cand["multi_hop"]:
        by_doc[c["doc_id"]].append(c)
    for doc, cs in by_doc.items():
        if counter["multi_hop"] >= QUOTAS_150["multi_hop"]:
            break
        if len(cs) < 2:
            continue
        a1, a2 = cs[0], cs[1]
        fb = "Combining the relevant provisions, what is required?"
        if router is not None:
            r = phrase_one(router, task_type, f"Fact 1: {a1['text']}\nFact 2: {a2['text']}",
                           "multi-step reasoning combining two facts")
            q = r["question"] if r else fb
            a = r["answer"] if r else f"{a1['text'][:140]} ; {a2['text'][:140]}"
        else:
            q, a = fb, f"{a1['text'][:140]} ; {a2['text'][:140]}"
        counter["multi_hop"] += 1
        items.append(make_item(
            qid("MH", counter["multi_hop"]), "multi_hop", q, a,
            (a1["ids"] + a2["ids"])[:6], [doc], category="multi_hop",
        ))

    # false_premise — gabarits (entités réelles, prémisse fausse)
    for i, (q, a) in enumerate(FALSE_PREMISE_SEEDS):
        if counter["false_premise"] >= QUOTAS_150["false_premise"]:
            break
        counter["false_premise"] += 1
        items.append(make_item(qid("FP", counter["false_premise"]), "false_premise", q, a,
                               extract_ids(q + " " + a), [], answerability="answerable",
                               false_premise=True, category="false_premise"))

    # unanswerable — gabarits hors-périmètre
    for i, (q, a) in enumerate(UNANSWERABLE_SEEDS):
        if counter["unanswerable"] >= QUOTAS_150["unanswerable"]:
            break
        counter["unanswerable"] += 1
        items.append(make_item(qid("UN", counter["unanswerable"]), "unanswerable", q, a,
                               [], [], answerability="unanswerable", false_premise=False,
                               category="unanswerable"))

    drv.close()

    logger.info("généré par type: %s", dict(counter))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    full = OUT_DIR / "gold_set_aero_150q.json"
    full.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("écrit %s (%d questions)", full, len(items))

    # sous-ensemble 50q stratifié
    by_type = defaultdict(list)
    for it in items:
        by_type[it["primary_type"]].append(it)
    sub: List[Dict[str, Any]] = []
    for t, q50 in QUOTAS_50.items():
        pool = by_type.get(t, [])
        rng.shuffle(pool)
        sub.extend(pool[:q50])
    sub_path = OUT_DIR / "gold_set_aero_50q.json"
    sub_path.write_text(json.dumps(sub, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("écrit %s (%d questions)", sub_path, len(sub))

    # validation groundedness
    docset = {c["doc_id"] for c in claims}
    bad = [it["id"] for it in items
           if it["ground_truth"]["answerability"] == "answerable"
           and it["ground_truth"]["supporting_doc_ids"]
           and not all(d in docset for d in it["ground_truth"]["supporting_doc_ids"])]
    if bad:
        logger.warning("doc_ids hors corpus dans %d questions: %s", len(bad), bad[:5])
    else:
        logger.info("groundedness OK : tous les supporting_doc_ids existent dans le KG")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="gabarits seuls, sans formulation LLM")
    args = ap.parse_args()
    build(no_llm=args.no_llm)
