#!/usr/bin/env python3
"""
Generateur de questions "humaines" — lit UNIQUEMENT les caches d'extraction SAP.

AUCUN acces au KG (Neo4j) ni a Qdrant. Simule ce qu'un humain demanderait
apres avoir lu les documents.

Pipeline:
1. Charge les full_text des 23 documents SAP depuis extraction_cache
2. Echantillonne des passages representatifs (debut, milieu, fin de chaque doc)
3. Utilise GPT-4o-mini pour generer des questions naturelles + ground truth
4. Produit des fichiers au meme format que les questions KG

Usage:
    python benchmark/questions/generate_human_questions.py --config benchmark/config.yaml --task T1 --count 100
    python benchmark/questions/generate_human_questions.py --config benchmark/config.yaml --task T2 --count 100
    python benchmark/questions/generate_human_questions.py --config benchmark/config.yaml --task T4 --count 100
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("benchmark-human-questions")

CACHE_DIR = Path("data/extraction_cache - Bkp")
SAP_DOC_PATTERN = re.compile(r"^\d{3}_")


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sap_documents() -> List[Dict[str, Any]]:
    """Charge les documents SAP depuis les caches d'extraction (SANS KG)."""
    docs = []
    for cache_file in sorted(CACHE_DIR.glob("*.v5cache.json")):
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)

        doc_id = data.get("document_id", "")
        if not SAP_DOC_PATTERN.match(doc_id):
            continue

        ext = data.get("extraction", {})
        full_text = ext.get("full_text", "")
        if not full_text or len(full_text) < 1000:
            continue

        # Extraire le doc_context si disponible
        doc_context = ext.get("doc_context", {})

        docs.append({
            "doc_id": doc_id,
            "full_text": full_text,
            "text_len": len(full_text),
            "pages": len(ext.get("page_index", [])),
            "title": doc_context.get("title", doc_id),
            "doc_type": doc_context.get("doc_type", "unknown"),
            "source_path": ext.get("source_path", ""),
        })

    logger.info(f"Loaded {len(docs)} SAP documents from cache")
    return docs


def sample_passages(doc: Dict, n_passages: int = 5, passage_len: int = 2000) -> List[Dict]:
    """Echantillonne des passages representatifs d'un document."""
    text = doc["full_text"]
    text_len = len(text)
    passages = []

    if text_len < passage_len:
        passages.append({"text": text, "position": "full", "char_offset": 0})
        return passages

    # Positions strategiques : debut, 25%, 50%, 75%, fin
    positions = [0, text_len // 4, text_len // 2, 3 * text_len // 4, text_len - passage_len]
    random.shuffle(positions)

    for i, pos in enumerate(positions[:n_passages]):
        pos = max(0, min(pos, text_len - passage_len))
        # Aligner sur le debut d'une phrase
        chunk = text[pos:pos + passage_len]
        # Trouver le premier saut de ligne ou point pour commencer proprement
        start = chunk.find("\n")
        if start > 0 and start < 200:
            chunk = chunk[start + 1:]

        passages.append({
            "text": chunk.strip(),
            "position": f"offset_{pos}",
            "char_offset": pos,
            "approx_page": int(pos / (text_len / max(doc["pages"], 1))) + 1 if doc["pages"] > 0 else 0,
        })

    return passages


def generate_t1_questions(docs: List[Dict], count: int, model: str) -> List[Dict]:
    """Genere des questions T1 (provenance) en lisant les documents."""
    from openai import OpenAI
    client = OpenAI()

    questions = []
    # Distribuer les questions entre les documents proportionnellement a leur taille
    total_chars = sum(d["text_len"] for d in docs)
    doc_quotas = {}
    for doc in docs:
        quota = max(1, int(count * doc["text_len"] / total_chars))
        doc_quotas[doc["doc_id"]] = quota

    # Ajuster pour atteindre exactement count
    allocated = sum(doc_quotas.values())
    if allocated < count:
        for doc in sorted(docs, key=lambda d: -d["text_len"]):
            if allocated >= count:
                break
            doc_quotas[doc["doc_id"]] += 1
            allocated += 1

    q_idx = 0
    for doc in docs:
        quota = doc_quotas.get(doc["doc_id"], 1)
        passages = sample_passages(doc, n_passages=min(quota + 2, 8))

        for passage in passages[:quota]:
            if q_idx >= count:
                break

            prompt = f"""Tu lis un extrait d'un document SAP Enterprise.
Genere UNE question factuelle qu'un utilisateur poserait naturellement apres avoir lu ce document.
La question doit etre specifique et verifiable dans le texte.

Document: {doc['title'][:100]}
Extrait (page ~{passage.get('approx_page', '?')}):
---
{passage['text'][:1500]}
---

Reponds en JSON strict:
{{
  "question": "la question naturelle en francais",
  "expected_claim": "le fait precis que la reponse doit contenir (extrait du texte)",
  "verbatim_quote": "citation exacte du texte source (1-2 phrases)"
}}"""

            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Tu generes des questions de benchmark pour evaluer un systeme de Q&A documentaire. Reponds UNIQUEMENT en JSON valide."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=500,
                    temperature=0.7,
                    response_format={"type": "json_object"},
                )
                result = json.loads(resp.choices[0].message.content or "{}")

                if result.get("question") and result.get("expected_claim"):
                    questions.append({
                        "question_id": f"T1_HUM_{q_idx:04d}",
                        "task": "T1_provenance",
                        "source": "human_derived",
                        "question": result["question"],
                        "ground_truth": {
                            "expected_claim": result["expected_claim"],
                            "verbatim_quote": result.get("verbatim_quote", ""),
                            "doc_id": doc["doc_id"],
                            "page_no": passage.get("approx_page", 0),
                        },
                        "grading_rules": {
                            "citation_must_include_doc": doc["doc_id"],
                            "answer_must_contain_fact": result["expected_claim"][:100],
                        },
                    })
                    q_idx += 1
                    logger.info(f"  [T1 {q_idx}/{count}] {result['question'][:60]}...")

            except Exception as e:
                logger.warning(f"  Error generating Q for {doc['doc_id']}: {e}")

            time.sleep(0.3)

        if q_idx >= count:
            break

    return questions[:count]


def generate_t2_questions(docs: List[Dict], count: int, model: str) -> List[Dict]:
    """Genere des questions T2 (contradictions) en comparant des passages entre documents."""
    from openai import OpenAI
    client = OpenAI()

    questions = []
    q_idx = 0

    # Grouper les docs par theme pour trouver des paires comparables
    theme_groups = _group_docs_by_theme(docs)

    for theme, theme_docs in theme_groups.items():
        if len(theme_docs) < 2:
            continue
        if q_idx >= count:
            break

        # Comparer chaque paire de documents du meme theme
        for i in range(len(theme_docs)):
            for j in range(i + 1, len(theme_docs)):
                if q_idx >= count:
                    break

                doc_a = theme_docs[i]
                doc_b = theme_docs[j]
                passage_a = sample_passages(doc_a, n_passages=2, passage_len=1500)[0]
                passage_b = sample_passages(doc_b, n_passages=2, passage_len=1500)[0]

                prompt = f"""Tu compares deux extraits de documents SAP differents sur le meme sujet.
Identifie si les deux textes contiennent des informations potentiellement contradictoires, divergentes,
ou complementaires sur un meme sujet.

Document A: {doc_a['title'][:80]}
---
{passage_a['text'][:1200]}
---

Document B: {doc_b['title'][:80]}
---
{passage_b['text'][:1200]}
---

Si tu trouves une tension/contradiction/divergence, genere une question qui forcerait le systeme
a exposer les deux points de vue. Si pas de contradiction, genere une question qui compare les deux versions.

Reponds en JSON strict:
{{
  "question": "la question en francais qui expose la tension",
  "claim1": {{"text": "position du document A", "doc_id": "{doc_a['doc_id']}"}},
  "claim2": {{"text": "position du document B", "doc_id": "{doc_b['doc_id']}"}},
  "tension_nature": "contradiction | evolution | nuance | scope_variation",
  "has_real_tension": true/false
}}"""

                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "Tu analyses des documents pour trouver des tensions/contradictions. Reponds UNIQUEMENT en JSON valide."},
                            {"role": "user", "content": prompt},
                        ],
                        max_tokens=600,
                        temperature=0.5,
                        response_format={"type": "json_object"},
                    )
                    result = json.loads(resp.choices[0].message.content or "{}")

                    if result.get("question") and result.get("claim1") and result.get("claim2"):
                        questions.append({
                            "question_id": f"T2_HUM_{q_idx:04d}",
                            "task": "T2_contradictions",
                            "source": "human_derived",
                            "question": result["question"],
                            "ground_truth": {
                                "claim1": result["claim1"],
                                "claim2": result["claim2"],
                                "tension_nature": result.get("tension_nature", "unknown"),
                                "has_real_tension": result.get("has_real_tension", False),
                            },
                            "grading_rules": {
                                "must_surface_both_docs": [doc_a["doc_id"], doc_b["doc_id"]],
                            },
                        })
                        q_idx += 1
                        logger.info(f"  [T2 {q_idx}/{count}] {result['question'][:60]}...")

                except Exception as e:
                    logger.warning(f"  Error comparing {doc_a['doc_id']} vs {doc_b['doc_id']}: {e}")

                time.sleep(0.3)

    return questions[:count]


def generate_t4_questions(docs: List[Dict], count: int, model: str) -> List[Dict]:
    """Genere des questions T4 (audit/completude) en lisant les documents."""
    from openai import OpenAI
    client = OpenAI()

    questions = []
    q_idx = 0

    # Pour T4, on genere des questions qui demandent un resume complet d'un sujet
    # en s'attendant a ce que le systeme couvre PLUSIEURS documents
    subjects = _extract_key_subjects(docs, model)

    for subject in subjects:
        if q_idx >= count:
            break

        # Trouver combien de docs mentionnent ce sujet
        mentioning_docs = []
        for doc in docs:
            # Recherche simple dans le texte
            if subject["name"].lower() in doc["full_text"][:50000].lower():
                mentioning_docs.append(doc["doc_id"])

        if len(mentioning_docs) < 2:
            continue

        question_text = f"Fais un resume complet de tout ce que disent les documents sur {subject['name']}. " \
                        f"Inclus les sources, les contradictions eventuelles, et les aspects couverts."

        questions.append({
            "question_id": f"T4_HUM_{q_idx:04d}",
            "task": "T4_audit",
            "source": "human_derived",
            "question": question_text,
            "ground_truth": {
                "entity": subject["name"],
                "expected_claim_count": len(mentioning_docs),
                "expected_contradiction_count": 0,
                "expected_docs": mentioning_docs[:10],
            },
            "grading_rules": {
                "must_mention_docs_count": min(len(mentioning_docs), 5),
            },
        })
        q_idx += 1
        logger.info(f"  [T4 {q_idx}/{count}] {subject['name']}")

    return questions[:count]


def _group_docs_by_theme(docs: List[Dict]) -> Dict[str, List[Dict]]:
    """Groupe les documents par theme (operations, security, conversion, etc.)."""
    groups: Dict[str, List[Dict]] = {}
    for doc in docs:
        doc_id = doc["doc_id"].lower()
        if "security" in doc_id:
            theme = "security"
        elif "conversion" in doc_id:
            theme = "conversion"
        elif "upgrade" in doc_id:
            theme = "upgrade"
        elif "operation" in doc_id:
            theme = "operations"
        elif "installation" in doc_id:
            theme = "installation"
        elif "scope" in doc_id or "feature" in doc_id:
            theme = "feature_scope"
        elif "business" in doc_id:
            theme = "business_scope"
        else:
            theme = "other"
        groups.setdefault(theme, []).append(doc)
    return groups


def _extract_key_subjects(docs: List[Dict], model: str) -> List[Dict]:
    """Extrait les sujets cles des documents pour les questions T4."""
    from openai import OpenAI
    client = OpenAI()

    # Construire un resume compact de tous les titres + premieres lignes
    doc_summaries = []
    for doc in docs:
        first_500 = doc["full_text"][:500].replace("\n", " ")
        doc_summaries.append(f"- {doc['title'][:80]}: {first_500[:200]}")

    summary_text = "\n".join(doc_summaries)

    prompt = f"""Voici la liste des 23 documents SAP Enterprise:

{summary_text}

Identifie 50 sujets/concepts/entites majeurs qui sont probablement couverts par PLUSIEURS documents.
Ces sujets seront utilises pour des questions d'audit (completude de couverture).

Reponds en JSON:
{{
  "subjects": [
    {{"name": "nom du sujet", "expected_doc_types": ["security", "operations", ...]}},
    ...
  ]
}}"""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Tu analyses un corpus documentaire SAP. Reponds UNIQUEMENT en JSON valide."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content or "{}")
        return result.get("subjects", [])
    except Exception as e:
        logger.error(f"Error extracting subjects: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Generate human-derived benchmark questions from document text")
    parser.add_argument("--config", default="benchmark/config.yaml")
    parser.add_argument("--task", choices=["T1", "T2", "T4", "all"], default="all")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    config = load_config(args.config)
    model = config["models"]["evaluation"]  # gpt-4o-mini

    # Charger les documents SAP uniquement
    docs = load_sap_documents()
    if not docs:
        logger.error("No SAP documents found in extraction cache")
        return

    tasks = ["T1", "T2", "T4"] if args.task == "all" else [args.task]

    for task in tasks:
        logger.info(f"\n{'='*60}")
        logger.info(f"Generating {args.count} human questions for {task}")
        logger.info(f"{'='*60}")

        if task == "T1":
            questions = generate_t1_questions(docs, args.count, model)
        elif task == "T2":
            questions = generate_t2_questions(docs, args.count, model)
        elif task == "T4":
            questions = generate_t4_questions(docs, args.count, model)
        else:
            continue

        # Sauvegarder
        task_filenames = {
            "T1": "task1_provenance_human.json",
            "T2": "task2_contradictions_human.json",
            "T4": "task4_audit_human.json",
        }
        output_path = Path("benchmark/questions") / task_filenames[task]

        output = {
            "metadata": {
                "task": task,
                "source": "human_derived",
                "corpus": config["corpus"]["name"],
                "count": len(questions),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "seed": args.seed,
                "config": args.config,
                "model": model,
                "note": "Questions generees en lisant les documents SAP (SANS acces au KG)",
            },
            "questions": questions,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(questions)} questions to {output_path}")


if __name__ == "__main__":
    main()
