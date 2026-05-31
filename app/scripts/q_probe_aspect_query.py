"""Probe : la requête emphasée sur l'aspect remonte-t-elle les claims d'aspect ?
Compare, via le full-text Neo4j (claim_text_search), la question entière vs la requête
aspect-emphasée pour l'aspect 'VPN' de HUM_0018.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from knowbase.common.clients.neo4j_client import get_neo4j_client

n4 = get_neo4j_client()
QUERIES = {
    "QUESTION ENTIERE": "connectivite reseau options VPN Express Route SAP Cloud Private Edition",
    "ASPECT EMPHASE (VPN)": "options vpn options vpn SAP Cloud Private Edition",
    "ASPECT EMPHASE (Express Route)": "options express route options express route SAP Cloud Private Edition",
}
for label, q in QUERIES.items():
    # échappe les termes pour Lucene (simple : OR des tokens)
    rows = n4.execute_query(
        "CALL db.index.fulltext.queryNodes('claim_text_search', $q) YIELD node, score "
        "RETURN node.text AS txt, score ORDER BY score DESC LIMIT 6",
        q=q,
    )
    print(f"\n### {label}")
    for r in rows:
        txt = (r.get("txt") or "")[:120].replace("\n", " ")
        has_vpn = "vpn" in txt.lower() or "express route" in txt.lower()
        mark = "★VPN/ER" if has_vpn else "       "
        print(f"  {mark} {r.get('score'):.2f} | {txt}")
