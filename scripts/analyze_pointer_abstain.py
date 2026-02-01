#!/usr/bin/env python3
"""
Script diagnostic: Analyse des ABSTAIN en mode Pointer-Based.

Objectif: Comprendre pourquoi 83% des concepts sont rejetés.

Usage:
    docker-compose exec app python scripts/analyze_pointer_abstain.py
"""

import json
import re
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class DiagnosticResult:
    label: str
    concept_type: str
    unit_id: str
    docitem_id: str
    unit_text: str
    value_kind: Optional[str]
    lexical_score: float
    abstain_reason: str
    details: str


def compute_lexical_score(label: str, text: str, value_kind: Optional[str] = None) -> Tuple[float, List[str]]:
    """Calcule le score lexical et retourne les tokens matchés."""
    score = 0.0
    text_lower = text.lower()
    tokens_scored = 0
    matched_tokens = []

    for token in label.lower().split():
        if len(token) < 3:  # Ignorer tokens courts
            continue
        if tokens_scored >= 2:  # Max 2 tokens
            break

        pattern = rf'\b{re.escape(token)}\b'
        if re.search(pattern, text_lower):
            score += 1.0
            tokens_scored += 1
            matched_tokens.append(token)

    # Score sur motif valeur
    if value_kind:
        patterns = {
            "version": r"\d+(\.\d+)+",
            "percentage": r"\d+\s*%",
            "size": r"\d+\s*(GB|TB|MB|TiB|GiB|KB|KiB)",
            "number": r"\d+",
            "duration": r"\d+\s*(ms|s|sec|min|hour|h|day|d|week|month|year)",
        }
        pattern = patterns.get(value_kind.lower())
        if pattern and re.search(pattern, text, re.IGNORECASE):
            score += 1.0
            matched_tokens.append(f"[{value_kind}]")
    else:
        # Pattern générique
        if re.search(r'\d+(\.\d+)*\s*(%|GB|TB|MB|GiB|TiB|ms|s|min|h)?', text):
            score += 1.0
            matched_tokens.append("[value]")

    return score, matched_tokens


def load_cache_and_analyze(cache_path: str, max_examples: int = 50):
    """Charge le cache et simule l'analyse pointer."""

    cache_file = Path(cache_path)
    if not cache_file.exists():
        print(f"❌ Cache non trouvé: {cache_path}")
        return

    with open(cache_file, 'r', encoding='utf-8') as f:
        cache_data = json.load(f)

    # Récupérer les DocItems
    docitems_data = cache_data.get('docitems', cache_data.get('items', {}))
    print(f"\n📄 Document: {cache_data.get('metadata', {}).get('title', 'Unknown')}")
    print(f"   {len(docitems_data)} DocItems dans le cache")

    # Simuler l'indexation des unités
    from knowbase.stratified.pass1.assertion_unit_indexer import AssertionUnitIndexer

    indexer = AssertionUnitIndexer()
    unit_index = {}

    for docitem_id, docitem in list(docitems_data.items())[:500]:  # Limiter
        text = ""
        if isinstance(docitem, dict):
            text = docitem.get('text', '') or docitem.get('content', '')
        elif isinstance(docitem, str):
            text = docitem

        if text and len(text.strip()) >= 30:
            result = indexer.index_docitem(docitem_id, text, "paragraph")
            if result.units:
                unit_index[docitem_id] = result

    print(f"   {len(unit_index)} DocItems indexés")

    # Analyser un échantillon d'unités
    print("\n" + "="*80)
    print("ANALYSE DES UNITÉS ET SCORING LEXICAL")
    print("="*80)

    examples = []

    for docitem_id, unit_result in list(unit_index.items())[:30]:
        for unit in unit_result.units[:2]:  # 2 premières unités par DocItem
            # Simuler des concepts typiques que le LLM pourrait générer
            test_concepts = generate_test_concepts(unit.text)

            for concept in test_concepts:
                score, matched = compute_lexical_score(
                    concept['label'],
                    unit.text,
                    concept.get('value_kind')
                )

                examples.append({
                    'unit_text': unit.text[:100] + "..." if len(unit.text) > 100 else unit.text,
                    'concept_label': concept['label'],
                    'value_kind': concept.get('value_kind'),
                    'score': score,
                    'matched': matched,
                    'would_pass': score >= 1.5,
                })

    # Afficher les résultats
    passing = [e for e in examples if e['would_pass']]
    failing = [e for e in examples if not e['would_pass']]

    print(f"\n📊 Résultats simulation:")
    print(f"   Total: {len(examples)}")
    print(f"   ✅ VALID (score >= 1.5): {len(passing)} ({len(passing)/len(examples)*100:.1f}%)")
    print(f"   ❌ ABSTAIN (score < 1.5): {len(failing)} ({len(failing)/len(examples)*100:.1f}%)")

    print("\n" + "-"*80)
    print("EXEMPLES QUI PASSERAIENT (score >= 1.5)")
    print("-"*80)
    for ex in passing[:10]:
        print(f"\n  Label: '{ex['concept_label']}'")
        print(f"  Score: {ex['score']:.1f} | Matched: {ex['matched']}")
        print(f"  Unit: {ex['unit_text']}")

    print("\n" + "-"*80)
    print("EXEMPLES QUI ÉCHOUERAIENT (score < 1.5)")
    print("-"*80)
    for ex in failing[:15]:
        print(f"\n  Label: '{ex['concept_label']}'")
        print(f"  Score: {ex['score']:.1f} | Matched: {ex['matched']}")
        print(f"  value_kind: {ex['value_kind']}")
        print(f"  Unit: {ex['unit_text']}")


def generate_test_concepts(unit_text: str) -> List[Dict]:
    """
    Génère des concepts de test typiques que le LLM pourrait proposer.

    Simule à la fois:
    - Des concepts bien ancrés (extraits du texte)
    - Des concepts abstraits (hallucinations typiques)
    """
    concepts = []
    text_lower = unit_text.lower()

    # 1. Concepts "abstraits" typiques (problématiques)
    abstract_concepts = [
        {"label": "security requirement", "type": "PRESCRIPTIVE", "value_kind": None},
        {"label": "data protection", "type": "PRESCRIPTIVE", "value_kind": None},
        {"label": "compliance standard", "type": "DEFINITIONAL", "value_kind": None},
        {"label": "system configuration", "type": "FACTUAL", "value_kind": None},
    ]

    # 2. Concepts avec value_kind (souvent mal assignés)
    if re.search(r'\d+', unit_text):
        concepts.append({
            "label": "numeric threshold",
            "type": "PRESCRIPTIVE",
            "value_kind": "percentage"  # Souvent faux
        })

    # 3. Concepts basés sur le texte réel
    words = [w for w in text_lower.split() if len(w) > 4][:5]
    if words:
        concepts.append({
            "label": f"{words[0]} configuration" if words else "unknown",
            "type": "FACTUAL",
            "value_kind": None
        })

    # 4. Ajouter les concepts abstraits
    concepts.extend(abstract_concepts[:2])

    return concepts


def analyze_real_concepts_from_logs():
    """
    Analyse les vrais concepts extraits par le LLM depuis les logs Docker.
    """
    import subprocess

    print("\n" + "="*80)
    print("ANALYSE DES VRAIS CONCEPTS EXTRAITS (depuis logs)")
    print("="*80)

    # Récupérer les logs de downgrade (on a le label et le texte)
    result = subprocess.run(
        ["docker", "logs", "knowbase-app"],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )

    logs = result.stdout + result.stderr

    # Parser les logs de downgrade
    downgrade_pattern = r"Downgrade PRESCRIPTIVE → DEFINITIONAL: '([^']+)' \(no markers in '([^']+)\.\.\.'\)"
    downgrades = re.findall(downgrade_pattern, logs)

    print(f"\n📉 DOWNGRADES (PRESCRIPTIVE sans marqueurs): {len(downgrades)}")
    print("-"*60)

    for label, text_preview in downgrades[:20]:
        print(f"\n  Label: '{label}'")
        print(f"  Text: '{text_preview}...'")

        # Chercher les marqueurs prescriptifs
        markers = ["must", "shall", "required", "mandatory", "need to", "have to"]
        found = [m for m in markers if m in text_preview.lower()]
        print(f"  Markers found: {found if found else 'NONE'}")

    # Analyser la distribution des labels
    print("\n" + "="*80)
    print("DISTRIBUTION DES PATTERNS DE LABELS")
    print("="*80)

    label_patterns = defaultdict(int)
    for label, _ in downgrades:
        # Catégoriser le label
        if "requirement" in label.lower():
            label_patterns["*requirement"] += 1
        elif "compliance" in label.lower():
            label_patterns["*compliance"] += 1
        elif "security" in label.lower():
            label_patterns["*security"] += 1
        elif "data" in label.lower():
            label_patterns["*data"] += 1
        elif "audit" in label.lower():
            label_patterns["*audit"] += 1
        else:
            label_patterns["other"] += 1

    print("\n  Pattern distribution:")
    for pattern, count in sorted(label_patterns.items(), key=lambda x: -x[1]):
        print(f"    {pattern}: {count}")


def main():
    print("="*80)
    print("🔍 DIAGNOSTIC POINTER-BASED ABSTAIN")
    print("="*80)

    # 1. Analyser depuis les logs réels
    analyze_real_concepts_from_logs()

    # 2. Analyser avec le cache si disponible
    cache_dir = Path("data/extraction_cache")
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("*RISE*.knowcache.json"))
        if cache_files:
            print("\n\n" + "="*80)
            print("SIMULATION AVEC CACHE EXISTANT")
            print("="*80)
            load_cache_and_analyze(str(cache_files[0]))
        else:
            print("\n⚠️ Pas de cache RISE trouvé pour simulation")

    # 3. Recommandations
    print("\n\n" + "="*80)
    print("📋 ANALYSE ET RECOMMANDATIONS")
    print("="*80)

    print("""
PROBLÈMES IDENTIFIÉS:

1. **value_mismatch = 372 (55%)**
   - Le LLM assigne souvent un value_kind (version, percentage, size)
   - MAIS le pattern correspondant n'existe pas dans l'unité
   - CAUSE: Le prompt permet au LLM de spéculer sur le value_kind
   - FIX: Ne pas demander value_kind au LLM, le détecter côté code

2. **no_lexical = 302 (45%)**
   - Les labels proposés ne matchent pas le texte de l'unité
   - CAUSE: Le LLM génère des labels "abstraits" (security requirement, data protection)
   - FIX: Demander au LLM d'utiliser les mots EXACTS de l'unité dans le label

3. **Validation peut-être trop stricte**
   - Seuil 1.5 = besoin de 2 tokens OU 1 token + valeur
   - Pour des unités courtes, c'est difficile à atteindre

SOLUTIONS PROPOSÉES:

A. PROMPT FIX (Priorité 1):
   - Instruction: "Le label DOIT contenir au moins 2 mots présents dans l'unité"
   - Supprimer la demande de value_kind au LLM

B. VALIDATION FIX (Priorité 2):
   - Détecter value_kind côté code (pas confiance au LLM)
   - Ajuster le seuil selon la longueur de l'unité

C. POST-PROCESS FIX (Priorité 3):
   - Si ABSTAIN no_lexical: essayer de régénérer le label depuis l'unité
""")


if __name__ == "__main__":
    main()
