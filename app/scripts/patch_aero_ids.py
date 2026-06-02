"""Re-extrait les exact_identifiers des gold-sets aéro avec la regex corrigée
(séparateurs de milliers + unités composées), SANS re-formuler les questions.
Extrait depuis question + réponse de référence (= ce qu'une bonne réponse doit contenir).
"""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_gold_set_aero import extract_ids, OUT_DIR

for name in ("gold_set_aero_150q.json", "gold_set_aero_50q.json"):
    p = OUT_DIR / name
    qs = json.loads(p.read_text(encoding="utf-8"))
    changed = 0
    for q in qs:
        gt = q["ground_truth"]
        src = f"{q['question']} {gt.get('answer', '')}"
        new_ids = extract_ids(src)
        if new_ids != gt.get("exact_identifiers"):
            gt["exact_identifiers"] = new_ids
            changed += 1
    p.write_text(json.dumps(qs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{name}: {len(qs)} questions, {changed} ids re-extraits")
