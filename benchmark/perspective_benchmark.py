"""
Benchmark mini Phase 2 — Validation du mode PERSPECTIVE.

25 questions reparties en :
- 10 questions OUVERTES (devraient declencher PERSPECTIVE)
- 10 questions DIRECTES (devraient rester en DIRECT)
- 5 questions AMBIGUES (cas limites)

Pour chaque question, capture :
- Mode resolu (DIRECT / PERSPECTIVE / TENSION / etc.)
- Latence
- Reponse (pour notation manuelle)
- Metadata (perspectives selectionnees, claims injectes, fallback reason)

Output : benchmark_perspective_results.json
"""

import json
import os
import sys
import time
from datetime import datetime

import requests

API_URL = "http://localhost:8000"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin123"


# ============================================================================
# 25 questions de benchmark
# ============================================================================

QUESTIONS = [
    # ─── 10 OUVERTES — devraient declencher PERSPECTIVE ───
    {
        "id": "OPEN-01",
        "category": "open",
        "expected_mode": "PERSPECTIVE",
        "question": "Qu'apporte la nouvelle version de S/4HANA ?",
        "rationale": "Question panoramique typique",
    },
    {
        "id": "OPEN-02",
        "category": "open",
        "expected_mode": "PERSPECTIVE",
        "question": "Quels sont les principaux changements introduits dans SAP S/4HANA ?",
        "rationale": "Vue d'ensemble large",
    },
    {
        "id": "OPEN-03",
        "category": "open",
        "expected_mode": "PERSPECTIVE",
        "question": "Decrivez les fonctionnalites de SAP S/4HANA Cloud Private Edition.",
        "rationale": "Description multi-aspects",
    },
    {
        "id": "OPEN-04",
        "category": "open",
        "expected_mode": "PERSPECTIVE",
        "question": "Vue d'ensemble de l'architecture SAP S/4HANA",
        "rationale": "Pattern 'vue d'ensemble' explicite",
    },
    {
        "id": "OPEN-05",
        "category": "open",
        "expected_mode": "PERSPECTIVE",
        "question": "Qu'est-ce que SAP S/4HANA et quelles sont ses caracteristiques principales ?",
        "rationale": "Question introductive large",
    },
    {
        "id": "OPEN-06",
        "category": "open",
        "expected_mode": "PERSPECTIVE",
        "question": "Quels sont les enjeux d'une migration vers SAP S/4HANA ?",
        "rationale": "Question 'enjeux' multi-dimensionnelle",
    },
    {
        "id": "OPEN-07",
        "category": "open",
        "expected_mode": "PERSPECTIVE",
        "question": "Resume des points cles d'ABAP dans S/4HANA",
        "rationale": "Pattern 'points cles'",
    },
    {
        "id": "OPEN-08",
        "category": "open",
        "expected_mode": "PERSPECTIVE",
        "question": "Decrivez les principales capacites de gestion logistique dans S/4HANA",
        "rationale": "Description de domaine",
    },
    {
        "id": "OPEN-09",
        "category": "open",
        "expected_mode": "PERSPECTIVE",
        "question": "Comment SAP gere-t-il la conformite et la securite dans ses systemes ?",
        "rationale": "Question conformite/securite multi-axes",
    },
    {
        "id": "OPEN-10",
        "category": "open",
        "expected_mode": "PERSPECTIVE",
        "question": "Quels sont les outils et processus pour gerer un upgrade SAP S/4HANA ?",
        "rationale": "Question 'outils et processus'",
    },

    # ─── 10 DIRECTES — devraient rester en DIRECT ───
    {
        "id": "DIRECT-01",
        "category": "direct",
        "expected_mode": "DIRECT",
        "question": "Quelle version de TLS est requise pour les connexions S/4HANA ?",
        "rationale": "Question factuelle precise",
    },
    {
        "id": "DIRECT-02",
        "category": "direct",
        "expected_mode": "DIRECT",
        "question": "Quel objet d'autorisation contrôle l'execution des programmes de paie ?",
        "rationale": "Recherche d'un fait precis",
    },
    {
        "id": "DIRECT-03",
        "category": "direct",
        "expected_mode": "DIRECT",
        "question": "Quels sont les rapports CNS_CP_DELETE disponibles ?",
        "rationale": "Question sur un nom technique specifique",
    },
    {
        "id": "DIRECT-04",
        "category": "direct",
        "expected_mode": "DIRECT",
        "question": "Le client 066 est-il utilise dans SAP S/4HANA ?",
        "rationale": "Question oui/non factuelle",
    },
    {
        "id": "DIRECT-05",
        "category": "direct",
        "expected_mode": "DIRECT",
        "question": "Quel est le nom du tool de migration SAP S/4HANA ?",
        "rationale": "Identification d'un outil precis",
    },
    {
        "id": "DIRECT-06",
        "category": "direct",
        "expected_mode": "DIRECT",
        "question": "Quel rapport RPCIPD00 est associe a quel objet d'autorisation ?",
        "rationale": "Lien entre deux entites precises",
    },
    {
        "id": "DIRECT-07",
        "category": "direct",
        "expected_mode": "DIRECT",
        "question": "Quelle base de donnees SAP S/4HANA necessite-t-il pour fonctionner ?",
        "rationale": "Requirement technique precis",
    },
    {
        "id": "DIRECT-08",
        "category": "direct",
        "expected_mode": "DIRECT",
        "question": "A quoi sert le Software Update Manager dans SAP S/4HANA ?",
        "rationale": "Definition d'un composant",
    },
    {
        "id": "DIRECT-09",
        "category": "direct",
        "expected_mode": "DIRECT",
        "question": "Que fait le rapport PPH_SETUP_MRPRECORDS ?",
        "rationale": "Description fonctionnelle d'un rapport",
    },
    {
        "id": "DIRECT-10",
        "category": "direct",
        "expected_mode": "DIRECT",
        "question": "Quelle est la valeur de SAP_SLL_BC_PI_MM_DOC_TRANS ?",
        "rationale": "Valeur d'un parametre nomme",
    },

    # ─── 5 AMBIGUES — cas limites ───
    {
        "id": "AMBIG-01",
        "category": "ambiguous",
        "expected_mode": "?",
        "question": "Comment fonctionne la securite dans S/4HANA ?",
        "rationale": "Pourrait etre direct ou panoramique",
    },
    {
        "id": "AMBIG-02",
        "category": "ambiguous",
        "expected_mode": "?",
        "question": "Quels sont les prerequis pour installer S/4HANA ?",
        "rationale": "Liste factuelle ou reflexion d'ensemble",
    },
    {
        "id": "AMBIG-03",
        "category": "ambiguous",
        "expected_mode": "?",
        "question": "S/4HANA fonctionne-t-il avec Oracle Database ?",
        "rationale": "Question fermee qui pourrait demander contexte",
    },
    {
        "id": "AMBIG-04",
        "category": "ambiguous",
        "expected_mode": "?",
        "question": "Quels sont les composants de SAP S/4HANA Cloud Private Edition ?",
        "rationale": "Liste ou panorama",
    },
    {
        "id": "AMBIG-05",
        "category": "ambiguous",
        "expected_mode": "?",
        "question": "Comment utiliser le SAP migration cockpit ?",
        "rationale": "Procedure precise ou explication large",
    },
]


# ============================================================================
# Utilitaires
# ============================================================================

def login() -> str:
    """Recupere un token JWT."""
    r = requests.post(
        f"{API_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def search(token: str, question: str, response_mode: str = None) -> dict:
    """Lance une requete search et retourne le resultat."""
    payload = {"question": question}
    if response_mode:
        payload["response_mode"] = response_mode

    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    r = requests.post(
        f"{API_URL}/api/search",
        json=payload,
        headers=headers,
        timeout=180,
    )
    elapsed = time.time() - start
    r.raise_for_status()
    return r.json(), elapsed


# ============================================================================
# Benchmark runner
# ============================================================================

def run_benchmark():
    print("=" * 70)
    print("BENCHMARK PERSPECTIVE — Phase 2 GO/NO-GO")
    print("=" * 70)

    token = login()
    print(f"Token OK ({len(token)} chars)\n")

    results = []
    for i, q in enumerate(QUESTIONS, 1):
        print(f"[{i:2d}/25] {q['id']} ({q['category']}) — {q['question'][:60]}...")

        try:
            data, elapsed = search(token, q["question"])
            synth = data.get("synthesis", {})
            mode_meta = data.get("response_mode_metadata", {})

            answer = synth.get("synthesized_answer", "")
            resolved_mode = mode_meta.get("resolved_mode", "?")
            reason = mode_meta.get("mode_reason", "")
            confidence = synth.get("confidence", 0.0)

            # Detecter la structure (nombre de headers H2/H3)
            n_headers = answer.count("\n##") + answer.count("\n# ")

            result = {
                "id": q["id"],
                "category": q["category"],
                "question": q["question"],
                "expected_mode": q["expected_mode"],
                "resolved_mode": resolved_mode,
                "mode_match": resolved_mode == q["expected_mode"] if q["expected_mode"] != "?" else None,
                "latency_seconds": round(elapsed, 2),
                "confidence": round(confidence, 3),
                "answer_length": len(answer),
                "n_headers": n_headers,
                "n_results": len(data.get("results", [])),
                "answer_preview": answer[:300],
                "answer_full": answer,
                "reason": reason,
            }
            results.append(result)

            match_icon = "OK" if result["mode_match"] else ("--" if q["expected_mode"] == "?" else "KO")
            print(f"        -> {resolved_mode} [{match_icon}] {elapsed:.1f}s, {len(answer)} chars, {n_headers} headers")

        except Exception as e:
            print(f"        ERREUR: {e}")
            results.append({
                "id": q["id"],
                "category": q["category"],
                "question": q["question"],
                "error": str(e),
            })

    # ─── Synthese globale ───
    print("\n" + "=" * 70)
    print("SYNTHESE")
    print("=" * 70)

    open_results = [r for r in results if r.get("category") == "open"]
    direct_results = [r for r in results if r.get("category") == "direct"]
    ambig_results = [r for r in results if r.get("category") == "ambiguous"]

    open_perspective = sum(1 for r in open_results if r.get("resolved_mode") == "PERSPECTIVE")
    direct_perspective = sum(1 for r in direct_results if r.get("resolved_mode") == "PERSPECTIVE")
    direct_direct = sum(1 for r in direct_results if r.get("resolved_mode") == "DIRECT")

    open_avg_headers = sum(r.get("n_headers", 0) for r in open_results) / max(len(open_results), 1)
    open_avg_latency = sum(r.get("latency_seconds", 0) for r in open_results) / max(len(open_results), 1)
    direct_avg_latency = sum(r.get("latency_seconds", 0) for r in direct_results) / max(len(direct_results), 1)

    print(f"\nOuvertes (10 questions) :")
    print(f"  Mode PERSPECTIVE active : {open_perspective}/10")
    print(f"  Headers moyens          : {open_avg_headers:.1f}")
    print(f"  Latence moyenne         : {open_avg_latency:.1f}s")

    print(f"\nDirectes (10 questions) :")
    print(f"  Mode DIRECT maintenu    : {direct_direct}/10")
    print(f"  Mode PERSPECTIVE (regression) : {direct_perspective}/10")
    print(f"  Latence moyenne         : {direct_avg_latency:.1f}s")

    print(f"\nAmbigues (5 questions) :")
    for r in ambig_results:
        print(f"  {r['id']}: {r.get('resolved_mode', '?')} ({r.get('n_headers', 0)} headers)")

    # ─── Verdict GO/NO-GO ───
    print("\n" + "=" * 70)
    print("VERDICT GO / NO-GO Phase 2")
    print("=" * 70)

    criteria = []
    criteria.append(("Ouvertes >=7 en PERSPECTIVE", open_perspective >= 7, f"{open_perspective}/10"))
    criteria.append(("Directes 0 regression", direct_perspective == 0, f"{direct_perspective}/10"))
    criteria.append(("Latence ouvertes < 30s", open_avg_latency < 30, f"{open_avg_latency:.1f}s"))
    criteria.append(("Latence directes < 30s", direct_avg_latency < 30, f"{direct_avg_latency:.1f}s"))

    all_passed = True
    for label, passed, value in criteria:
        icon = "OK" if passed else "KO"
        print(f"  [{icon}] {label}: {value}")
        if not passed:
            all_passed = False

    print(f"\n  >>> VERDICT: {'GO' if all_passed else 'NO-GO'}")

    # ─── Sauvegarde ───
    output = {
        "timestamp": datetime.utcnow().isoformat(),
        "summary": {
            "open_perspective_count": open_perspective,
            "direct_direct_count": direct_direct,
            "direct_perspective_regression": direct_perspective,
            "open_avg_headers": round(open_avg_headers, 1),
            "open_avg_latency_s": round(open_avg_latency, 2),
            "direct_avg_latency_s": round(direct_avg_latency, 2),
            "verdict": "GO" if all_passed else "NO-GO",
        },
        "results": results,
    }
    output_path = "benchmark_perspective_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  Rapport sauvegarde: {output_path}")


if __name__ == "__main__":
    run_benchmark()
