"""Probe : structure des sous-buts d'une question multi_hop (sujet partagé ? aspects ? tool ?)."""
import sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from knowbase.runtime_a3.parse import parse
from knowbase.runtime_a3.schemas import ParseInput

QS = [
    "Que disent les documents sur la connectivite reseau et les options VPN/Express Route pour SAP Cloud Private Edition ?",
    "Que disent les documents sur le MRP dans SAP S/4HANA, incluant les transactions, rapports et BAdIs ?",
]
for q in QS:
    po = parse(ParseInput(question=q, tenant_id="default", as_of_date=datetime.now(timezone.utc)))
    print("\n=== ", q[:70])
    print("n_sub_goals =", len(po.sub_goals))
    for i, sg in enumerate(po.sub_goals):
        print(f"  [{i}] kind={sg.kind} | subj={sg.subject_canonical!r} | pred={sg.predicate_hint!r} | obj={getattr(sg, 'object_hint', None)!r}")
