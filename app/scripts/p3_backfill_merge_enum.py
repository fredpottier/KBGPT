"""P3.7 backfill — consolide les fratries d'énumération fragmentées du KG.

Critère sûr : claims de même hash-base (claim_<HASH>_<suffix>), partageant le MÊME
verbatim_quote non vide (= même span source → le verbatim contient TOUS les items),
et dont les textes partagent un long préfixe commun (signature énumération, ≠ multi-prédicat).

Action par groupe :
  - champion (is_champion sinon 1er) : text = verbatim_quote (contient tous les items),
    re-embed (e5 'passage: ' — convention vérifiée empiriquement),
  - DETACH DELETE des fratries (info préservée dans le champion ; réversible via extraction_cache).

--apply pour exécuter (sinon dry-run).
"""
from __future__ import annotations
import re
import sys
from collections import defaultdict

from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.common.clients.embeddings import EmbeddingModelManager

SUFFIX_RE = re.compile(r"_[a-z]$")
MIN_COMMON_PREFIX_RATIO = 0.4


def base_hash(cid: str) -> str:
    return SUFFIX_RE.sub("", cid)


def common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b)); i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def is_enum_group(texts):
    t0 = texts[0]
    for t in texts[1:]:
        if t == t0:
            return False  # textes identiques = vrai doublon, pas énumération
        if common_prefix_len(t0, t) < MIN_COMMON_PREFIX_RATIO * min(len(t0), len(t)):
            return False
    return True


def main() -> None:
    apply = "--apply" in sys.argv
    driver = get_neo4j_client().driver
    rows = driver.session().run(
        "MATCH (c:Claim {tenant_id:'default'}) "
        "RETURN c.claim_id AS id, c.text AS text, c.verbatim_quote AS vq, "
        "c.unit_ids AS units, c.is_champion AS champ"
    )
    by_base = defaultdict(list)
    for r in rows:
        if r["id"]:
            by_base[base_hash(r["id"])].append(
                {"id": r["id"], "text": r["text"] or "", "vq": r["vq"] or "",
                 "units": tuple(r["units"] or []), "champ": r["champ"]}
            )

    groups = []
    for members in by_base.values():
        if len(members) < 2:
            continue
        vqs = {m["vq"] for m in members}
        if len(vqs) != 1 or not members[0]["vq"]:
            continue  # exige même verbatim non vide
        if len({m["units"] for m in members}) != 1:
            continue
        if not is_enum_group([m["text"] for m in members]):
            continue
        groups.append(members)

    n_groups = len(groups)
    n_claims = sum(len(g) for g in groups)
    print(f"Groupes à consolider : {n_groups} | claims concernés : {n_claims} "
          f"→ {n_groups} (suppression {n_claims - n_groups})")
    if not apply:
        print("DRY-RUN (ajouter --apply pour exécuter).")
        for g in groups[:3]:
            print(f"  ex base={base_hash(g[0]['id'])} n={len(g)} vq={g[0]['vq'][:80]}")
        return

    mgr = EmbeddingModelManager()
    n_merged = 0
    n_deleted = 0
    for g in groups:
        champion = next((m for m in g if m["champ"]), g[0])
        new_text = champion["vq"]
        emb = mgr.encode([f"passage: {new_text}"])[0].tolist()
        sibling_ids = [m["id"] for m in g if m["id"] != champion["id"]]
        with driver.session() as s:
            s.run(
                "MATCH (c:Claim {claim_id:$cid}) SET c.text=$t, c.embedding=$e, "
                "c.enum_backfilled=true",
                cid=champion["id"], t=new_text, e=emb,
            )
            if sibling_ids:
                s.run(
                    "MATCH (c:Claim) WHERE c.claim_id IN $ids DETACH DELETE c",
                    ids=sibling_ids,
                )
        n_merged += 1
        n_deleted += len(sibling_ids)
        if n_merged % 100 == 0:
            print(f"  ... {n_merged}/{n_groups} groupes traités", flush=True)

    print(f"FAIT : {n_merged} champions consolidés, {n_deleted} fratries supprimées.")


if __name__ == "__main__":
    main()
