"""
S2.A.1.b — Traduction EN→FR des questions sous-représentées en FR.

Pour chaque type sous-représenté en FR (causal/list/false_premise/unanswerable),
sample 1000 questions EN et traduit en FR via Qwen2.5-72B sur DeepInfra.

Output : data/router/external/translated_fr.jsonl
Workers parallèles 8 (DeepInfra accepte 200 concurrent).

Usage :
  docker exec -e DEEPINFRA_API_KEY=$DEEPINFRA_API_KEY knowbase-app \
    python /app/scripts/router/translate_to_fr.py
"""
from __future__ import annotations
import json
import logging
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, "/app/src")
from knowbase.runtime_v3.llm_client import RuntimeLLMClient

OUT_PATH = Path("/app/data/router/external/translated_fr.jsonl")
INPUT_PATH = Path("/app/benchmark/questions/router_training_set_v2.json")
SEED = 42

# Types sous-représentés en FR (cible : ~1000 traductions chaque)
TARGETS_PER_TYPE = {
    "causal": 1000,
    "list": 900,
    "false_premise": 1000,
    "unanswerable": 1000,
}

TRANSLATE_PROMPT = """Translate the following English question to French. Output ONLY the French translation, no comments, no quotation marks.

ENGLISH: {question}
FRENCH:"""

llm = RuntimeLLMClient(timeout=60.0)


def translate(record: dict) -> dict | None:
    """Translate a record's question EN→FR. Returns new record or None on failure."""
    try:
        meta = llm.chat_completion_with_meta(
            messages=[
                {"role": "system", "content": "You are a precise question translator EN→FR. Translate naturally, preserving meaning, technical terms, and question structure. Never explain — output only the translation."},
                {"role": "user", "content": TRANSLATE_PROMPT.format(question=record["question"])},
            ],
            temperature=0.1, max_tokens=200, json_mode=False, timeout=45.0,
        )
        fr_text = (meta.get("content") or "").strip().strip('"').strip("'").strip()
        if not fr_text or len(fr_text) < 10 or fr_text.lower() == record["question"].lower():
            return None
        new_id = record["id"].replace("_EN_", "_FR_TR_") + "_TR"
        return {
            **record,
            "id": new_id,
            "question": fr_text,
            "language": "fr",
            "source": record.get("source", "unknown") + "_translated",
            "source_id": record.get("source_id", record.get("id")),
            "translated_from": record["question"],
        }
    except Exception as exc:
        logger.warning(f"Translation failed for {record.get('id')}: {exc}")
        return None


def main():
    rng = random.Random(SEED)
    data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    questions = data["questions"]

    # Sample EN questions per type (those not already translated)
    by_type_en = defaultdict(list)
    for q in questions:
        if q.get("language") == "en" and q["primary_type"] in TARGETS_PER_TYPE:
            by_type_en[q["primary_type"]].append(q)

    to_translate = []
    for typ, target in TARGETS_PER_TYPE.items():
        items = by_type_en.get(typ, [])
        rng.shuffle(items)
        n_take = min(target, len(items))
        to_translate.extend(items[:n_take])
        logger.info(f"{typ}: will translate {n_take}/{len(items)} EN questions")

    logger.info(f"Total to translate: {len(to_translate)}")

    # Process in parallel
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(translate, r): r for r in to_translate}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if r is not None:
                results.append(r)
            if i % 100 == 0 or i == len(futures):
                elapsed = time.time() - t0
                rate = i / elapsed
                logger.info(f"Progress {i}/{len(futures)} | {rate:.1f}/s | ok={len(results)}")

    # Persist
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info(f"Persisted {len(results)} translations → {OUT_PATH}")
    logger.info(f"Total time: {time.time() - t0:.0f}s")

    # Stats
    from collections import Counter
    print(f"\nBy type: {dict(Counter(r['primary_type'] for r in results))}")
    print(f"\nSample translations:")
    for r in results[:3]:
        print(f"  EN: {r['translated_from'][:120]}")
        print(f"  FR: {r['question'][:120]}\n")


if __name__ == "__main__":
    sys.exit(main())
