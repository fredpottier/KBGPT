#!/usr/bin/env python3
"""
Benchmark performance système ontologies YAML vs alternatives.

Teste :
- Temps de chargement YAML (parsing)
- Temps de lookup (normalisation)
- Mémoire consommée
- Scalabilité (10, 100, 1000, 10000 entités)
"""
import time
import yaml
import json
import sqlite3
from pathlib import Path
from typing import Dict, List
import sys

# Simuler croissance ontologies
def generate_mock_ontology(num_entities: int, aliases_per_entity: int = 3) -> Dict:
    """Génère ontologie mock pour benchmark."""
    ontology = {}
    for i in range(num_entities):
        entity_id = f"ENTITY_{i:05d}"
        ontology[entity_id] = {
            "canonical_name": f"Entity Name {i}",
            "aliases": [f"Alias {i}-{j}" for j in range(aliases_per_entity)],
            "category": f"Category_{i % 10}",
            "vendor": f"Vendor_{i % 5}"
        }
    return {"TEST_TYPE": ontology}

# Benchmark 1 : YAML Loading
def benchmark_yaml_loading(num_entities: int) -> float:
    """Mesure temps chargement YAML."""
    ontology = generate_mock_ontology(num_entities)
    yaml_content = yaml.dump(ontology, default_flow_style=False)

    start = time.perf_counter()
    loaded = yaml.safe_load(yaml_content)
    duration = time.perf_counter() - start

    return duration

# Benchmark 2 : YAML Lookup (index building)
def benchmark_yaml_lookup(num_entities: int, aliases_per_entity: int = 3) -> tuple:
    """Mesure temps construction index + lookup."""
    ontology = generate_mock_ontology(num_entities, aliases_per_entity)
    yaml_content = yaml.dump(ontology, default_flow_style=False)
    loaded = yaml.safe_load(yaml_content)

    # Construire index (comme EntityNormalizer)
    start_index = time.perf_counter()
    alias_index = {}
    for entity_id, data in loaded["TEST_TYPE"].items():
        canonical = data["canonical_name"]
        aliases = data.get("aliases", [])

        alias_index[canonical.lower()] = entity_id
        for alias in aliases:
            alias_index[alias.lower()] = entity_id

    index_duration = time.perf_counter() - start_index

    # Lookup test (1000 requêtes aléatoires)
    import random
    test_keys = random.choices(list(alias_index.keys()), k=1000)

    start_lookup = time.perf_counter()
    for key in test_keys:
        _ = alias_index.get(key)
    lookup_duration = time.perf_counter() - start_lookup

    return index_duration, lookup_duration, len(alias_index)

# Benchmark 3 : SQLite Alternative
def benchmark_sqlite(num_entities: int, aliases_per_entity: int = 3) -> tuple:
    """Mesure perf SQLite pour ontologies."""
    db_path = Path("test_ontology.db")
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Schema
    cursor.execute("""
    CREATE TABLE ontology_entities (
        entity_id TEXT PRIMARY KEY,
        canonical_name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        category TEXT,
        vendor TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE ontology_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id TEXT NOT NULL,
        alias TEXT NOT NULL,
        FOREIGN KEY (entity_id) REFERENCES ontology_entities(entity_id)
    )
    """)

    cursor.execute("CREATE INDEX idx_alias_lower ON ontology_aliases(lower(alias))")

    # Insert data
    start_insert = time.perf_counter()
    for i in range(num_entities):
        entity_id = f"ENTITY_{i:05d}"
        cursor.execute(
            "INSERT INTO ontology_entities VALUES (?, ?, ?, ?, ?)",
            (entity_id, f"Entity Name {i}", "TEST_TYPE", f"Category_{i % 10}", f"Vendor_{i % 5}")
        )

        for j in range(aliases_per_entity):
            cursor.execute(
                "INSERT INTO ontology_aliases (entity_id, alias) VALUES (?, ?)",
                (entity_id, f"Alias {i}-{j}")
            )

    conn.commit()
    insert_duration = time.perf_counter() - start_insert

    # Lookup test
    import random
    test_aliases = [f"Alias {random.randint(0, num_entities-1)}-{random.randint(0, aliases_per_entity-1)}" for _ in range(1000)]

    start_lookup = time.perf_counter()
    for alias in test_aliases:
        cursor.execute(
            "SELECT entity_id FROM ontology_aliases WHERE lower(alias) = lower(?)",
            (alias,)
        )
        _ = cursor.fetchone()
    lookup_duration = time.perf_counter() - start_lookup

    conn.close()
    db_path.unlink()

    return insert_duration, lookup_duration

# Main benchmark
def run_benchmarks():
    """Exécute tous les benchmarks."""
    print("BENCHMARK SYSTEME ONTOLOGIES - SAP KB")
    print("=" * 70)

    test_sizes = [100, 500, 1000, 5000, 10000]

    for size in test_sizes:
        print(f"\nTest avec {size:,} entites (3 aliases chacune = {size*3:,} cles total)")
        print("-" * 70)

        # YAML
        yaml_load_time = benchmark_yaml_loading(size)
        index_time, lookup_time, num_keys = benchmark_yaml_lookup(size)

        print(f"YAML (Actuel):")
        print(f"   - Chargement YAML    : {yaml_load_time*1000:.2f} ms")
        print(f"   - Construction index : {index_time*1000:.2f} ms")
        print(f"   - 1000 lookups       : {lookup_time*1000:.2f} ms ({lookup_time/1000*1000000:.2f} us/lookup)")
        print(f"   - Total startup      : {(yaml_load_time + index_time)*1000:.2f} ms")
        print(f"   - Cles indexees      : {num_keys:,}")

        # SQLite
        sqlite_insert_time, sqlite_lookup_time = benchmark_sqlite(size)

        print(f"\nSQLite (Alternative):")
        print(f"   - Insertion donnees  : {sqlite_insert_time*1000:.2f} ms")
        print(f"   - 1000 lookups       : {sqlite_lookup_time*1000:.2f} ms ({sqlite_lookup_time/1000*1000000:.2f} us/lookup)")

        # Comparaison
        yaml_total = (yaml_load_time + index_time) * 1000
        sqlite_total = sqlite_insert_time * 1000

        print(f"\nComparaison:")
        print(f"   - YAML startup  : {yaml_total:.2f} ms")
        print(f"   - SQLite startup: {sqlite_total:.2f} ms")

        if yaml_total < sqlite_total:
            print(f"   -> YAML plus rapide de {(sqlite_total - yaml_total):.2f} ms ({sqlite_total/yaml_total:.1f}x)")
        else:
            print(f"   -> SQLite plus rapide de {(yaml_total - sqlite_total):.2f} ms ({yaml_total/sqlite_total:.1f}x)")

        # Lookup comparison
        if lookup_time < sqlite_lookup_time:
            print(f"   - YAML lookup {sqlite_lookup_time/lookup_time:.1f}x plus rapide que SQLite")
        else:
            print(f"   - SQLite lookup {lookup_time/sqlite_lookup_time:.1f}x plus rapide que YAML")

    print("\n" + "=" * 70)
    print("Benchmark termine")

if __name__ == "__main__":
    run_benchmarks()
