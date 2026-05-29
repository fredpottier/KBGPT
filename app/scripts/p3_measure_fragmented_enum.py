"""Mesure (read-only) l'ampleur des fratries d'énumération fragmentées dans le KG.

Signature : claims partageant le même hash-base (claim_<HASH>_<suffix>) + même unit_id,
dont les textes partagent un long préfixe commun mais diffèrent (≈ 1 objet par claim).
Ce sont les claims que le merge déterministe aurait dû produire en 1 seul.
"""
from __future__ import annotations
import re
from collections import defaultdict

from knowbase.common.clients.neo4j_client import get_neo4j_client

SUFFIX_RE = re.compile(r"_[a-z]$")


def base_hash(cid: str) -> str:
    return SUFFIX_RE.sub("", cid)


def common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def main() -> None:
    driver = get_neo4j_client().driver
    query = (
        "MATCH (c:Claim {tenant_id:'default'}) "
        "RETURN c.claim_id AS id, c.text AS text, c.unit_ids AS units"
    )
    rows = driver.session().run(query)
    by_base = defaultdict(list)
    for r in rows:
        cid = r["id"]
        if not cid:
            continue
        by_base[base_hash(cid)].append((cid, r["text"] or "", (r["units"] or [None])[0]))

    frag_groups = 0
    frag_claims = 0
    examples = []
    for base, members in by_base.items():
        if len(members) < 2:
            continue
        # même unité source
        units = {m[2] for m in members}
        if len(units) != 1:
            continue
        # textes : long préfixe commun (≥ 40% du plus court) → signature énumération
        texts = [m[1] for m in members]
        ok = True
        for i in range(1, len(texts)):
            cpl = common_prefix_len(texts[0], texts[i])
            if cpl < 0.4 * min(len(texts[0]), len(texts[i])) or texts[0] == texts[i]:
                ok = False
                break
        if ok:
            frag_groups += 1
            frag_claims += len(members)
            if len(examples) < 5:
                examples.append((base, len(members), texts[0][:70]))

    print(f"Groupes de fratries d'énumération fragmentées : {frag_groups}")
    print(f"Claims concernés (à consolider) : {frag_claims}")
    print(f"→ après backfill : {frag_groups} claims (réduction de {frag_claims - frag_groups})")
    print("\nExemples :")
    for base, n, txt in examples:
        print(f"  [{base}] {n} fratries | {txt}")


if __name__ == "__main__":
    main()
