#!/usr/bin/env python3
"""
Script de test pour le mode Pointer-Based Extraction.

Usage:
    # Dans Docker:
    docker-compose exec app python scripts/test_pointer_mode.py

    # Avec un fichier cache spécifique:
    docker-compose exec app python scripts/test_pointer_mode.py --cache data/extraction_cache/mon_doc.knowcache.json

    # Test sur un texte simple:
    docker-compose exec app python scripts/test_pointer_mode.py --demo
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def test_unit_indexer_demo():
    """Test l'indexer sur un texte de démo."""
    from knowbase.stratified.pass1.assertion_unit_indexer import (
        AssertionUnitIndexer,
        format_units_for_llm,
    )

    print("\n" + "="*70)
    print("TEST 1: AssertionUnitIndexer - Segmentation")
    print("="*70)

    # Texte de test réaliste (sécurité cloud)
    test_text = """
TLS 1.2 is required for all connections. TLS 1.0 and 1.1 are not supported.
All data must be encrypted at rest using AES-256 encryption.
Authentication requires multi-factor authentication (MFA) for all users.
Sessions timeout after 30 minutes of inactivity; users must re-authenticate.
The system supports SOC 2 Type II compliance requirements.
    """.strip()

    print(f"\n📄 Texte source ({len(test_text)} chars):")
    print("-"*50)
    print(test_text)
    print("-"*50)

    # Indexer
    indexer = AssertionUnitIndexer(min_unit_length=20, max_unit_length=300)
    result = indexer.index_docitem(
        docitem_id="demo:test:item1",
        text=test_text,
        item_type="paragraph",
    )

    print(f"\n✅ Résultat: {result.unit_count} unités créées")
    print(f"   Stats: {result.stats}")

    print("\n📋 Unités extraites:")
    for unit in result.units:
        print(f"   {unit.unit_local_id}: [{unit.unit_type}] {unit.text[:80]}...")

    # Format pour LLM
    print("\n📤 Format pour LLM:")
    print("-"*50)
    formatted = format_units_for_llm(result.units)
    print(formatted)
    print("-"*50)

    return result


def test_pointer_validator_demo(unit_result):
    """Test le validator sur les unités."""
    from knowbase.stratified.pass1.pointer_validator import (
        PointerValidator,
        ValidationStatus,
    )

    print("\n" + "="*70)
    print("TEST 2: PointerValidator - Validation 3 niveaux")
    print("="*70)

    validator = PointerValidator()

    # Simuler des concepts pointés par le LLM
    test_concepts = [
        {"label": "TLS requirement", "type": "PRESCRIPTIVE", "unit_id": "U1", "value_kind": "version"},
        {"label": "data encryption", "type": "PRESCRIPTIVE", "unit_id": "U3", "value_kind": None},
        {"label": "session timeout", "type": "PRESCRIPTIVE", "unit_id": "U5", "value_kind": "duration"},
        {"label": "fake concept", "type": "FACTUAL", "unit_id": "U99", "value_kind": None},  # Invalid
        {"label": "random stuff", "type": "PRESCRIPTIVE", "unit_id": "U1", "value_kind": None},  # No lexical support
    ]

    print(f"\n🔍 Test de {len(test_concepts)} concepts simulés:")

    for concept in test_concepts:
        unit = unit_result.get_unit_by_local_id(concept["unit_id"])
        unit_text = unit.text if unit else ""

        result = validator.validate(
            concept_label=concept["label"],
            concept_type=concept["type"],
            unit_text=unit_text,
            value_kind=concept.get("value_kind"),
        )

        status_emoji = {
            ValidationStatus.VALID: "✅",
            ValidationStatus.DOWNGRADE: "⚠️",
            ValidationStatus.ABSTAIN: "❌",
        }

        print(f"\n   {status_emoji[result.status]} {concept['label']} → {concept['unit_id']}")
        print(f"      Status: {result.status.value}")
        print(f"      Score: {result.score:.2f}")
        if result.reason:
            print(f"      Reason: {result.reason.value}")
        if result.new_type:
            print(f"      Downgraded to: {result.new_type}")


def test_with_cache_file(cache_path: str):
    """Test le mode pointer sur un fichier cache existant."""
    from knowbase.stratified.pass1.assertion_unit_indexer import (
        AssertionUnitIndexer,
        format_units_for_llm,
    )
    from knowbase.stratified.pass1.pointer_validator import PointerValidator

    print("\n" + "="*70)
    print(f"TEST: Mode Pointer sur cache existant")
    print(f"      {cache_path}")
    print("="*70)

    # Charger le cache
    cache_file = Path(cache_path)
    if not cache_file.exists():
        print(f"❌ Fichier non trouvé: {cache_path}")
        return

    with open(cache_file, 'r', encoding='utf-8') as f:
        cache_data = json.load(f)

    doc_title = cache_data.get('metadata', {}).get('title', 'Unknown')
    print(f"\n📄 Document: {doc_title}")

    # Récupérer les DocItems depuis le cache
    docitems_data = cache_data.get('docitems', {})
    if not docitems_data:
        # Essayer avec 'items' ou 'doc_items'
        docitems_data = cache_data.get('items', cache_data.get('doc_items', {}))

    if not docitems_data:
        print("❌ Pas de DocItems dans le cache")
        print(f"   Clés disponibles: {list(cache_data.keys())}")
        return

    print(f"   {len(docitems_data)} DocItems trouvés")

    # Indexer les unités
    indexer = AssertionUnitIndexer(min_unit_length=30, max_unit_length=500)
    total_units = 0
    sample_units = []

    for docitem_id, docitem in list(docitems_data.items())[:20]:  # Limiter à 20 pour le test
        text = ""
        if isinstance(docitem, dict):
            text = docitem.get('text', '') or docitem.get('content', '')
        elif isinstance(docitem, str):
            text = docitem

        if not text or len(text) < 30:
            continue

        result = indexer.index_docitem(
            docitem_id=docitem_id,
            text=text,
            item_type="paragraph",
        )

        total_units += result.unit_count
        if result.units and len(sample_units) < 10:
            sample_units.extend(result.units[:2])

    print(f"\n✅ Indexation: {total_units} unités créées")

    if sample_units:
        print("\n📋 Échantillon d'unités (10 premières):")
        for unit in sample_units[:10]:
            text_preview = unit.text[:60] + "..." if len(unit.text) > 60 else unit.text
            print(f"   {unit.unit_local_id}: {text_preview}")

        print("\n📤 Format LLM (échantillon):")
        print("-"*50)
        print(format_units_for_llm(sample_units[:5]))
        print("-"*50)


def find_cache_files():
    """Trouve les fichiers cache disponibles."""
    cache_dir = Path("data/extraction_cache")
    if not cache_dir.exists():
        return []

    return list(cache_dir.glob("*.knowcache.json"))


def main():
    parser = argparse.ArgumentParser(description="Test du mode Pointer-Based Extraction")
    parser.add_argument("--cache", type=str, help="Chemin vers un fichier .knowcache.json")
    parser.add_argument("--demo", action="store_true", help="Exécuter la démo avec texte de test")
    parser.add_argument("--list", action="store_true", help="Lister les fichiers cache disponibles")

    args = parser.parse_args()

    if args.list:
        cache_files = find_cache_files()
        if cache_files:
            print(f"\n📁 Fichiers cache disponibles ({len(cache_files)}):")
            for f in cache_files[:20]:
                size = f.stat().st_size / 1024
                print(f"   - {f.name} ({size:.1f} KB)")
            if len(cache_files) > 20:
                print(f"   ... et {len(cache_files) - 20} autres")
        else:
            print("❌ Aucun fichier cache trouvé dans data/extraction_cache/")
        return

    if args.cache:
        test_with_cache_file(args.cache)
        return

    if args.demo or not args.cache:
        # Test avec données de démo
        unit_result = test_unit_indexer_demo()
        test_pointer_validator_demo(unit_result)

        print("\n" + "="*70)
        print("RÉSUMÉ")
        print("="*70)
        print("""
Le mode Pointer-Based fonctionne ainsi:

1. SEGMENTATION (AssertionUnitIndexer)
   - Découpe les DocItems en unités numérotées (U1, U2, ...)
   - Gère abréviations, versions, clauses

2. PROMPT LLM
   - Envoie: "U1: texte1\\nU2: texte2\\n..."
   - Reçoit: {"concepts": [{"label": "X", "unit_id": "U1"}]}
   - Le LLM POINTE au lieu de COPIER → anti-reformulation

3. VALIDATION (PointerValidator)
   - Niveau 1: Score lexical ≥ 1.5
   - Niveau 2: Type markers (PRESCRIPTIVE → must/shall)
   - Niveau 3: Value patterns (version, %, size)

4. RECONSTRUCTION
   - exact_quote = units[unit_id].text  ← GARANTI VERBATIM

Pour tester sur vos données:
  python scripts/test_pointer_mode.py --list
  python scripts/test_pointer_mode.py --cache data/extraction_cache/VOTRE_DOC.knowcache.json
""")


if __name__ == "__main__":
    main()
