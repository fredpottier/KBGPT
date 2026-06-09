"""redate_historical_citations.py — #455 : re-date les claims citant un texte historique.

Problème : un doc (ex AC 25-17A, publié 2009) cite des blocs d'amendement anciens
(« 14 CFR 29.853(b) effective October 26, 1984 ») → les claims du bloc héritent du
`valid_from` du DOC (2009) au lieu de la date citée (1984). L'adjudicateur de
contradictions ne peut alors pas voir qu'un statement est historique/périmé.

Fix déterministe : si le TEXTE d'un claim contient une date « effective <date> »
ANTÉRIEURE à son valid_from courant, on aligne valid_from sur la date citée et on
marque valid_from_source='cited_effective_date'. N'EXPIRE PAS le claim (valid_from
= date d'entrée en vigueur ; le runtime « as_of today » l'inclut toujours).

Usage :
    docker exec -e PYTHONIOENCODING=utf-8 knowbase-app python //app/scripts/redate_historical_citations.py --tenant aero            # dry-run
    docker exec ... python //app/scripts/redate_historical_citations.py --tenant aero --execute
"""
from __future__ import annotations
import argparse
import re
from knowbase.common.clients.neo4j_client import get_neo4j_client

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}

# « effective October 26, 1984 » / « effective Oct 26, 1984 » / « effective 1984 »
_RE_FULL = re.compile(r"effective\s+([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I)
_RE_YEAR = re.compile(r"effective\s+(?:in\s+)?(\d{4})\b", re.I)


def _cited_date(text: str):
    """Retourne (iso_date, kind) de la 1re date « effective » du texte, ou None."""
    m = _RE_FULL.search(text or "")
    if m:
        mraw = m.group(1).lower().rstrip(".")
        mon = _MONTHS.get(mraw) or next(
            (v for k, v in _MONTHS.items() if k.startswith(mraw)), None)
        if mon:
            return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}", "full"
    m = _RE_YEAR.search(text or "")
    if m:
        return f"{int(m.group(1)):04d}-01-01", "year"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--execute", action="store_true", help="Applique (sinon dry-run).")
    args = ap.parse_args()

    drv = get_neo4j_client().driver
    candidates = []
    with drv.session() as s:
        rows = list(s.run(
            "MATCH (c:Claim {tenant_id:$t}) WHERE toLower(c.text) CONTAINS 'effective' "
            "RETURN c.claim_id AS cid, c.text AS text, "
            "substring(toString(c.valid_from),0,10) AS vf", t=args.tenant))
    for r in rows:
        cited = _cited_date(r["text"])
        if not cited:
            continue
        iso, kind = cited
        cur = r["vf"]
        # ne re-date que si la date citée est STRICTEMENT antérieure au valid_from courant
        if cur and iso < cur:
            candidates.append((r["cid"], cur, iso, kind, r["text"][:75]))

    print(f"# Re-datation citations historiques (#455) — tenant {args.tenant}")
    print(f"claims avec 'effective' scannés : {len(rows)} | à re-dater : {len(candidates)}\n")
    for cid, cur, iso, kind, txt in candidates[:25]:
        print(f"  {cur} → {iso} ({kind})  {txt}")
    if len(candidates) > 25:
        print(f"  … +{len(candidates) - 25} autres")

    if args.execute and candidates:
        with drv.session() as s:
            for cid, cur, iso, kind, _ in candidates:
                s.run(
                    "MATCH (c:Claim {claim_id:$cid, tenant_id:$t}) "
                    "SET c.valid_from = date($iso), c.valid_from_source = 'cited_effective_date'",
                    cid=cid, t=args.tenant, iso=iso)
        print(f"\n✅ {len(candidates)} claims re-datés (valid_from = date citée).")
    elif candidates:
        print("\n(dry-run — relancer avec --execute pour appliquer)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
