#!/usr/bin/env python3
"""Sprint 0 — Tests restants (livrables 4, 5, 7, 8, 9, 10)

Livrable 4 : Test top_k RAG (3/5/10/20)
Livrable 5 : false_answer_rate metric
Livrable 7 : Test IntentResolver sur 275 questions
Livrable 8 : Canonical labels ClaimClusters
Livrable 9+10 : Questions negatives + vagues
"""

import json
import logging
import os
import re
import time
from collections import Counter

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("sprint0")

TEI_URL = os.environ.get("TEI_URL", "http://18.194.28.167:8001")
QDRANT_URL = "http://localhost:6333"
COLLECTION = "knowbase_chunks_v2"


def embed(text):
    r = requests.post(f"{TEI_URL}/embed", json={"inputs": f"query: {text}"}, timeout=10)
    return r.json()[0]


def qdrant_search(embedding, top_k=10):
    r = requests.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/query",
        json={"query": embedding, "limit": top_k, "with_payload": True},
        timeout=10,
    )
    return r.json().get("result", {}).get("points", [])


# ============================================================
# LIVRABLE 4 : Test top_k RAG
# ============================================================

def test_topk():
    """Teste le RAG avec different top_k pour calibrer le baseline."""
    logger.info("=== LIVRABLE 4 : Test top_k RAG ===")

    with open("benchmark/questions/task1_provenance_human.json", encoding="utf-8") as f:
        questions = json.load(f)["questions"][:20]

    results = {}
    for k in [3, 5, 10, 20]:
        total_docs = []
        for q in questions:
            emb = embed(q["question"])
            chunks = qdrant_search(emb, top_k=k)
            docs = set(p.get("payload", {}).get("doc_id", "") for p in chunks)
            total_docs.append(len(docs))

        avg_docs = sum(total_docs) / len(total_docs)
        results[k] = {"avg_docs": avg_docs, "avg_chunks": k}
        logger.info(f"  top_k={k:2d}: avg {avg_docs:.1f} docs distincts")

    return results


# ============================================================
# LIVRABLE 7 : Test IntentResolver
# ============================================================

def test_intent_resolver():
    """Teste un IntentResolver regex sur les 275 questions."""
    logger.info("=== LIVRABLE 7 : Test IntentResolver ===")

    # Patterns de detection
    B_COMPARISON = re.compile(
        r"\b(differ|difference|compar|versus|vs\.?|contrast|"
        r"between .+ and|evolue|evolution|coherent|identique|meme maniere)\b",
        re.IGNORECASE
    )
    C_UNIVERSAL = re.compile(
        r"\b(all|every|each|complete|full|comprehensive|exhaustive|"
        r"across all|throughout|resume complet|tous les documents|"
        r"que disent|que dit|fais un audit|fais un resume)\b",
        re.IGNORECASE
    )
    D_COMPARABLE = re.compile(
        r"\b(minimum|maximum|min|max|threshold|limit|"
        r"version|release|required|requis|patch|seuil)\b",
        re.IGNORECASE
    )

    def classify(question):
        q = question.strip()
        scores = {"A": 0.3, "B": 0.0, "C": 0.0, "D": 0.0}

        if B_COMPARISON.search(q):
            scores["B"] += 0.6
        if C_UNIVERSAL.search(q):
            scores["C"] += 0.6
        if D_COMPARABLE.search(q):
            scores["D"] += 0.4

        best = max(scores, key=scores.get)
        best_score = scores[best]
        second_score = sorted(scores.values(), reverse=True)[1]
        ambiguous = (best_score - second_score) < 0.15

        return best if not ambiguous else "X", best_score, ambiguous

    # Load all questions
    all_questions = []
    for fname in [
        "task1_provenance_kg.json", "task1_provenance_human.json",
        "task2_contradictions_kg.json", "task2_contradictions_human.json",
        "task4_audit_kg.json", "task4_audit_human.json",
    ]:
        try:
            with open(f"benchmark/questions/{fname}", encoding="utf-8") as f:
                qs = json.load(f)["questions"]
                for q in qs:
                    q["_source"] = fname
                all_questions.extend(qs)
        except FileNotFoundError:
            pass

    logger.info(f"  {len(all_questions)} questions chargees")

    # Classify
    classifications = Counter()
    ambiguous_count = 0
    ambiguous_examples = []
    for q in all_questions:
        intent, score, ambiguous = classify(q["question"])
        classifications[intent] += 1
        if ambiguous:
            ambiguous_count += 1
            if len(ambiguous_examples) < 5:
                ambiguous_examples.append(q["question"][:60])

    logger.info(f"  Distribution: {dict(classifications)}")
    logger.info(f"  Ambigues: {ambiguous_count}/{len(all_questions)} ({100*ambiguous_count/len(all_questions):.0f}%)")
    if ambiguous_examples:
        logger.info(f"  Exemples ambigus:")
        for ex in ambiguous_examples:
            logger.info(f"    - {ex}")

    return {"distribution": dict(classifications), "ambiguous_rate": ambiguous_count / len(all_questions)}


# ============================================================
# LIVRABLE 8 : Canonical labels ClaimClusters
# ============================================================

def test_cluster_labels():
    """Verifie la qualite des canonical_labels des ClaimClusters."""
    logger.info("=== LIVRABLE 8 : Canonical labels ClaimClusters ===")

    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "graphiti_neo4j_pass"))

    with driver.session() as session:
        result = session.run("""
            MATCH (cc:ClaimCluster {tenant_id: "default"})
            RETURN cc.canonical_label AS label, cc.claim_count AS cnt, cc.cross_doc AS xdoc,
                   cc.doc_count AS dcnt
            ORDER BY cc.claim_count DESC
        """)
        clusters = [dict(r) for r in result]

    driver.close()

    total = len(clusters)
    empty_labels = sum(1 for c in clusters if not c["label"] or c["label"].strip() == "")
    short_labels = sum(1 for c in clusters if c["label"] and len(c["label"]) < 10)
    cross_doc = sum(1 for c in clusters if c.get("xdoc"))

    logger.info(f"  Total clusters: {total}")
    logger.info(f"  Labels vides: {empty_labels} ({100*empty_labels/total:.0f}%)")
    logger.info(f"  Labels courts (<10 chars): {short_labels} ({100*short_labels/total:.0f}%)")
    logger.info(f"  Cross-doc: {cross_doc} ({100*cross_doc/total:.0f}%)")

    # Top 10 labels
    logger.info(f"  Top 10 labels (par taille de cluster):")
    for c in clusters[:10]:
        logger.info(f"    [{c['cnt']} claims, {c.get('dcnt',1)} docs] {c['label'][:60]}")

    # Bottom 10
    logger.info(f"  Bottom 10 labels:")
    for c in clusters[-10:]:
        logger.info(f"    [{c['cnt']} claims] {(c['label'] or '(vide)')[:60]}")

    return {
        "total": total,
        "empty_labels": empty_labels,
        "short_labels": short_labels,
        "cross_doc": cross_doc,
    }


# ============================================================
# LIVRABLE 9+10 : Questions negatives + vagues
# ============================================================

def create_additional_questions():
    """Cree les questions negatives (pas de reponse dans le corpus) et vagues."""
    logger.info("=== LIVRABLES 9+10 : Questions negatives + vagues ===")

    negative_questions = [
        {"question": "Quel est le prix de la licence SAP S/4HANA Cloud ?",
         "expected": "IDK", "reason": "Aucun document ne contient les prix des licences"},
        {"question": "Comment SAP S/4HANA se compare-t-il a Oracle ERP Cloud ?",
         "expected": "IDK", "reason": "Aucune comparaison avec Oracle dans le corpus"},
        {"question": "Quels sont les bugs connus de la version 2023 FPS03 ?",
         "expected": "IDK", "reason": "Pas de bug list dans les documents"},
        {"question": "Combien de clients SAP utilisent S/4HANA dans le monde ?",
         "expected": "IDK", "reason": "Pas de statistiques d'adoption dans le corpus"},
        {"question": "Quel est le SLA de disponibilite garanti pour RISE with SAP ?",
         "expected": "IDK", "reason": "Pas de SLA chiffre dans les documents fournis"},
        {"question": "Comment migrer de SAP Business One vers S/4HANA ?",
         "expected": "IDK", "reason": "Business One n'est pas couvert dans les guides de conversion"},
        {"question": "Quelles sont les vulnerabilites CVE connues pour SAP HANA en 2024 ?",
         "expected": "IDK", "reason": "Pas de CVE dans les documents"},
        {"question": "Quel est le calendrier de release de S/4HANA 2026 ?",
         "expected": "IDK", "reason": "Les documents ne couvrent que jusqu'a 2025"},
        {"question": "Comment configurer SAP SuccessFactors Employee Central ?",
         "expected": "IDK", "reason": "SuccessFactors n'est mentionne que brievement pour l'integration"},
        {"question": "Quel est le cout total de possession (TCO) d'une migration S/4HANA ?",
         "expected": "IDK", "reason": "Pas d'analyse TCO dans les documents techniques"},
    ]

    vague_questions = [
        {"question": "comment on fait pour upgrader ?",
         "expected": "reponse sur upgrade S/4HANA", "type": "vague_fr"},
        {"question": "c'est quoi le truc Fiori la ?",
         "expected": "explication SAP Fiori", "type": "vague_fr"},
        {"question": "Quels sont les prerequis pour le system conversion ?",
         "expected": "prerequis conversion S/4HANA", "type": "code_switch"},
        {"question": "ya des security issues avec la config par defaut ?",
         "expected": "new default security settings", "type": "vague_fr"},
        {"question": "how does the upgrade work with the custom code stuff?",
         "expected": "custom code migration during upgrade", "type": "english"},
        {"question": "les autorisations c'est gere comment dans le nouveau systeme ?",
         "expected": "authorization concept S/4HANA", "type": "vague_fr"},
        {"question": "what changed between 2022 and 2023 version?",
         "expected": "differences entre versions", "type": "english_vague"},
        {"question": "faut faire quoi avant de migrer ?",
         "expected": "prerequis conversion/upgrade", "type": "vague_fr"},
        {"question": "le monitoring on peut faire quoi avec ?",
         "expected": "monitoring dans Operations Guide", "type": "vague_fr"},
        {"question": "Fiori launchpad setup how?",
         "expected": "configuration Fiori Launchpad", "type": "code_switch"},
    ]

    output = {
        "metadata": {
            "task": "T1",
            "source": "sprint0_additional",
            "count": len(negative_questions) + len(vague_questions),
        },
        "questions": [],
    }

    for i, nq in enumerate(negative_questions):
        output["questions"].append({
            "question_id": f"T1_NEG_{i:04d}",
            "task": "T1_provenance",
            "question": nq["question"],
            "ground_truth": {"expected_claim": nq["expected"], "doc_id": "NONE"},
            "grading_rules": {"must_say_idk": True, "reason": nq["reason"]},
            "_type": "negative",
        })

    for i, vq in enumerate(vague_questions):
        output["questions"].append({
            "question_id": f"T1_VAGUE_{i:04d}",
            "task": "T1_provenance",
            "question": vq["question"],
            "ground_truth": {"expected_claim": vq["expected"], "doc_id": "multi_doc"},
            "grading_rules": {},
            "_type": vq["type"],
        })

    path = "benchmark/questions/task1_additional_sprint0.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info(f"  Cree {len(negative_questions)} questions negatives + {len(vague_questions)} vagues")
    logger.info(f"  Sauve dans {path}")

    return {"negative": len(negative_questions), "vague": len(vague_questions)}


# ============================================================
# MAIN
# ============================================================

def main():
    results = {}

    logger.info("Sprint 0 — Tests restants\n")

    # Livrable 4 : top_k
    results["topk"] = test_topk()

    # Livrable 7 : IntentResolver
    results["intent"] = test_intent_resolver()

    # Livrable 8 : Cluster labels
    results["clusters"] = test_cluster_labels()

    # Livrable 9+10 : Questions additionnelles
    results["questions"] = create_additional_questions()

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("SPRINT 0 — RESUME DES RESULTATS")
    logger.info("=" * 60)
    logger.info(f"top_k: {json.dumps(results['topk'], indent=2)}")
    logger.info(f"intent: {json.dumps(results['intent'], indent=2)}")
    logger.info(f"clusters: {json.dumps(results['clusters'], indent=2)}")
    logger.info(f"questions: {json.dumps(results['questions'], indent=2)}")

    # Save
    with open("benchmark/results/sprint0_remaining_results.json", "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Resultats sauves dans benchmark/results/sprint0_remaining_results.json")


if __name__ == "__main__":
    main()
