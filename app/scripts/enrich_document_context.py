"""Enrichit DocumentContext avec doc_title, doc_summary, key_topics, key_terms.

Approche domain-agnostic stricte :
- Prompt LLM neutre (pas de vocabulaire SAP-spécifique)
- Charte open-source : DeepSeek-V3.1 via Together AI (fallback DeepInfra)
- Champs valables sur tout corpus (SAP, légal, médical, aerospace, etc.)

Schéma cible (UPDATE DocumentContext) :
  doc_title           : str  (5-10 mots lisibles)
  doc_summary         : str  (1 phrase décrivant le doc)
  key_topics          : [str] (3-5 thèmes conceptuels)
  key_terms           : [str] (5-10 identifiants nommés cherchables)
  enriched_at         : datetime
  enriched_model      : str
  enriched_input_chars: int

Usage :
  docker exec knowbase-app python scripts/enrich_document_context.py [--limit N] [--tag v1] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from knowbase.runtime_v5.structure_loader import (
    list_available_doc_ids,
    load_structure,
)


# ─── LLM config (charte open-source) ─────────────────────────────────────────
TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "").strip()
DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()
MODEL = "deepseek-ai/DeepSeek-V3.1"


def _llm_endpoint_and_key():
    if TOGETHER_KEY:
        return "https://api.together.xyz/v1/chat/completions", TOGETHER_KEY, "together"
    return "https://api.deepinfra.com/v1/openai/chat/completions", DEEPINFRA_KEY, "deepinfra"


# ─── Prompt agnostique ───────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are extracting routing metadata from a document.

The document content is provided below. Your task is to produce a JSON object
that helps a downstream agent decide whether this document is relevant for a
given user question.

OUTPUT FORMAT (strict JSON, no markdown, no preamble):
{{
  "doc_title": "string — short readable title (5-10 words)",
  "doc_summary": "string — single sentence describing what this document is about",
  "key_topics": ["array of 3-5 main conceptual themes covered"],
  "key_terms": ["array of 5-10 specific named items — proper nouns, identifiers, codes, references, named concepts, or specific entities that someone would use as search keywords to find content in this document"]
}}

GUIDELINES:
- key_topics are abstract/conceptual themes (e.g. "Authentication", "Performance Monitoring", "Data Privacy")
- key_terms are concrete, specific, citeable items (e.g. proper nouns, codes, identifiers, named procedures)
- Both must come from the actual content — do not invent
- Keep entries concise (under 60 chars each)
- Do not include generic words ("information", "document", "content")
- Output ONLY the JSON object, nothing else

PRE-EXTRACTED CONCEPTS (already identified, use as hints if relevant):
{anchors_hint}

DOCUMENT CONTENT:
{content}
"""


_BOILERPLATE_TITLES = {
    "document history", "content", "contents", "disclaimer", "agenda",
    "public", "table of contents", "preface", "introduction",
    "additional information and sap notes",  # SAP-specific boilerplate, neutral check
    "copyright", "trademarks", "legal notice", "important notice",
}


def _is_boilerplate(title: str) -> bool:
    """Filtre les titres boilerplate génériques (présents dans tout doc structuré)."""
    t = (title or "").strip().lower()
    if not t:
        return True
    if len(t) < 4:
        return True
    if t in _BOILERPLATE_TITLES:
        return True
    # All-caps single word très court = bruit de header
    if title.isupper() and len(title) < 12:
        return True
    return False


def build_content_window(structure, max_chars: int = 12000) -> str:
    """Échantillonnage stratifié : prend des sections réparties dans le doc
    en filtrant le boilerplate. Évite le biais "que les premières sections".
    """
    # 1. Filtrer boilerplate + sections trop courtes
    candidates = []
    for s in structure.sections:
        title = (s.get("title") or "").strip()
        text = (s.get("text") or "").strip()
        if _is_boilerplate(title):
            continue
        if len(text) < 100 and len(title) < 8:
            continue
        candidates.append((title, text))

    if not candidates:
        return ""

    # 2. Échantillonnage stratifié : on veut N sections espacées
    # Si peu de sections (< 30), prendre tout. Sinon, prendre ~30 sections espacées.
    target_n = min(30, len(candidates))
    if len(candidates) <= target_n:
        sample = candidates
    else:
        step = len(candidates) / target_n
        sample = [candidates[int(i * step)] for i in range(target_n)]

    # 3. Concaténer en respectant max_chars (budget équitable par section)
    per_section_budget = max(max_chars // max(len(sample), 1), 300)
    pieces = []
    total = 0
    for title, text in sample:
        snippet = f"## {title}\n{text[:per_section_budget]}" if title else text[:per_section_budget]
        if total + len(snippet) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                pieces.append(snippet[:remaining])
            break
        pieces.append(snippet)
        total += len(snippet)
    return "\n\n".join(pieces)


def call_llm(prompt: str, max_retries: int = 3) -> dict:
    """Appel LLM JSON-only. Returns dict or {'error': msg}."""
    endpoint, key, provider = _llm_endpoint_and_key()
    if not key:
        return {"error": "no_llm_api_key"}

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 800,
    }
    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"].strip()
            # Strip eventual code fences
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
            try:
                parsed = json.loads(content)
                return {"result": parsed, "_provider": provider}
            except json.JSONDecodeError:
                return {"error": "non_json_response", "raw": content[:500]}
        except requests.HTTPError as e:
            last_err = f"http_{e.response.status_code}"
            if e.response.status_code < 500 and e.response.status_code != 429:
                return {"error": last_err}
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < max_retries - 1:
            time.sleep(2 ** (attempt + 1))
    return {"error": last_err or "unknown"}


# ─── Neo4j access ────────────────────────────────────────────────────────────


def get_neo4j_session():
    """Return Neo4j driver session."""
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://knowbase-neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, pwd))


def fetch_anchors_for_doc(session, doc_id: str) -> list[str]:
    """Récupère les SubjectAnchor canonical_names liés au doc via DocumentContext.subject_ids."""
    query = """
    MATCH (dc:DocumentContext {doc_id: $doc_id})
    OPTIONAL MATCH (a:SubjectAnchor)
      WHERE a.subject_id IN coalesce(dc.subject_ids, [])
    RETURN collect(a.canonical_name) AS anchors
    """
    result = session.run(query, doc_id=doc_id).single()
    return result["anchors"] if result else []


def update_document_context(session, doc_id: str, enrichment: dict, model: str, input_chars: int) -> bool:
    """UPDATE DocumentContext avec les 4 champs + audit."""
    query = """
    MATCH (dc:DocumentContext {doc_id: $doc_id})
    SET dc.doc_title = $title,
        dc.doc_summary = $summary,
        dc.key_topics = $topics,
        dc.key_terms = $terms,
        dc.enriched_at = $enriched_at,
        dc.enriched_model = $model,
        dc.enriched_input_chars = $input_chars
    RETURN dc.doc_id AS doc_id
    """
    result = session.run(
        query,
        doc_id=doc_id,
        title=enrichment.get("doc_title", "")[:200],
        summary=enrichment.get("doc_summary", "")[:500],
        topics=[str(x)[:80] for x in enrichment.get("key_topics", [])[:8]],
        terms=[str(x)[:80] for x in enrichment.get("key_terms", [])[:15]],
        enriched_at=datetime.utcnow().isoformat(),
        model=model,
        input_chars=input_chars,
    ).single()
    return result is not None


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                        help="0 = all docs, N = first N for testing")
    parser.add_argument("--max-chars", type=int, default=12000,
                        help="Max content window passed to LLM")
    parser.add_argument("--tag", default="v1")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show LLM output but skip Neo4j UPDATE")
    parser.add_argument("--only", default=None,
                        help="Run on a single doc_id (substring match)")
    args = parser.parse_args()

    docs = list_available_doc_ids()
    if args.only:
        docs = [d for d in docs if args.only in d]
    if args.limit > 0:
        docs = docs[: args.limit]

    print(f"=== enrich_document_context.py ({args.tag}) ===")
    print(f"Model: {MODEL}")
    print(f"Docs to process: {len(docs)}")
    print(f"Dry-run: {args.dry_run}")
    print()

    driver = get_neo4j_session()
    audit_log = []
    t_global = time.time()

    with driver.session() as session:
        for i, doc_id in enumerate(docs, 1):
            t_doc = time.time()
            print(f"[{i}/{len(docs)}] {doc_id[:80]}")

            structure = load_structure(doc_id)
            if not structure:
                print("  ❌ no structure loaded")
                audit_log.append({"doc_id": doc_id, "status": "no_structure"})
                continue

            content = build_content_window(structure, max_chars=args.max_chars)
            if len(content) < 200:
                print(f"  ❌ content too short ({len(content)} chars)")
                audit_log.append({"doc_id": doc_id, "status": "content_too_short",
                                  "chars": len(content)})
                continue

            anchors = fetch_anchors_for_doc(session, doc_id)
            anchors_hint = (
                ", ".join(f'"{a}"' for a in anchors if a)
                if anchors else "(none — extract from content directly)"
            )

            prompt = EXTRACTION_PROMPT.format(
                anchors_hint=anchors_hint,
                content=content,
            )

            llm_resp = call_llm(prompt)
            if "error" in llm_resp:
                print(f"  ❌ LLM error: {llm_resp.get('error')}")
                if "raw" in llm_resp:
                    print(f"     raw: {llm_resp['raw'][:200]}")
                audit_log.append({"doc_id": doc_id, "status": "llm_error",
                                  "error": llm_resp.get("error")})
                continue

            enrichment = llm_resp["result"]
            print(f"  → title: {enrichment.get('doc_title', '?')[:80]}")
            print(f"  → summary: {enrichment.get('doc_summary', '?')[:120]}")
            print(f"  → key_topics: {enrichment.get('key_topics', [])}")
            print(f"  → key_terms ({len(enrichment.get('key_terms', []))}): "
                  f"{enrichment.get('key_terms', [])[:5]}...")

            if args.dry_run:
                print("  [DRY-RUN] skipping Neo4j UPDATE")
                status = "dry_run_ok"
            else:
                updated = update_document_context(
                    session, doc_id, enrichment, MODEL, len(content),
                )
                status = "updated" if updated else "update_failed"
                print(f"  → Neo4j: {status}")

            audit_log.append({
                "doc_id": doc_id, "status": status,
                "title": enrichment.get("doc_title", ""),
                "summary": enrichment.get("doc_summary", ""),
                "key_topics": enrichment.get("key_topics", []),
                "key_terms": enrichment.get("key_terms", []),
                "anchors_hint_count": len(anchors),
                "input_chars": len(content),
                "latency_s": round(time.time() - t_doc, 1),
            })
            print()

    driver.close()

    # Save audit log
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    log_path = root / f"benchmark/runs/enrich_doc_context_{args.tag}_{ts}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps({
        "_meta": {
            "ts": ts, "tag": args.tag, "model": MODEL,
            "n_total": len(docs), "duration_s": round(time.time() - t_global, 1),
            "dry_run": args.dry_run,
        },
        "results": audit_log,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nAudit log: {log_path}")

    n_ok = sum(1 for r in audit_log if r["status"] in ("updated", "dry_run_ok"))
    print(f"\nDone: {n_ok}/{len(docs)} successful, total {time.time() - t_global:.1f}s")
    return 0 if n_ok == len(docs) else 1


if __name__ == "__main__":
    sys.exit(main())
