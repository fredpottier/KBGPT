"""V6-P2.2 — Batch extraction sur N docs avec async + checkpoint JSONL.

Itère sur toutes les sections (text >= MIN_CHARS) des doc_ids cibles,
appelle DeepSeek-V3.1 via Together AI avec extraction prompt V6,
écrit 1 ligne JSONL par section dans benchmark/runs/v6_extractions/{doc_id}.jsonl.

Features :
- asyncio.Semaphore(WORKERS) pour parallélisme contrôlé
- Retry exponentiel 3× sur 429/5xx
- Resume : skip sections déjà extraites (lecture du JSONL existant)
- Progress log toutes les PROGRESS_EVERY sections
- Total : usage cumulé + durée + nombre d'erreurs

Usage :
    docker exec knowbase-app python scripts/v6_batch_extract.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from knowbase.runtime_v5.structure_loader import load_structure
from knowbase.runtime_v6.schemas import SectionExtraction
from knowbase.runtime_v6.extraction.prompt import build_extraction_messages


# ─── Config ──────────────────────────────────────────────────────────────────

_ALL_DOC_IDS = [
    "014_SAP_S4HANA_2021_Operations_Guide_819d2c07",
    "027_SAP_S4HANA_2023_Security_Guide_c160af0e",
    "003_SAP_S4HANA_2023_Upgrade_Guide_299d71e9",
]
_env_docs = os.getenv("V6_BATCH_DOCS", "").strip()
DOC_IDS = [d.strip() for d in _env_docs.split(",") if d.strip()] if _env_docs else _ALL_DOC_IDS
MIN_CHARS = 100             # skip sections trop courtes (TOC, titles only)
WORKERS = 4                 # asyncio concurrency
MAX_TOKENS_OUT = 4000
HTTP_TIMEOUT_S = 180.0
RETRY_MAX = 3
RETRY_BASE_DELAY = 2.0
PROGRESS_EVERY = 10

TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "").strip()
DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()
MODEL = os.getenv("V6_EXTRACT_MODEL", "deepseek-ai/DeepSeek-V3.1")

ROOT = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "benchmark/runs/v6_extractions"


def _endpoint_key():
    if TOGETHER_KEY:
        return ("https://api.together.xyz/v1/chat/completions", TOGETHER_KEY, "together")
    return ("https://api.deepinfra.com/v1/openai/chat/completions", DEEPINFRA_KEY, "deepinfra")


# ─── LLM call async ─────────────────────────────────────────────────────────

async def call_llm_async(
    client: httpx.AsyncClient,
    messages: list[dict],
) -> dict:
    endpoint, key, provider = _endpoint_key()
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS_OUT,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    last_err = None
    for attempt in range(RETRY_MAX):
        try:
            t0 = time.time()
            resp = await client.post(endpoint, headers=headers, json=payload, timeout=HTTP_TIMEOUT_S)
            if resp.status_code in (429, 500, 502, 503, 504):
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                await asyncio.sleep(delay)
                last_err = f"http_{resp.status_code}"
                continue
            resp.raise_for_status()
            data = resp.json()
            return {
                "content": data["choices"][0]["message"]["content"],
                "usage": data.get("usage", {}),
                "latency_s": time.time() - t0,
                "provider": provider,
            }
        except httpx.HTTPError as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            await asyncio.sleep(delay)
    return {"error": last_err or "max_retries_exceeded"}


def _drop_invalid_items(parsed: dict):
    """Filtre les items avec champs critiques null (subject/predicate/object/etc.).
    Le LLM peut produire des `null` sur des champs required → mieux vaut drop
    l'item que faire échouer toute la section.
    """
    def _is_str(x):
        return isinstance(x, str) and x.strip()

    facts = parsed.get("facts") or []
    parsed["facts"] = [
        f for f in facts
        if _is_str(f.get("subject")) and _is_str(f.get("predicate")) and _is_str(f.get("object"))
    ]
    entities = parsed.get("entities") or []
    parsed["entities"] = [
        e for e in entities
        if _is_str(e.get("canonical_name")) and _is_str(e.get("entity_kind"))
    ]
    constraints = parsed.get("constraints") or []
    parsed["constraints"] = [
        c for c in constraints
        if _is_str(c.get("constraint_type")) and _is_str(c.get("statement"))
    ]
    refs = parsed.get("references") or []
    for r in refs:
        if isinstance(r.get("reference_text"), str) and len(r["reference_text"]) > 500:
            r["reference_text"] = r["reference_text"][:497] + "..."
    parsed["references"] = [
        r for r in refs
        if _is_str(r.get("reference_text")) and _is_str(r.get("target_kind"))
    ]
    procs = parsed.get("procedures") or []
    parsed["procedures"] = [
        p for p in procs
        if _is_str(p.get("name")) and _is_str(p.get("goal"))
    ]


def parse_extraction(content: str, doc_id: str, section_id: str):
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as exc:
        return {"error": f"json_decode: {exc}"}
    parsed["doc_id"] = doc_id
    parsed["section_id"] = section_id
    _drop_invalid_items(parsed)
    for key in ("entities", "facts", "procedures", "constraints", "references"):
        for item in parsed.get(key, []) or []:
            if "evidence_section_id" not in item or not item.get("evidence_section_id"):
                item["evidence_section_id"] = section_id
    try:
        return SectionExtraction(**parsed)
    except Exception as exc:
        return {"error": f"pydantic: {str(exc)[:300]}"}


# ─── Resume helper ──────────────────────────────────────────────────────────

def load_done_section_ids(output_path: Path) -> set[str]:
    if not output_path.exists():
        return set()
    done = set()
    with output_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if row.get("section_id") and not row.get("error"):
                    done.add(row["section_id"])
            except json.JSONDecodeError:
                continue
    return done


# ─── Worker ─────────────────────────────────────────────────────────────────

async def process_section(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    doc_id: str,
    section: dict,
    output_path: Path,
    write_lock: asyncio.Lock,
    stats: dict,
):
    async with semaphore:
        section_id = section["section_id"]
        section_text = section["text"]
        section_title = section["title"]
        msgs = build_extraction_messages(doc_id, section_id, section_title, section_text)
        resp = await call_llm_async(client, msgs)

        row = {
            "doc_id": doc_id,
            "section_id": section_id,
            "section_title": section_title,
            "section_chars": len(section_text),
            "ts": datetime.utcnow().isoformat(),
        }
        if "error" in resp:
            row["error"] = resp["error"]
            stats["errors"] += 1
        else:
            row["latency_s"] = resp["latency_s"]
            row["usage"] = resp["usage"]
            result = parse_extraction(resp["content"], doc_id, section_id)
            if isinstance(result, dict) and "error" in result:
                row["error"] = result["error"]
                row["raw_content_preview"] = resp["content"][:300]
                stats["errors"] += 1
            else:
                row["extraction"] = result.model_dump(mode="json")
                stats["ok"] += 1
                u = resp["usage"]
                stats["tokens_in"] += int(u.get("prompt_tokens", 0))
                stats["tokens_out"] += int(u.get("completion_tokens", 0))

        async with write_lock:
            with output_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            stats["processed"] += 1
            if stats["processed"] % PROGRESS_EVERY == 0:
                elapsed = time.time() - stats["t_start"]
                rate = stats["processed"] / elapsed if elapsed > 0 else 0
                remaining = (stats["total_to_do"] - stats["processed"]) / rate if rate > 0 else 0
                print(
                    f"  [{stats['processed']:4d}/{stats['total_to_do']}] "
                    f"ok={stats['ok']} err={stats['errors']} | "
                    f"rate={rate:.2f}/s | elapsed={elapsed:.0f}s | eta={remaining:.0f}s",
                    flush=True,
                )


# ─── Main ───────────────────────────────────────────────────────────────────

async def process_doc(client: httpx.AsyncClient, doc_id: str, semaphore: asyncio.Semaphore):
    print(f"\n{'='*72}")
    print(f"DOC: {doc_id}")
    print(f"{'='*72}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{doc_id}.jsonl"

    struct = load_structure(doc_id)
    if struct is None:
        print(f"  ERROR: doc not found")
        return

    all_sections = []
    for section_id, sec in struct.by_id.items():
        text = (sec.get("text") or "").strip()
        if len(text) < MIN_CHARS:
            continue
        all_sections.append({
            "section_id": section_id,
            "title": sec.get("title", "") or "",
            "text": text,
        })

    done = load_done_section_ids(output_path)
    to_do = [s for s in all_sections if s["section_id"] not in done]

    print(f"  Total sections : {len(all_sections)} (>= {MIN_CHARS} chars)")
    print(f"  Already done   : {len(done)}")
    print(f"  To process     : {len(to_do)}")
    print(f"  Output file    : {output_path}")

    if not to_do:
        print("  Nothing to do, skipping.")
        return

    stats = {
        "processed": 0, "ok": 0, "errors": 0,
        "tokens_in": 0, "tokens_out": 0,
        "total_to_do": len(to_do),
        "t_start": time.time(),
    }
    write_lock = asyncio.Lock()

    tasks = [
        process_section(client, semaphore, doc_id, sec, output_path, write_lock, stats)
        for sec in to_do
    ]
    await asyncio.gather(*tasks)

    elapsed = time.time() - stats["t_start"]
    print(f"\n  DONE: ok={stats['ok']} errors={stats['errors']} "
          f"elapsed={elapsed:.0f}s tokens_in={stats['tokens_in']} tokens_out={stats['tokens_out']}")


async def main():
    print(f"=== V6-P2.2 Batch extraction ===")
    print(f"Model    : {MODEL}")
    print(f"Workers  : {WORKERS}")
    print(f"Docs     : {DOC_IDS}")

    if not (TOGETHER_KEY or DEEPINFRA_KEY):
        print("ERROR: no API key found")
        return 1

    semaphore = asyncio.Semaphore(WORKERS)
    limits = httpx.Limits(max_connections=WORKERS * 2, max_keepalive_connections=WORKERS)
    async with httpx.AsyncClient(limits=limits) as client:
        for doc_id in DOC_IDS:
            await process_doc(client, doc_id, semaphore)

    print("\n=== ALL DONE ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
