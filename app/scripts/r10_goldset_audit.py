"""R10 — Audit fiabilité gold-set 50q.

Pour chaque question, vérifie si ses `exact_identifiers` (réponse attendue) sont
présents dans :
  - le KG (claims, via full-text claim_text_search)
  - les chunks sources Qdrant (knowbase_chunks_v2)

Classifie chaque question :
  - answerable_kg       : identifier ∈ claims KG → pipeline DEVRAIT répondre
  - answerable_src_only : identifier ∈ Qdrant chunks mais ∉ claims → extraction ratée (Phase 1)
  - out_of_corpus       : identifier absent partout → abstention attendue / gold hors-scope
  - no_identifier       : pas d'exact_identifier exploitable (question ouverte)

Croise avec `answerability` déclaré + `false_premise`.

Usage:
    docker exec knowbase-app sh -c 'cd /app && python -u scripts/r10_goldset_audit.py'
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

_LUCENE_SPECIAL = r'+-&|!(){}[]^"~*?:\/'


def _escape_lucene(text: str) -> str:
    return "".join("\\" + c if c in _LUCENE_SPECIAL else c for c in text)


def _extract_key_tokens(identifier: str) -> List[str]:
    """Extrait les tokens discriminants d'un exact_identifier.

    Ex: "Transaction CBGLWB (Labeling Workbench, filter by state)"
        → ["CBGLWB", "Labeling Workbench"]
    Priorise les codes (ALL_CAPS, slash-paths, alphanum) qui sont les plus
    discriminants pour vérifier la présence dans le corpus.
    """
    tokens: List[str] = []
    # Codes formels : ALL_CAPS≥3, /SAPAPO/XXX, alphanum codes
    codes = re.findall(r"/[A-Z][A-Za-z]*/\w+|[A-Z]{3,}[0-9A-Z_]*|[A-Z]\d{2,}\w*", identifier)
    tokens.extend(codes)
    return tokens


def search_kg(neo4j_client, token: str, tenant_id: str = "default") -> int:
    """Compte les claims KG contenant le token (full-text)."""
    try:
        rows = neo4j_client.execute_query(
            """
            CALL db.index.fulltext.queryNodes('claim_text_search', $q)
            YIELD node AS c, score
            WHERE c.tenant_id = $tenant_id
            RETURN count(c) AS n
            """,
            q=_escape_lucene(token), tenant_id=tenant_id,
        )
        return rows[0]["n"] if rows else 0
    except Exception:
        return -1


def search_qdrant(qdrant_client, models, token: str) -> int:
    """Compte les chunks Qdrant contenant le token (text match)."""
    try:
        results, _ = qdrant_client.scroll(
            collection_name="knowbase_chunks_v2",
            scroll_filter=models.Filter(must=[
                models.FieldCondition(key="text", match=models.MatchText(text=token))
            ]),
            limit=3,
            with_payload=False,
        )
        return len(results)
    except Exception:
        return -1


def main():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.common.clients.qdrant_client import get_qdrant_client
    from qdrant_client import models

    print("=" * 70)
    print("R10 — Audit fiabilité gold-set 50q")
    print("=" * 70)

    neo4j = get_neo4j_client()
    qdrant = get_qdrant_client()

    gs = json.load(open(ROOT / "benchmark/questions/gold_set_a38_50q.json", encoding="utf-8"))
    print(f"\n{len(gs)} questions à auditer\n")

    audit = []
    for i, q in enumerate(gs, 1):
        qid = q["id"]
        ptype = q["primary_type"]
        gt = q.get("ground_truth", {})
        identifiers = gt.get("exact_identifiers", [])
        answerability = gt.get("answerability", "?")
        false_premise = gt.get("false_premise", False)

        # Extraire les tokens clés de tous les identifiers
        all_tokens = []
        for ident in identifiers:
            all_tokens.extend(_extract_key_tokens(ident))

        if not all_tokens:
            verdict = "no_identifier"
            detail = {"identifiers": identifiers}
        else:
            # Chercher chaque token dans KG + Qdrant
            kg_hits = {}
            qd_hits = {}
            for tok in all_tokens:
                kg_hits[tok] = search_kg(neo4j, tok)
                qd_hits[tok] = search_qdrant(qdrant, models, tok)

            in_kg = any(v > 0 for v in kg_hits.values())
            in_qd = any(v > 0 for v in qd_hits.values())

            if in_kg:
                verdict = "answerable_kg"
            elif in_qd:
                verdict = "answerable_src_only"  # extraction ratée → Phase 1
            else:
                verdict = "out_of_corpus"  # abstention attendue
            detail = {"tokens": all_tokens, "kg_hits": kg_hits, "qd_hits": qd_hits}

        flag = ""
        if false_premise:
            flag = " [FALSE_PREMISE]"
        if answerability != "answerable":
            flag += f" [answerability={answerability}]"

        print(f"[{i:2d}/50] {ptype:13s} {verdict:20s}{flag} {qid}")
        if verdict in ("out_of_corpus", "answerable_src_only") and all_tokens:
            print(f"        tokens={all_tokens} kg={detail.get('kg_hits')} qd={detail.get('qd_hits')}")

        audit.append({
            "id": qid, "type": ptype, "verdict": verdict,
            "answerability": answerability, "false_premise": false_premise,
            "identifiers": identifiers, "detail": detail,
        })

    # Distribution
    print("\n" + "=" * 70)
    print("DISTRIBUTION VERDICTS")
    print("=" * 70)
    verdict_counts = Counter(a["verdict"] for a in audit)
    for v, n in verdict_counts.most_common():
        print(f"  {v:22s} : {n}")

    print("\n--- Croisement verdict × type ---")
    by_vt = Counter((a["type"], a["verdict"]) for a in audit)
    for (t, v), n in sorted(by_vt.items()):
        print(f"  {t:13s} {v:22s} : {n}")

    # Cas problématiques (out_of_corpus déclarés answerable)
    print("\n--- ALERTES : out_of_corpus mais answerability=answerable ---")
    alerts = [a for a in audit if a["verdict"] == "out_of_corpus"
              and a["answerability"] == "answerable" and not a["false_premise"]]
    for a in alerts:
        print(f"  {a['id']} ({a['type']}) — identifiers={a['identifiers']}")
    print(f"  → {len(alerts)} questions 'answerable' mais réponse hors-corpus")

    print("\n--- Cas answerable_src_only (extraction ratée, Phase 1) ---")
    src_only = [a for a in audit if a["verdict"] == "answerable_src_only"]
    for a in src_only:
        print(f"  {a['id']} ({a['type']}) — identifiers={a['identifiers']}")
    print(f"  → {len(src_only)} questions où le claim existe en source mais pas extrait")

    # Persister
    out_path = ROOT / "data/benchmark/r10_goldset_audit_20260525.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"\nRésultats persistés : {out_path}")


if __name__ == "__main__":
    main()
