"""Smoke PremiseVerifier : faux présupposés (doivent être FALSE_*) + questions
normales (doivent rester OK — anti-sur-rejet). Read-only.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from knowbase.runtime_a3.premise_verifier import PremiseVerifier

FALSE_PREMISE = [
    "Comment activer le module Embedded Reporting Studio dans S/4HANA Cloud Private Edition 2024 ?",
    "Comment fonctionne le support natif d'Oracle Database dans SAP S/4HANA ?",
    "Quelle est la procédure de migration directe depuis SAP Business One vers S/4HANA Cloud Private Edition ?",
]
NORMAL = [
    "Quel role SAP est fourni pour le team lead dans le Payroll Control Center ?",
    "Quelles options de connectivite Azure sont supportees pour RISE with SAP ?",
    "Quelle base de données est requise pour une nouvelle installation de SAP S/4HANA ?",
]

pv = PremiseVerifier()
print("=== FAUX PRÉSUPPOSÉS (attendu : FALSE_*) ===")
for q in FALSE_PREMISE:
    r = pv.verify(q)
    print(f"\n[{r.status}] {q[:70]}")
    print(f"   présupposés: {r.presuppositions}")
    print(f"   reasoning  : {r.reasoning[:160]}")
    print(f"   correction : {r.correction[:200]}")

print("\n\n=== QUESTIONS NORMALES (attendu : OK) ===")
for q in NORMAL:
    r = pv.verify(q)
    print(f"\n[{r.status}] {q[:70]}")
    print(f"   reasoning  : {r.reasoning[:160]}")
