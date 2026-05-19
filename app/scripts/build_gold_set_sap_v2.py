"""Construction de gold_set_sap_v2 par sampling stratifié des sets SAP existants
(backup 2026-04-10) - SANS sets KG-derived (risque entités obsolètes).

Sources non-KG :
- gold_set_sap_v1 (30q Fred-rédigé adversarial)
- task1_provenance_human (100q factuel)
- task1_additional_sprint0 (20q)
- task1_pptx_additional (20q)
- task2_contradictions_human (50q + v2 25q)
- task4_audit_human (50q)
- task6_robustness (246q, 10 catégories × 25q environ)

Cible : 155 questions stratifiées avec distribution naturelle (60% factuel/simple, 40% complexe).

Validation : exclure les questions dont les supporting_doc_ids n'existent plus dans
data/poc_a/structures/ (corpus actuel).

Output : benchmark/questions/gold_set_sap_v2.json (format unifié rejudge_only-compatible)

Run :
    docker exec knowbase-app bash -c "cd /app && python scripts/build_gold_set_sap_v2.py"
"""
from __future__ import annotations

import json
import logging
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Backup source (extracted to /tmp/sap_bench)
BACKUP_QUESTIONS = Path("/tmp/sap_bench/benchmark/questions")
GOLDSET_V1 = Path("/app/benchmark/questions/gold_set_sap_v1.json")
STRUCTURES_DIR = Path("/app/data/poc_a/structures")
OUT = Path("/app/benchmark/questions/gold_set_sap_v2.json")
REPORT = Path("/app/doc/ongoing/GOLD_SET_SAP_V2_REPORT.md")

# Sampling targets
TARGETS = {
    "v1_adversarial": 30,  # full gold_set_sap_v1
    "t1_factual": 50,  # provenance_human + sprint0 + pptx (mix)
    "t2_comparison": 25,  # contradictions_human + human_v2
    "t4_audit": 20,  # audit_human
    "t6_robustness": 30,  # 3 per category (10 cats)
}
TOTAL_TARGET = sum(TARGETS.values())  # 155

# Map T6 category -> primary_type (gold_set_v1-compatible)
T6_CATEGORY_MAP = {
    "false_premise": "false_premise",
    "unanswerable": "unanswerable",
    "temporal_evolution": "lifecycle",
    "negation": "negation",
    "synthesis_large": "listing",
    "set_list": "listing",
    "multi_hop": "multi_hop",
    "causal_why": "causal",
    "conditional": "contextual",
    "hypothetical": "contextual",
}

RANDOM_SEED = 42


def load_json(path: Path) -> list[dict]:
    """Load json questions either as list or under 'questions' key."""
    d = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return d.get("questions", d.get("items", []))
    return []


def get_existing_doc_ids() -> set[str]:
    """Retourne les doc_ids présents dans structures/."""
    if not STRUCTURES_DIR.exists():
        logger.warning(f"Structures dir not found: {STRUCTURES_DIR}")
        return set()
    doc_ids = set()
    for p in STRUCTURES_DIR.glob("*.json"):
        # Doc IDs format: 003_SAP_..._hash, last suffix is 8-char hash
        name = p.stem
        doc_ids.add(name)
        # Also add the 8-char hash suffix for fuzzy matching
        if "_" in name:
            doc_ids.add(name.split("_")[-1])
    return doc_ids


def doc_id_exists(doc_id: str, existing: set[str]) -> bool:
    """Check if a doc_id (or its hash suffix) exists in current corpus."""
    if not doc_id:
        return False
    if doc_id in existing:
        return True
    # Try suffix match
    if "_" in doc_id and doc_id.split("_")[-1] in existing:
        return True
    # Try contained-in match (doc_id may be a suffix of a structure filename)
    for ex in existing:
        if doc_id in ex or ex in doc_id:
            return True
    return False


def normalize_t1(q: dict, existing_docs: set[str]) -> dict | None:
    """T1 factual : expected_claim + verbatim_quote.

    Enrichissement : si expected_claim trop court ou redondant avec verbatim,
    on construit une phrase plus complète "{expected_claim}. Source : doc {doc_id}."
    """
    gt = q.get("ground_truth", {})
    doc_id = gt.get("doc_id", "")
    if not doc_id_exists(doc_id, existing_docs):
        return None
    expected = gt.get("expected_claim", "").strip()
    verbatim = gt.get("verbatim_quote", "").strip()
    # Skip if both empty (unusable)
    if not expected and not verbatim:
        return None
    # Build narrative answer
    answer = expected or f"Information explicitement présente dans le document : '{verbatim}'."
    return {
        "id": f"V2_T1_{q.get('question_id', '?')}",
        "question": q.get("question", ""),
        "primary_type": "factual",
        "secondary_types": [],
        "ground_truth": {
            "answer": answer,
            "exact_identifiers": [verbatim] if verbatim else [],
            "supporting_doc_ids": [doc_id] if doc_id else [],
            "answerability": "answerable",
            "false_premise": False,
        },
        "source_set": q.get("task", "T1") + ":" + q.get("source", "?"),
        "category": "factual_simple",
    }


def normalize_t2(q: dict, existing_docs: set[str]) -> dict | None:
    """T2 contradictions/comparison : claim1/claim2 + tension_nature.

    Réponse narrative synthétique : la comparaison/évolution est exprimée
    en prose ; les deux claims sont fondues dans une phrase contextuelle.
    """
    gt = q.get("ground_truth", {})
    claim1 = gt.get("claim1", {})
    claim2 = gt.get("claim2", {})
    doc1 = claim1.get("doc_id", "")
    doc2 = claim2.get("doc_id", "")
    must_docs = q.get("grading_rules", {}).get("must_surface_both_docs", [])
    all_docs = [d for d in (must_docs or [doc1, doc2]) if d]
    valid_docs = [d for d in all_docs if doc_id_exists(d, existing_docs)]
    if not valid_docs or len(valid_docs) < 2:
        return None

    text1 = claim1.get("text", "").strip().rstrip(".")
    text2 = claim2.get("text", "").strip().rstrip(".")
    tension = gt.get("tension_nature", "").strip().lower()
    has_real_tension = gt.get("has_real_tension", False)

    # Map tension type → narrative connector
    if tension in ("evolution", "successive_replacement", "amendment_evolution"):
        connector_intro = "Les deux documents reflètent une évolution chronologique"
        connector_mid = "tandis que"
        conclusion = "Ce n'est pas une contradiction technique mais une mise à jour entre versions."
    elif tension in ("contradiction", "conflict"):
        connector_intro = "Les deux sources présentent une contradiction"
        connector_mid = "alors que"
        conclusion = "Cette contradiction doit être signalée et résolue par référence à la version la plus récente ou applicable."
    elif tension in ("scope_evolution_lifecycle", "scope_extension_lifecycle", "scope_evolution"):
        connector_intro = "Le périmètre a été étendu/modifié entre les deux versions"
        connector_mid = "puis"
        conclusion = "Il s'agit d'une évolution de scope, pas d'une contradiction."
    elif tension in ("complementary_not_conflict", "complementary_distinct_scope"):
        connector_intro = "Les deux sources sont complémentaires et non contradictoires"
        connector_mid = "et parallèlement"
        conclusion = "Les deux informations sont valides dans leurs scopes respectifs."
    elif tension in ("apparent_tension_resolved", "nuance_not_conflict"):
        connector_intro = "Il existe une tension apparente entre les deux sources qui se résout en contexte"
        connector_mid = "tandis que"
        conclusion = "Ce n'est pas une contradiction réelle après lecture en contexte."
    elif tension == "numeric_evolution":
        connector_intro = "Les valeurs numériques ont évolué entre les versions"
        connector_mid = "alors que"
        conclusion = "Cette différence reflète une évolution chiffrée, pas une contradiction."
    elif tension == "lifecycle_not_conflict":
        connector_intro = "Les deux sources documentent un cycle de vie (introduction puis remplacement/évolution)"
        connector_mid = "puis"
        conclusion = "C'est un cycle normal de version, pas une contradiction."
    else:
        connector_intro = "Les deux sources rapportent des informations distinctes"
        connector_mid = "tandis que"
        conclusion = "L'analyse contextuelle permet de comprendre la relation entre les deux."

    answer = f"{connector_intro} : {text1}, {connector_mid} {text2}. {conclusion}"

    return {
        "id": f"V2_T2_{q.get('question_id', '?')}",
        "question": q.get("question", ""),
        "primary_type": "comparison",
        "secondary_types": [],
        "ground_truth": {
            "answer": answer,
            "exact_identifiers": [],
            "supporting_doc_ids": valid_docs,
            "answerability": "answerable",
            "false_premise": False,
            "tension_nature": tension,
            "has_real_tension": has_real_tension,
        },
        "source_set": q.get("task", "T2") + ":" + q.get("source", "?"),
        "category": "comparison",
    }


def normalize_t4(q: dict, existing_docs: set[str]) -> dict | None:
    """T4 audit : expected_docs[] cross-doc synthesis.

    Le ground truth de référence ('answer') est PLACEHOLDER ici car nécessite
    lecture des expected_docs sections pour rédiger une synthèse narrative.
    Rédaction par Claude en batch interactif post-script (cf t4_redact_batch.py).
    """
    gt = q.get("ground_truth", {})
    expected_docs = gt.get("expected_docs", [])
    valid_docs = [d for d in expected_docs if doc_id_exists(d, existing_docs)]
    if not valid_docs:
        return None
    entity = gt.get("entity", "")
    n_claims = gt.get("expected_claim_count", 0)
    n_contradictions = gt.get("expected_contradiction_count", 0)
    return {
        "id": f"V2_T4_{q.get('question_id', '?')}",
        "question": q.get("question", ""),
        "primary_type": "multi_hop",
        "secondary_types": [],
        "ground_truth": {
            "answer": "PENDING_CLAUDE_REDACTION",  # to be filled by t4_redact_batch.py
            "exact_identifiers": [],
            "supporting_doc_ids": valid_docs,
            "answerability": "answerable",
            "false_premise": False,
            "entity": entity,
            "expected_claim_count": n_claims,
            "expected_contradiction_count": n_contradictions,
        },
        "source_set": q.get("task", "T4") + ":" + q.get("source", "?"),
        "category": "multi_hop_audit",
        "_needs_redaction": True,
    }


def normalize_t6(q: dict, existing_docs: set[str]) -> dict | None:
    """T6 robustness : correct_fact + expected_behavior + evidence_claim.

    Enrichissement : si false_premise, on encadre l'answer "La prémisse de la
    question est fausse. {correct_fact}". Pour unanswerable, similar pattern.
    """
    gt = q.get("ground_truth", {})
    doc_id = gt.get("evidence_doc", "") or gt.get("doc_id", "")
    if doc_id and not doc_id_exists(doc_id, existing_docs):
        return None
    cat = q.get("category", "unknown")
    primary = T6_CATEGORY_MAP.get(cat, "contextual")
    correct_fact = gt.get("correct_fact", "").strip()
    expected_claim = gt.get("expected_claim", "").strip()
    evidence = gt.get("evidence_claim", "").strip()
    expected_behavior = gt.get("expected_behavior", "")

    # Build narrative based on expected_behavior
    if expected_behavior == "reject_premise":
        base = correct_fact or "La prémisse de la question est fausse."
        if evidence:
            answer = f"{base} Preuve documentaire : {evidence}"
        else:
            answer = base
    elif expected_behavior in ("abstain", "indicate_unanswerable", "say_unanswerable"):
        base = correct_fact or "Cette information n'est pas couverte par les documents disponibles."
        answer = f"{base} La réponse correcte est de signaler l'absence d'information plutôt que de spéculer."
    else:
        # Standard case : correct_fact or expected_claim, enrich with evidence
        base = correct_fact or expected_claim
        if evidence and evidence not in base:
            answer = f"{base} Cette information est confirmée par : {evidence}"
        else:
            answer = base

    if not answer.strip():
        return None  # Skip if no usable ground truth

    return {
        "id": f"V2_T6_{q.get('question_id', '?')}",
        "question": q.get("question", ""),
        "primary_type": primary,
        "secondary_types": [],
        "ground_truth": {
            "answer": answer,
            "exact_identifiers": [],
            "supporting_doc_ids": [doc_id] if doc_id else [],
            "answerability": "unanswerable" if cat == "unanswerable" or expected_behavior in ("abstain", "indicate_unanswerable", "say_unanswerable") else "answerable",
            "false_premise": expected_behavior == "reject_premise",
        },
        "source_set": "T6_robustness",
        "category": cat,
    }


def normalize_v1(q: dict) -> dict:
    """gold_set_sap_v1 already in good format, just add source tag."""
    q2 = dict(q)
    q2["source_set"] = "gold_set_sap_v1"
    q2["category"] = q.get("primary_type", "unknown")
    q2["id"] = f"V2_V1_{q['id']}"
    return q2


def main():
    random.seed(RANDOM_SEED)
    existing = get_existing_doc_ids()
    logger.info(f"Found {len(existing)} doc_ids in structures dir")

    samples = []

    # 1. gold_set_sap_v1 (30q full)
    v1 = load_json(GOLDSET_V1)
    logger.info(f"[v1] Loading {len(v1)} questions from gold_set_sap_v1")
    for q in v1:
        samples.append(normalize_v1(q))
    logger.info(f"  -> {len(v1)} added")

    # 2. T1 factual (50q from human + sprint0 + pptx)
    t1_pool = []
    for fname in ["task1_provenance_human.json", "task1_additional_sprint0.json", "task1_pptx_additional.json"]:
        path = BACKUP_QUESTIONS / fname
        if path.exists():
            t1_pool.extend(load_json(path))
    valid_t1 = [normalize_t1(q, existing) for q in t1_pool]
    valid_t1 = [q for q in valid_t1 if q is not None]
    logger.info(f"[T1 factual] {len(valid_t1)} valid (after doc_id check) from pool {len(t1_pool)}")
    sampled_t1 = random.sample(valid_t1, min(TARGETS["t1_factual"], len(valid_t1)))
    samples.extend(sampled_t1)

    # 3. T2 comparison (25q from human + v2)
    t2_pool = []
    for fname in ["task2_contradictions_human.json", "task2_contradictions_human_v2.json"]:
        path = BACKUP_QUESTIONS / fname
        if path.exists():
            t2_pool.extend(load_json(path))
    valid_t2 = [normalize_t2(q, existing) for q in t2_pool]
    valid_t2 = [q for q in valid_t2 if q is not None]
    logger.info(f"[T2 comparison] {len(valid_t2)} valid from pool {len(t2_pool)}")
    sampled_t2 = random.sample(valid_t2, min(TARGETS["t2_comparison"], len(valid_t2)))
    samples.extend(sampled_t2)

    # 4. T4 audit (20q)
    t4_pool = load_json(BACKUP_QUESTIONS / "task4_audit_human.json") if (BACKUP_QUESTIONS / "task4_audit_human.json").exists() else []
    valid_t4 = [normalize_t4(q, existing) for q in t4_pool]
    valid_t4 = [q for q in valid_t4 if q is not None]
    logger.info(f"[T4 audit] {len(valid_t4)} valid from pool {len(t4_pool)}")
    sampled_t4 = random.sample(valid_t4, min(TARGETS["t4_audit"], len(valid_t4)))
    samples.extend(sampled_t4)

    # 5. T6 robustness (30q, 3 per category)
    t6_pool = load_json(BACKUP_QUESTIONS / "task6_robustness.json")
    by_cat = defaultdict(list)
    for q in t6_pool:
        norm = normalize_t6(q, existing)
        if norm:
            by_cat[q.get("category", "?")].append(norm)
    sampled_t6 = []
    per_cat_target = 3
    for cat, items in by_cat.items():
        sampled_t6.extend(random.sample(items, min(per_cat_target, len(items))))
    logger.info(f"[T6 robustness] {len(sampled_t6)} sampled from {sum(len(v) for v in by_cat.values())} valid")
    samples.extend(sampled_t6)

    # Final stats
    by_source = Counter(q["source_set"] for q in samples)
    by_primary = Counter(q["primary_type"] for q in samples)

    report_lines = [
        "# gold_set_sap_v2 — Composition Report",
        "",
        f"*Generated : {datetime.utcnow().isoformat()}*",
        f"*Total questions : {len(samples)}*",
        f"*Random seed : {RANDOM_SEED}*",
        "",
        "## Distribution par source",
        "",
        "| Source | n |",
        "|---|---:|",
    ]
    for src, n in sorted(by_source.items(), key=lambda x: -x[1]):
        report_lines.append(f"| {src} | {n} |")

    report_lines.extend([
        "",
        "## Distribution par primary_type",
        "",
        "| primary_type | n | % |",
        "|---|---:|---:|",
    ])
    total = len(samples)
    for ptype, n in sorted(by_primary.items(), key=lambda x: -x[1]):
        report_lines.append(f"| {ptype} | {n} | {n/total:.1%} |")

    report_lines.extend([
        "",
        "## Notes",
        "",
        "- Aucune question issue de sets `_kg` (risque entités obsolètes).",
        "- Toutes les questions T1/T2/T4 sont human-derived.",
        f"- {len(existing)} doc_ids du corpus actuel utilisés pour validation.",
        "- Questions dont `supporting_doc_ids` n'existent plus = écartées.",
        "",
    ])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(samples, indent=2, ensure_ascii=False), encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report_lines), encoding="utf-8")

    print(f"\n[OK] Written: {OUT} ({len(samples)} questions)")
    print(f"[OK] Report : {REPORT}")
    print()
    print("Distribution par primary_type:")
    for ptype, n in sorted(by_primary.items(), key=lambda x: -x[1]):
        print(f"  {ptype:18s} {n:3d}  ({n/total:.1%})")


if __name__ == "__main__":
    main()
