#!/usr/bin/env python3
"""Canary Test — 15 questions de non-regression, runable en <2 min.

Usage:
    python benchmark/canary_test.py [--system osmosis|rag|both]

Objectif : detecter rapidement une regression apres un changement de code.
Pas un benchmark complet — juste un filet de securite.
"""

import json
import logging
import os
import sys
import time

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("canary")

VLLM_URL = os.environ.get("VLLM_URL", "http://18.194.28.167:8000")
TEI_URL = os.environ.get("TEI_URL", "http://18.194.28.167:8001")
QDRANT_URL = "http://localhost:6333"
COLLECTION = "knowbase_chunks_v2"
API_BASE = "http://localhost:8000"

# 15 questions canary avec criteres pass/fail simples
CANARY_QUESTIONS = [
    # --- 5 Type A (factuel simple) ---
    {
        "id": "CANARY_A01",
        "type": "A",
        "question": "What is SAP Fiori?",
        "must_contain": ["fiori", "user interface"],
        "must_not_contain": [],
        "must_not_be_idk": True,
    },
    {
        "id": "CANARY_A02",
        "type": "A",
        "question": "Quels sont les prerequis pour la conversion systeme S/4HANA ?",
        "must_contain": ["unicode"],
        "must_not_contain": [],
        "must_not_be_idk": True,
    },
    {
        "id": "CANARY_A03",
        "type": "A",
        "question": "How does the custom code migration work during S/4HANA upgrade?",
        "must_contain": ["custom code"],
        "must_not_contain": [],
        "must_not_be_idk": True,
    },
    {
        "id": "CANARY_A04",
        "type": "A",
        "question": "Quels sont les new default security settings dans S/4HANA ?",
        "must_contain": ["security"],
        "must_not_contain": [],
        "must_not_be_idk": True,
    },
    {
        "id": "CANARY_A05",
        "type": "A",
        "question": "What monitoring capabilities are available in SAP S/4HANA Cloud Private Edition?",
        "must_contain": ["monitor"],
        "must_not_contain": [],
        "must_not_be_idk": True,
    },
    # --- 5 Type B/C (cross-doc, contradictions, audit) ---
    {
        "id": "CANARY_B01",
        "type": "B",
        "question": "Y a-t-il des differences entre les fonctionnalites de S/4HANA Cloud Private Edition 2022 et 2023 ?",
        "must_contain": ["2022", "2023"],
        "must_not_contain": [],
        "must_not_be_idk": True,
    },
    {
        "id": "CANARY_B02",
        "type": "B",
        "question": "Les guides de securite mentionnent-ils des approches differentes pour la gestion des autorisations ?",
        "must_contain": ["autoris", "secur"],
        "must_not_contain": [],
        "must_not_be_idk": True,
    },
    {
        "id": "CANARY_C01",
        "type": "C",
        "question": "Fais un resume complet de ce que disent les documents sur Fiori Launchpad",
        "must_contain": ["fiori", "launchpad"],
        "must_not_contain": [],
        "must_not_be_idk": True,
    },
    {
        "id": "CANARY_C02",
        "type": "C",
        "question": "Que disent tous les documents sur la gestion des autorisations dans S/4HANA ?",
        "must_contain": ["autoris"],
        "must_not_contain": [],
        "must_not_be_idk": True,
    },
    {
        "id": "CANARY_C03",
        "type": "C",
        "question": "Quels aspects de la securite sont couverts dans le corpus documentaire ?",
        "must_contain": ["secur"],
        "must_not_contain": [],
        "must_not_be_idk": True,
    },
    # --- 5 Negatives (doit dire IDK) ---
    {
        "id": "CANARY_NEG01",
        "type": "NEG",
        "question": "Quel est le prix de la licence SAP S/4HANA Cloud ?",
        "must_contain": [],
        "must_not_contain": [],
        "must_be_idk": True,
    },
    {
        "id": "CANARY_NEG02",
        "type": "NEG",
        "question": "Comment SAP S/4HANA se compare-t-il a Oracle ERP Cloud ?",
        "must_contain": [],
        "must_not_contain": ["oracle est"],  # ne doit pas inventer de comparaison
        "must_be_idk": True,
    },
    {
        "id": "CANARY_NEG03",
        "type": "NEG",
        "question": "Quelles sont les vulnerabilites CVE connues pour SAP HANA en 2024 ?",
        "must_contain": [],
        "must_not_contain": ["CVE-"],  # ne doit pas inventer de CVE
        "must_be_idk": True,
    },
    {
        "id": "CANARY_NEG04",
        "type": "NEG",
        "question": "Combien de clients SAP utilisent S/4HANA dans le monde ?",
        "must_contain": [],
        "must_not_contain": [],
        "must_be_idk": True,
    },
    {
        "id": "CANARY_NEG05",
        "type": "NEG",
        "question": "Quel est le cout total de possession (TCO) d'une migration S/4HANA ?",
        "must_contain": [],
        "must_not_contain": [],
        "must_be_idk": True,
    },
]

IDK_MARKERS = [
    "not available", "ne sais pas", "pas disponible", "aucune information",
    "information not available", "no information", "cannot find",
    "ne dispose pas", "pas en mesure", "je ne peux pas",
]


def is_idk(answer: str) -> bool:
    """Detecte si une reponse est un refus."""
    lower = answer.lower()
    if len(answer) < 60:
        return True
    return any(m in lower for m in IDK_MARKERS)


def is_partial_hallucination(answer: str) -> bool:
    """Detecte si le systeme reconnait l'absence mais repond quand meme."""
    lower = answer.lower()
    partial_markers = [
        "pas specifiquement", "not specifically", "pas explicitement",
        "ne contiennent pas", "not mentioned", "pas mentionn",
    ]
    return any(m in lower for m in partial_markers) and len(answer) > 150


def get_osmosis_answer(question: str, token: str) -> str:
    """Appelle l'API OSMOSIS."""
    resp = requests.post(
        f"{API_BASE}/api/search",
        json={
            "question": question,
            "use_graph_context": True,
            "graph_enrichment_level": "standard",
            "use_graph_first": True,
            "use_kg_traversal": True,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    if resp.status_code != 200:
        return f"[ERROR {resp.status_code}]"
    data = resp.json()
    # L'API retourne la synthese dans data["synthesis"]["synthesized_answer"]
    synthesis = data.get("synthesis", {})
    return (
        synthesis.get("synthesized_answer", "")
        or data.get("answer", "")
        or data.get("native_synthesis", "")
    )


def get_rag_answer(question: str) -> str:
    """Appelle TEI + Qdrant + vLLM directement."""
    from openai import OpenAI

    # Embedding
    emb_resp = requests.post(f"{TEI_URL}/embed", json={"inputs": f"query: {question}"}, timeout=10)
    if emb_resp.status_code != 200:
        return "[EMBED ERROR]"
    embedding = emb_resp.json()[0]

    # Qdrant
    search_resp = requests.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/query",
        json={"query": embedding, "limit": 10, "with_payload": True},
        timeout=10,
    )
    points = search_resp.json().get("result", {}).get("points", [])
    chunks = [p.get("payload", {}).get("text", "")[:800] for p in points]

    context = "\n\n".join(f"[Source {i+1}]\n{c}" for i, c in enumerate(chunks))

    client = OpenAI(api_key="EMPTY", base_url=f"{VLLM_URL}/v1")
    resp = client.chat.completions.create(
        model="Qwen/Qwen2.5-14B-Instruct-AWQ",
        messages=[
            {"role": "system", "content": "Answer using ONLY the provided sources. Say 'information not available' if sources don't contain the answer. Answer in the SAME LANGUAGE as the question."},
            {"role": "user", "content": f"Sources:\n{context}\n\nQuestion: {question}"},
        ],
        max_tokens=800,
        temperature=0,
    )
    return resp.choices[0].message.content or ""


def evaluate_answer(q: dict, answer: str) -> dict:
    """Evalue une reponse avec les criteres canary (pas de LLM juge)."""
    lower = answer.lower()
    passed = True
    reasons = []

    # Must contain
    for term in q.get("must_contain", []):
        if term.lower() not in lower:
            passed = False
            reasons.append(f"MISSING '{term}'")

    # Must not contain
    for term in q.get("must_not_contain", []):
        if term.lower() in lower:
            passed = False
            reasons.append(f"UNWANTED '{term}'")

    # IDK checks
    answer_is_idk = is_idk(answer)
    if q.get("must_not_be_idk") and answer_is_idk:
        passed = False
        reasons.append("UNEXPECTED IDK")

    if q.get("must_be_idk"):
        if not answer_is_idk and not is_partial_hallucination(answer):
            passed = False
            reasons.append("SHOULD BE IDK (hallucination)")

    return {
        "passed": passed,
        "reasons": reasons,
        "is_idk": answer_is_idk,
        "is_partial_hallucination": is_partial_hallucination(answer),
        "answer_length": len(answer),
    }


def run_canary(system: str = "both"):
    """Lance le canary test."""
    systems = []
    if system in ("osmosis", "both"):
        systems.append("osmosis")
    if system in ("rag", "both"):
        systems.append("rag")

    # Auth pour OSMOSIS
    token = None
    if "osmosis" in systems:
        try:
            resp = requests.post(
                f"{API_BASE}/api/auth/login",
                json={"email": "admin@example.com", "password": "admin123"},
                timeout=10,
            )
            token = resp.json().get("access_token", "")
        except Exception as e:
            logger.error(f"Auth failed: {e}")
            if "osmosis" in systems and "rag" in systems:
                systems.remove("osmosis")
            else:
                return

    results = {}
    start = time.time()

    for sys_name in systems:
        logger.info(f"\n{'='*50}")
        logger.info(f"CANARY TEST — {sys_name.upper()}")
        logger.info(f"{'='*50}")

        passed_count = 0
        total_count = len(CANARY_QUESTIONS)
        sys_results = []

        for q in CANARY_QUESTIONS:
            try:
                if sys_name == "osmosis":
                    answer = get_osmosis_answer(q["question"], token)
                else:
                    answer = get_rag_answer(q["question"])
            except Exception as e:
                answer = f"[ERROR: {e}]"

            evaluation = evaluate_answer(q, answer)
            status = "PASS" if evaluation["passed"] else "FAIL"
            if evaluation["passed"]:
                passed_count += 1

            reasons_str = ", ".join(evaluation["reasons"]) if evaluation["reasons"] else ""
            logger.info(f"  [{status}] {q['id']} ({q['type']}) {reasons_str}")

            sys_results.append({
                "id": q["id"],
                "type": q["type"],
                "status": status,
                "reasons": evaluation["reasons"],
                "is_idk": evaluation["is_idk"],
                "is_partial_hallucination": evaluation["is_partial_hallucination"],
            })

        # Summary
        type_a = [r for r in sys_results if r["type"] == "A"]
        type_bc = [r for r in sys_results if r["type"] in ("B", "C")]
        type_neg = [r for r in sys_results if r["type"] == "NEG"]

        pass_a = sum(1 for r in type_a if r["status"] == "PASS")
        pass_bc = sum(1 for r in type_bc if r["status"] == "PASS")
        pass_neg = sum(1 for r in type_neg if r["status"] == "PASS")
        partial_halluc = sum(1 for r in type_neg if r["is_partial_hallucination"])

        logger.info(f"\n  SUMMARY [{sys_name.upper()}]:")
        logger.info(f"    Total: {passed_count}/{total_count} passed")
        logger.info(f"    Type A (simple): {pass_a}/{len(type_a)}")
        logger.info(f"    Type B/C (cross-doc): {pass_bc}/{len(type_bc)}")
        logger.info(f"    Negative (IDK): {pass_neg}/{len(type_neg)}")
        logger.info(f"    Partial hallucination: {partial_halluc}/{len(type_neg)}")

        results[sys_name] = {
            "passed": passed_count,
            "total": total_count,
            "pass_rate": passed_count / total_count,
            "type_a": f"{pass_a}/{len(type_a)}",
            "type_bc": f"{pass_bc}/{len(type_bc)}",
            "type_neg": f"{pass_neg}/{len(type_neg)}",
            "partial_hallucination": partial_halluc,
            "details": sys_results,
        }

    elapsed = time.time() - start
    logger.info(f"\nCanary test completed in {elapsed:.1f}s")

    # Save
    with open("benchmark/results/canary_latest.json", "w") as f:
        json.dump(results, f, indent=2)

    # Exit code: 0 if all pass, 1 if any fail
    all_pass = all(r["passed"] == r["total"] for r in results.values())
    if not all_pass:
        logger.warning("\nCANARY TEST FAILED — regression detectee!")
        sys.exit(1)
    else:
        logger.info("\nCANARY TEST PASSED — no regression detected")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Canary test — 15 questions, <2 min")
    parser.add_argument("--system", default="both", choices=["osmosis", "rag", "both"])
    args = parser.parse_args()
    run_canary(args.system)
