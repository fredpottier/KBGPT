"""
Diagnostic cible de la qualite des Perspectives selectionnees.

Pour chaque question test :
- Mode resolu, latence
- Top 5 Perspectives selectionnees + leurs scores
- Top claims de chaque Perspective (depuis Neo4j)
- Top facets dominantes par Perspective
- Reponse complete pour analyse manuelle

Output : perspective_quality_report.json + affichage console structure.

Objectif : distinguer si le probleme PERSPECTIVE est :
1. Selection : bonnes Perspectives existent mais mal choisies
2. Pollution : la Perspective "Securite" existe mais contient 80% de claims hors sujet
3. Absence : aucune Perspective ne couvre les axes necessaires
"""

import json
import os
import sys
import time
from datetime import datetime

import requests
from neo4j import GraphDatabase

API_URL = "http://localhost:8000"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin123"

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"


# ============================================================================
# 8 questions test (3 anciennes + 5 nouvelles variees)
# ============================================================================

QUESTIONS = [
    # ─── 3 anciennes (deja testees) ───
    {
        "id": "OLD-MIGR",
        "category": "panoramic_migration",
        "question": "Si je dois preparer la migration de notre ECC vers S/4HANA, quels sont les chantiers a anticiper ?",
        "expected": "structured",
        "rationale": "Question panoramique qui DEVRAIT bien marcher (deja testee, OSMOSIS apporte peu)",
    },
    {
        "id": "OLD-EVOL-SEC",
        "category": "evolution_cross_version",
        "question": "En quoi la posture de securite de SAP S/4HANA a-t-elle evolue entre les versions 2021, 2022 et 2023 ?",
        "expected": "structured",
        "rationale": "Question d'evolution cross-version (deja testee, KO car claims n'expriment pas l'evolution)",
    },
    {
        "id": "OLD-META-SEC",
        "category": "meta_corpus_security",
        "question": "Quels sont les concepts de securite communs a tous les guides SAP S/4HANA ?",
        "expected": "structured",
        "rationale": "Question meta sur la securite (deja testee, KO car Perspectives Securite absentes)",
    },

    # ─── 5 nouvelles ───
    {
        "id": "NEW-PANO-INNOV",
        "category": "panoramic_overview",
        "question": "Quelles sont les principales innovations apportees par SAP S/4HANA ?",
        "expected": "structured",
        "rationale": "Overview classique large, axes multiples attendus (fonctionnel, technique, processus)",
    },
    {
        "id": "NEW-PANO-CPE",
        "category": "panoramic_narrow",
        "question": "Quels aspects operationnels couvre SAP S/4HANA Cloud Private Edition ?",
        "expected": "structured",
        "rationale": "Panoramique sur sujet plus precis (CPE), test si Perspectives s'adaptent au sujet",
    },
    {
        "id": "NEW-DIRECT-COMP",
        "category": "direct_component",
        "question": "Quel est le role du SAP Solution Builder ?",
        "expected": "direct",
        "rationale": "Composant nomme, definition factuelle, doit rester DIRECT",
    },
    {
        "id": "NEW-NARROW-MULTI",
        "category": "narrow_multiaspect",
        "question": "Comment fonctionne le Maintenance Planner et a quoi sert-il ?",
        "expected": "direct",
        "rationale": "Cas limite : un seul composant mais demande multi-aspects",
    },
    {
        "id": "NEW-META-MIGR",
        "category": "meta_corpus_tools",
        "question": "Quels outils d'aide a la migration sont documentes dans le corpus ?",
        "expected": "structured",
        "rationale": "Question meta sur les outils, devrait demander une liste organisee",
    },
]


# ============================================================================
# Utilitaires
# ============================================================================

def login() -> str:
    r = requests.post(
        f"{API_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def search(token: str, question: str) -> tuple:
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    r = requests.post(
        f"{API_URL}/api/search",
        json={"question": question},
        headers=headers,
        timeout=180,
    )
    elapsed = time.time() - start
    r.raise_for_status()
    return r.json(), elapsed


def get_perspectives_details(driver, perspective_labels: list) -> dict:
    """Pour chaque Perspective (par label), recupere son contenu detaille."""
    if not perspective_labels:
        return {}

    details = {}
    with driver.session() as session:
        for label in perspective_labels:
            # Trouver la Perspective par label
            result = session.run("""
                MATCH (p:Perspective {tenant_id: $tid})
                WHERE p.label = $label
                RETURN p.perspective_id AS pid,
                       p.subject_name AS subject,
                       p.label AS label,
                       p.claim_count AS claim_count,
                       p.doc_count AS doc_count,
                       p.tension_count AS tension_count,
                       p.coverage_ratio AS coverage,
                       p.representative_texts AS rep_texts,
                       p.source_facet_ids AS facet_ids
                LIMIT 1
            """, tid="default", label=label)
            rec = result.single()
            if not rec:
                continue

            pid = rec["pid"]

            # Recuperer les facets associees
            fr = session.run("""
                MATCH (p:Perspective {perspective_id: $pid})-[:SPANS_FACET]->(f:Facet)
                RETURN f.facet_name AS name, f.facet_id AS fid
            """, pid=pid)
            facets = [dict(r) for r in fr]

            details[label] = {
                "perspective_id": pid,
                "subject": rec["subject"],
                "claim_count": rec["claim_count"],
                "doc_count": rec["doc_count"],
                "tension_count": rec["tension_count"],
                "coverage_ratio": round(rec["coverage"] or 0, 3),
                "representative_texts": (rec["rep_texts"] or [])[:8],
                "facets": facets[:10],
            }
    return details


def compute_perspectives_for_question(driver, question: str, sentence_model) -> list:
    """Replique la logique de chargement + scoring des Perspectives.

    Recupere les Perspectives liees a SAP S/4HANA, SAP, ABAP (sujets dominants),
    les score contre l'embedding de la question, et retourne le top 5.
    """
    import numpy as np

    # Embed la question (avec prefix query: pour E5-large)
    q_embedding = sentence_model.encode(f"query: {question}").tolist()
    q_vec = np.array(q_embedding)

    with driver.session() as session:
        result = session.run("""
            MATCH (p:Perspective {tenant_id: $tid})
            WHERE p.subject_name IN ['SAP S/4HANA', 'SAP', 'ABAP', 'SAP S/4HANA Cloud Private Edition']
            RETURN p.perspective_id AS pid,
                   p.label AS label,
                   p.subject_name AS subject,
                   p.claim_count AS claim_count,
                   p.doc_count AS doc_count,
                   p.tension_count AS tension_count,
                   p.coverage_ratio AS coverage,
                   p.embedding_json AS embedding_json,
                   p.representative_texts AS rep_texts
        """, tid="default")
        all_perspectives = [dict(r) for r in result]

    # Scorer chaque Perspective contre l'embedding de la question
    scored = []
    for p in all_perspectives:
        if not p.get("embedding_json"):
            continue
        try:
            p_emb = json.loads(p["embedding_json"])
            p_vec = np.array(p_emb)
            dot = np.dot(q_vec, p_vec)
            norms = np.linalg.norm(q_vec) * np.linalg.norm(p_vec)
            semantic = float(dot / norms) if norms > 0 else 0.0

            tension_bonus = 0.15 if p["tension_count"] > 0 else 0
            diversity_bonus = 0.10 if p["doc_count"] >= 3 else 0
            coverage_weight = (p["coverage"] or 0) * 0.20
            total = semantic + tension_bonus + diversity_bonus + coverage_weight

            scored.append({
                "label": p["label"],
                "subject": p["subject"],
                "semantic_score": round(semantic, 4),
                "total_score": round(total, 4),
                "claim_count": p["claim_count"],
                "doc_count": p["doc_count"],
                "rep_texts": (p.get("rep_texts") or [])[:5],
            })
        except Exception as e:
            print(f"  Score error for {p.get('label')}: {e}")

    scored.sort(key=lambda x: -x["total_score"])
    return scored[:5]


# ============================================================================
# Diagnostic runner
# ============================================================================

def run_diagnostic():
    print("=" * 80)
    print("DIAGNOSTIC CIBLE — QUALITE DES PERSPECTIVES")
    print("=" * 80)

    token = login()
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # Charger E5-large pour scorer les Perspectives
    print("Loading sentence-transformer (E5-large multilingual)...")
    from sentence_transformers import SentenceTransformer
    sentence_model = SentenceTransformer("intfloat/multilingual-e5-large")
    print("Model loaded.")

    results = []
    for i, q in enumerate(QUESTIONS, 1):
        print(f"\n[{i}/{len(QUESTIONS)}] {q['id']} ({q['category']})")
        print(f"  Question: {q['question']}")
        print(f"  Expected: {q['expected']}")

        try:
            data, elapsed = search(token, q["question"])
            synth = data.get("synthesis", {})
            answer = synth.get("synthesized_answer", "")
            mode_meta = data.get("response_mode_metadata", {})
            resolved_mode = mode_meta.get("resolved_mode", "?")

            n_chunks = len(data.get("results", []))
            n_headers = answer.count("\n##") + answer.count("\n# ")

            # Replique le scoring des Perspectives cote diagnostic (independant des logs)
            scored_perspectives = compute_perspectives_for_question(driver, q["question"], sentence_model)
            selected_labels = [sp["label"] for sp in scored_perspectives]

            # Recuperer les details des Perspectives
            persp_details = get_perspectives_details(driver, selected_labels)

            result = {
                "id": q["id"],
                "category": q["category"],
                "question": q["question"],
                "expected": q["expected"],
                "rationale": q["rationale"],
                "resolved_mode": resolved_mode,
                "mode_match": (resolved_mode == "PERSPECTIVE") == (q["expected"] == "structured"),
                "latency_seconds": round(elapsed, 2),
                "n_chunks": n_chunks,
                "n_headers": n_headers,
                "answer_length": len(answer),
                "answer_full": answer,
                "selected_perspectives": selected_labels,
                "scored_perspectives_full": scored_perspectives,
                "perspectives_details": persp_details,
            }
            results.append(result)

            match_icon = "OK" if result["mode_match"] else "KO"
            print(f"  -> Mode: {resolved_mode} [{match_icon}], {elapsed:.1f}s, {n_headers} headers, {n_chunks} chunks")
            if selected_labels:
                print(f"  Selected perspectives: {selected_labels}")

        except Exception as e:
            print(f"  ERREUR: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "id": q["id"],
                "question": q["question"],
                "error": str(e),
            })

    driver.close()

    # ─── Analyse manuelle ───
    print("\n" + "=" * 80)
    print("ANALYSE MANUELLE — A faire pour chaque question :")
    print("=" * 80)
    print("Pour chaque Perspective selectionnee, regarder ses representative_texts")
    print("et determiner :")
    print("  - Pertinence : claims pertinents pour la question (%) ?")
    print("  - Pollution : claims hors sujet dans la Perspective ?")
    print("  - Absence : axe attendu mais aucune Perspective ne le couvre ?")
    print()

    # ─── Sauvegarde ───
    output = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_questions": len(QUESTIONS),
        "results": results,
    }
    output_path = "perspective_quality_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Rapport sauvegarde: {output_path}")
    print(f"Taille: {os.path.getsize(output_path) / 1024:.1f} KB")


if __name__ == "__main__":
    run_diagnostic()
