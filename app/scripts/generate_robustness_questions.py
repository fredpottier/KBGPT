#!/usr/bin/env python3
"""Generate 175+ robustness benchmark questions from corpus claims via Qwen/vLLM."""

import json
import pickle
import random
import sys
import os
import requests
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

random.seed(42)
VLLM = "http://3.71.166.45:8000/v1/chat/completions"


def ask_qwen(prompt, max_tokens=4000):
    resp = requests.post(VLLM, json={
        "model": "Qwen/Qwen2.5-14B-Instruct-AWQ",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.3,
    }, timeout=60)
    return resp.json()["choices"][0]["message"]["content"]


def parse_json(resp):
    if "```" in resp:
        resp = resp.split("```")[1]
        if resp.startswith("json"):
            resp = resp[4:]
    return json.loads(resp)


def extract_claims():
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))
    claims = {}

    with driver.session() as s:
        r = list(s.run('MATCH (c:Claim {tenant_id: "default"}) WHERE c.text CONTAINS " not " OR c.text CONTAINS " cannot " OR c.text CONTAINS " only " OR c.text CONTAINS " unless " OR c.text CONTAINS " without " RETURN c.text AS t, c.doc_id AS d LIMIT 60'))
        random.shuffle(r)
        claims["negation"] = [{"text": x["t"], "doc": x["d"]} for x in r[:30]]

        r = list(s.run('MATCH (c:Claim {tenant_id: "default"}) WHERE c.text CONTAINS " if " OR c.text CONTAINS " when " OR c.text CONTAINS " requires " OR c.text CONTAINS " only if " RETURN c.text AS t, c.doc_id AS d LIMIT 60'))
        random.shuffle(r)
        claims["conditional"] = [{"text": x["t"], "doc": x["d"]} for x in r[:30]]

        r = list(s.run('MATCH (c:Claim {tenant_id: "default"}) WHERE c.text CONTAINS " to ensure " OR c.text CONTAINS " to prevent " OR c.text CONTAINS " to protect " OR c.text CONTAINS " because " OR c.text CONTAINS " in order to " RETURN c.text AS t, c.doc_id AS d LIMIT 60'))
        random.shuffle(r)
        claims["causal"] = [{"text": x["t"], "doc": x["d"]} for x in r[:30]]

        r = list(s.run('MATCH (c:Claim {tenant_id: "default"}) WHERE c.text CONTAINS " and " AND c.text CONTAINS "," AND size(c.text) > 80 RETURN c.text AS t, c.doc_id AS d LIMIT 60'))
        random.shuffle(r)
        claims["list"] = [{"text": x["t"], "doc": x["d"]} for x in r[:25]]

        r = list(s.run('MATCH (c:Claim {tenant_id: "default"})-[:ABOUT]->(e) WITH e, collect(DISTINCT c.doc_id) AS docs, collect(c.text)[..3] AS samples WHERE size(docs) >= 3 RETURN e.name AS entity, docs, samples ORDER BY size(docs) DESC LIMIT 25'))
        claims["multi_doc"] = [{"entity": x["entity"], "docs": x["docs"], "samples": [s[:150] for s in x["samples"]]} for x in r]

    driver.close()
    return claims


def gen_unanswerable(count=17):
    logger.info(f"Generating {count} unanswerable...")
    prompt = f"""Generate {count} questions in French about SAP S/4HANA that CANNOT be answered from technical documentation.
Topics NOT in technical docs: pricing, market statistics, competitor comparisons, salaries, timelines, third-party integrations (Salesforce, ServiceNow), legal advice, customer success stories, training programs, certification costs, partner programs, hardware sizing, SLA guarantees, support response times, end-of-life dates, migration tools pricing.

Format as JSON array: [{{"question": "...", "reason": "..."}}]
ONLY output the JSON."""

    data = parse_json(ask_qwen(prompt))
    questions = []
    for i, q in enumerate(data[:count]):
        questions.append({
            "question_id": f"T6_UN_{9+i:03d}",
            "category": "unanswerable",
            "question": q["question"],
            "ground_truth": {
                "expected_behavior": "admit_ignorance",
                "reason": q.get("reason", ""),
                "expected_keywords": ["pas d'information", "ne dispose pas", "non disponible", "aucune donnee"]
            },
            "grading_rules": {"must_admit_no_info": True, "must_not_hallucinate": True}
        })
    logger.info(f"  Got {len(questions)}")
    return questions


def gen_from_claims(category, claims_list, count, gen_prompt_fn, make_question_fn):
    logger.info(f"Generating {count} {category}...")
    questions = []
    for i, claim in enumerate(claims_list[:count]):
        text = claim["text"][:200]
        prompt = gen_prompt_fn(text)
        try:
            data = parse_json(ask_qwen(prompt, max_tokens=500))
            q = make_question_fn(i, data, claim)
            if q:
                questions.append(q)
        except Exception as e:
            logger.debug(f"  Skip {i}: {e}")
    logger.info(f"  Got {len(questions)}")
    return questions


def gen_temporal(count=17):
    logger.info(f"Generating {count} temporal...")
    pairs = [
        ("Security Guide 2022 vs 2023", "028_SAP_S4HANA_2022_Security", "027_SAP_S4HANA_2023_Security"),
        ("Operations Guide 2021 vs 2023", "014_SAP_S4HANA_2021_Operations", "017_SAP_S4HANA_2023_Operations"),
        ("Installation Guide 2021 vs 2023", "012_SAP_S4HANA_2021_Installation", "011_SAP_S4HANA_2023_Installation"),
        ("Business Scope FPS03 vs 2025", "022_Business-Scope-FPS03", "023_Business-Scope-2025"),
    ]
    questions = []
    for pair_name, doc_a, doc_b in pairs:
        prompt = f"""Generate 5 questions in French about how SAP documentation has EVOLVED between versions.
Context: comparing {pair_name}.
Each question asks if/how something changed between versions.
Format as JSON array: [{{"question": "..."}}]
ONLY output JSON."""
        try:
            items = parse_json(ask_qwen(prompt))
            for j, item in enumerate(items[:5]):
                questions.append({
                    "question_id": f"T6_TE_{9+len(questions):03d}",
                    "category": "temporal_evolution",
                    "question": item["question"],
                    "ground_truth": {
                        "expected_behavior": "compare_versions",
                        "docs": [doc_a, doc_b]
                    },
                    "grading_rules": {"must_mention_both_versions": True, "must_identify_change": True}
                })
        except Exception as e:
            logger.debug(f"  Skip pair {pair_name}: {e}")
    logger.info(f"  Got {len(questions)}")
    return questions[:count]


def gen_synthesis(entities, count=20):
    logger.info(f"Generating {count} synthesis...")
    questions = []
    for i, ent in enumerate(entities[:count]):
        entity = ent["entity"]
        samples = ent["samples"]
        prompt = f"""The entity "{entity}" appears in {len(ent["docs"])} SAP documents. Sample claims:
{chr(10).join("- " + s for s in samples)}

Generate a broad synthesis question in French asking for a COMPLETE overview of "{entity}".
Format: {{"question": "...", "expected_aspects": ["aspect1", "aspect2", ...]}}
ONLY output JSON."""
        try:
            data = parse_json(ask_qwen(prompt, max_tokens=500))
            questions.append({
                "question_id": f"T6_SY_{6+i:03d}",
                "category": "synthesis_large",
                "question": data["question"],
                "ground_truth": {
                    "expected_behavior": "multi_aspect_synthesis",
                    "expected_aspects": data.get("expected_aspects", []),
                    "min_docs": min(3, len(ent["docs"]))
                },
                "grading_rules": {"must_cover_multiple_aspects": True, "must_cite_multiple_docs": True, "min_aspects": 3}
            })
        except:
            pass
    logger.info(f"  Got {len(questions)}")
    return questions


def gen_multi_hop(entities, count=20):
    logger.info(f"Generating {count} multi_hop...")
    questions = []
    for i, ent in enumerate(entities[:count]):
        entity = ent["entity"]
        samples = ent["samples"]
        if len(samples) < 2:
            continue
        prompt = f"""The entity "{entity}" appears in multiple SAP documents with these claims:
{chr(10).join("- " + s for s in samples)}

Generate a multi-hop question in French requiring CHAINING facts from at least 2 claims.
Format: {{"question": "...", "chain": ["fact1", "fact2"]}}
ONLY output JSON."""
        try:
            data = parse_json(ask_qwen(prompt, max_tokens=500))
            questions.append({
                "question_id": f"T6_MH_{6+i:03d}",
                "category": "multi_hop",
                "question": data["question"],
                "ground_truth": {
                    "expected_behavior": "chain_reasoning",
                    "chain": data.get("chain", samples[:2]),
                },
                "grading_rules": {"must_chain_facts": True, "must_cite_source": True}
            })
        except:
            pass
    logger.info(f"  Got {len(questions)}")
    return questions


def main():
    logger.info("Extracting claims from Neo4j...")
    claims = extract_claims()
    logger.info(f"Claims: {', '.join(f'{k}={len(v)}' for k, v in claims.items())}")

    all_new = []

    # Unanswerable (need 17 more → 25 total)
    all_new.extend(gen_unanswerable(17))

    # False premise (need 18 more → 25 total)
    all_new.extend(gen_from_claims(
        "false_premise", claims["negation"], 18,
        lambda text: f'Given this TRUE fact: "{text}"\nGenerate a question in French with a FALSE premise (opposite of fact).\nFormat: {{"question": "...", "correct_fact": "..."}}\nONLY output JSON.',
        lambda i, data, claim: {
            "question_id": f"T6_FP_{8+i:03d}",
            "category": "false_premise",
            "question": data["question"],
            "ground_truth": {"expected_behavior": "reject_premise", "correct_fact": data.get("correct_fact", ""), "evidence_claim": claim["text"][:200]},
            "grading_rules": {"must_correct_premise": True, "must_not_confirm_false_claim": True}
        }
    ))

    # Negation (need 20 more → 25 total)
    all_new.extend(gen_from_claims(
        "negation", claims["negation"], 20,
        lambda text: f'Given this fact: "{text}"\nGenerate a question in French about what is NOT possible/supported/allowed.\nFormat: {{"question": "..."}}\nONLY output JSON.',
        lambda i, data, claim: {
            "question_id": f"T6_NE_{6+i:03d}",
            "category": "negation",
            "question": data["question"],
            "ground_truth": {"expected_behavior": "find_negation", "evidence_claim": claim["text"][:200]},
            "grading_rules": {"must_mention_negation": True, "must_cite_source": True}
        }
    ))

    # Conditional (need 20 more → 25 total)
    all_new.extend(gen_from_claims(
        "conditional", claims["conditional"], 20,
        lambda text: f'Given this fact: "{text}"\nGenerate a conditional question in French (si/quand/prerequis).\nFormat: {{"question": "..."}}\nONLY output JSON.',
        lambda i, data, claim: {
            "question_id": f"T6_CO_{6+i:03d}",
            "category": "conditional",
            "question": data["question"],
            "ground_truth": {"expected_behavior": "conditional_extraction", "evidence_claim": claim["text"][:200]},
            "grading_rules": {"must_cite_condition": True, "must_cite_source": True}
        }
    ))

    # Causal (need 20 more → 25 total)
    all_new.extend(gen_from_claims(
        "causal_why", claims["causal"], 20,
        lambda text: f'Given this fact: "{text}"\nGenerate a "Pourquoi" question in French.\nFormat: {{"question": "..."}}\nONLY output JSON.',
        lambda i, data, claim: {
            "question_id": f"T6_CA_{6+i:03d}",
            "category": "causal_why",
            "question": data["question"],
            "ground_truth": {"expected_behavior": "explain_reasoning", "evidence_claim": claim["text"][:200]},
            "grading_rules": {"must_explain_reason": True, "must_not_invent_reasons": True}
        }
    ))

    # Hypothetical (need 20 more → 25 total)
    all_new.extend(gen_from_claims(
        "hypothetical", claims["conditional"], 20,
        lambda text: f'Given this fact: "{text}"\nGenerate a "Si..." hypothetical question in French about what happens if condition is NOT met.\nFormat: {{"question": "..."}}\nONLY output JSON.',
        lambda i, data, claim: {
            "question_id": f"T6_HY_{6+i:03d}",
            "category": "hypothetical",
            "question": data["question"],
            "ground_truth": {"expected_behavior": "infer_from_docs", "evidence_claim": claim["text"][:200]},
            "grading_rules": {"must_identify_consequence": True, "must_base_on_documented_facts": True}
        }
    ))

    # Set/list (need 20 more → 25 total)
    all_new.extend(gen_from_claims(
        "set_list", claims["list"], 20,
        lambda text: f'Given this fact: "{text}"\nGenerate a question in French asking to LIST/ENUMERATE items.\nFormat: {{"question": "...", "expected_items": ["item1", "item2"]}}\nONLY output JSON.',
        lambda i, data, claim: {
            "question_id": f"T6_SE_{6+i:03d}",
            "category": "set_list",
            "question": data["question"],
            "ground_truth": {"expected_behavior": "enumerate_set", "expected_items": data.get("expected_items", []), "evidence_claim": claim["text"][:200]},
            "grading_rules": {"must_list_items": True, "min_items": 2}
        }
    ))

    # Temporal (need 17 more → 25 total)
    all_new.extend(gen_temporal(17))

    # Synthesis (need 20 more → 25 total)
    all_new.extend(gen_synthesis(claims["multi_doc"], 20))

    # Multi-hop (need 20 more → 25 total)
    all_new.extend(gen_multi_hop(claims["multi_doc"], 20))

    # Summary
    logger.info(f"\nTotal new questions: {len(all_new)}")
    cats = {}
    for q in all_new:
        cats[q["category"]] = cats.get(q["category"], 0) + 1
    for c, n in sorted(cats.items()):
        logger.info(f"  {c}: {n}")

    # Merge with existing questions
    existing_path = "benchmark/questions/task6_robustness.json"
    with open(existing_path) as f:
        existing = json.load(f)

    existing_questions = existing["questions"]
    existing_ids = {q["question_id"] for q in existing_questions}
    new_only = [q for q in all_new if q["question_id"] not in existing_ids]

    merged = existing_questions + new_only
    existing["questions"] = merged
    existing["metadata"]["count"] = len(merged)

    # Write
    with open(existing_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    logger.info(f"\nMerged: {len(existing_questions)} existing + {len(new_only)} new = {len(merged)} total")

    # Final category counts
    final_cats = {}
    for q in merged:
        final_cats[q["category"]] = final_cats.get(q["category"], 0) + 1
    for c, n in sorted(final_cats.items()):
        logger.info(f"  {c}: {n}")


if __name__ == "__main__":
    main()
