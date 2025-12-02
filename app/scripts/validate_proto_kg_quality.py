#!/usr/bin/env python3
"""
🔍 Validation Qualité Proto-KG
Analyse la cohérence et qualité des concepts extraits dans Neo4j
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from neo4j import GraphDatabase
import os
import json
from collections import Counter, defaultdict
from typing import Dict, List, Any
import statistics

# Configuration Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")


class ProtoKGValidator:
    """Validateur de qualité du Proto-KG"""

    def __init__(self):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        self.results = {}

    def close(self):
        self.driver.close()

    def run_query(self, query: str) -> List[Dict]:
        """Exécute une requête Cypher"""
        with self.driver.session() as session:
            result = session.run(query)
            return [dict(record) for record in result]

    # ========================================
    # 1. MÉTRIQUES GLOBALES
    # ========================================

    def get_global_stats(self):
        """Statistiques globales du graph"""
        print("\n" + "=" * 60)
        print("📊 STATISTIQUES GLOBALES")
        print("=" * 60)

        # Compter noeuds
        stats = {}
        result = self.run_query("""
            MATCH (n)
            RETURN labels(n)[0] as Type, count(n) as Count
            ORDER BY Count DESC
        """)

        for row in result:
            stats[row['Type']] = row['Count']
            print(f"  {row['Type']}: {row['Count']}")

        # Compter relations
        print("\n📎 Relations:")
        result = self.run_query("""
            MATCH ()-[r]->()
            RETURN type(r) as RelationType, count(r) as Count
            ORDER BY Count DESC
        """)

        for row in result:
            print(f"  {row['RelationType']}: {row['Count']}")

        self.results['global_stats'] = stats
        return stats

    # ========================================
    # 2. VALIDATION CONCEPTS
    # ========================================

    def validate_concepts(self):
        """Valide les ProtoConcepts"""
        print("\n" + "=" * 60)
        print("🔍 VALIDATION PROTOCONCEPTS")
        print("=" * 60)

        issues = []

        # Concepts sans nom
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            WHERE p.concept_name IS NULL OR p.concept_name = ""
            RETURN count(p) as count
        """)
        count = result[0]['count']
        if count > 0:
            issues.append(f"❌ {count} concepts SANS NOM (critique)")
        else:
            print(f"  ✅ Tous les concepts ont un nom")

        # Noms trop courts
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            WHERE size(p.concept_name) < 3
            RETURN count(p) as count
        """)
        count = result[0]['count']
        if count > 0:
            issues.append(f"⚠️  {count} concepts avec nom < 3 caractères")
            # Exemples
            examples = self.run_query("""
                MATCH (p:ProtoConcept)
                WHERE size(p.concept_name) < 3
                RETURN p.concept_name as name
                LIMIT 5
            """)
            for ex in examples:
                print(f"    - \"{ex['name']}\"")

        # Noms trop longs (probablement des phrases)
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            WHERE size(p.concept_name) > 100
            RETURN count(p) as count
        """)
        count = result[0]['count']
        if count > 0:
            issues.append(f"⚠️  {count} concepts avec nom > 100 caractères (possibles phrases)")
            examples = self.run_query("""
                MATCH (p:ProtoConcept)
                WHERE size(p.concept_name) > 100
                RETURN p.concept_name as name, size(p.concept_name) as len
                ORDER BY len DESC
                LIMIT 3
            """)
            for ex in examples:
                print(f"    - {ex['len']} chars: \"{ex['name'][:80]}...\"")

        # Distribution longueur
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            RETURN
              min(size(p.concept_name)) as min_len,
              max(size(p.concept_name)) as max_len,
              avg(size(p.concept_name)) as avg_len
        """)
        row = result[0]
        print(f"\n  📏 Longueur noms: min={row['min_len']}, max={row['max_len']}, avg={row['avg_len']:.1f}")

        # Concepts sans type
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            WHERE p.concept_type IS NULL OR p.concept_type = ""
            RETURN count(p) as count
        """)
        count = result[0]['count']
        if count > 0:
            issues.append(f"⚠️  {count} concepts SANS TYPE")

        # Distribution par type
        print(f"\n  📂 Distribution par type:")
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            RETURN p.concept_type as type, count(p) as count
            ORDER BY count DESC
        """)
        for row in result:
            print(f"    {row['type']}: {row['count']}")

        self.results['concept_issues'] = issues
        return issues

    # ========================================
    # 3. VALIDATION CANONICALISATION
    # ========================================

    def validate_canonicalization(self):
        """Valide la canonicalisation"""
        print("\n" + "=" * 60)
        print("🔄 VALIDATION CANONICALISATION")
        print("=" * 60)

        issues = []

        # ProtoConcepts sans forme canonique
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            WHERE NOT EXISTS((p)-[:PROMOTED_TO]->(:CanonicalConcept))
            RETURN count(p) as count
        """)
        count = result[0]['count']
        if count > 0:
            issues.append(f"⚠️  {count} ProtoConcepts SANS canonicalisation")
            print(f"  ⚠️  {count} ProtoConcepts sans forme canonique")
            # Exemples
            examples = self.run_query("""
                MATCH (p:ProtoConcept)
                WHERE NOT EXISTS((p)-[:PROMOTED_TO]->(:CanonicalConcept))
                RETURN p.concept_name as name
                LIMIT 5
            """)
            for ex in examples:
                print(f"    - \"{ex['name']}\"")
        else:
            print(f"  ✅ Tous les ProtoConcepts sont canonicalisés")

        # Canoniques avec beaucoup de variations (fusion réussie)
        print(f"\n  🎯 CanonicalConcepts avec le PLUS de variations (bonnes fusions):")
        result = self.run_query("""
            MATCH (p:ProtoConcept)-[:PROMOTED_TO]->(c:CanonicalConcept)
            WITH c, collect(p.concept_name) as variations, count(p) as var_count
            WHERE var_count > 1
            RETURN c.canonical_name as canonical, var_count, variations
            ORDER BY var_count DESC
            LIMIT 10
        """)

        for row in result:
            print(f"    \"{row['canonical']}\" ← {row['var_count']} variations:")
            for var in row['variations'][:3]:  # 3 premières
                print(f"      - {var}")
            if len(row['variations']) > 3:
                print(f"      ... et {len(row['variations']) - 3} autres")

        # Canoniques 1:1 (pas de fusion)
        result = self.run_query("""
            MATCH (p:ProtoConcept)-[:PROMOTED_TO]->(c:CanonicalConcept)
            WITH c, count(p) as var_count
            WHERE var_count = 1
            RETURN count(c) as count
        """)
        count = result[0]['count']
        total_canonical = self.results['global_stats'].get('CanonicalConcept', 0)
        if total_canonical > 0:
            pct = (count / total_canonical) * 100
            print(f"\n  📊 {count}/{total_canonical} CanonicalConcepts 1:1 ({pct:.1f}% - pas de fusion)")

        self.results['canonicalization_issues'] = issues
        return issues

    # ========================================
    # 4. VALIDATION RELATIONS
    # ========================================

    def validate_relations(self):
        """Valide les relations extraites"""
        print("\n" + "=" * 60)
        print("🔗 VALIDATION RELATIONS")
        print("=" * 60)

        # Relations LLM (hors PROMOTED_TO)
        result = self.run_query("""
            MATCH ()-[r]->()
            WHERE type(r) NOT IN ["PROMOTED_TO", "CO_OCCURRENCE"]
            RETURN type(r) as rel_type, count(r) as count
            ORDER BY count DESC
        """)

        print(f"  📎 Relations sémantiques extraites:")
        for row in result:
            print(f"    {row['rel_type']}: {row['count']}")

        # Exemples relations avec confiance
        print(f"\n  🎲 Exemples relations avec confiance:")
        result = self.run_query("""
            MATCH (p1)-[r]->(p2)
            WHERE type(r) NOT IN ["PROMOTED_TO", "CO_OCCURRENCE"]
              AND r.confidence IS NOT NULL
            RETURN
              p1.concept_name as source,
              type(r) as rel,
              p2.concept_name as target,
              r.confidence as conf
            ORDER BY r.confidence DESC
            LIMIT 5
        """)

        for row in result:
            print(f"    {row['source']} --[{row['rel']} ({row['conf']:.2f})]-> {row['target']}")

        # Relations faible confiance
        result = self.run_query("""
            MATCH (p1)-[r]->(p2)
            WHERE r.confidence IS NOT NULL AND r.confidence < 0.5
            RETURN count(r) as count
        """)
        count = result[0]['count']
        if count > 0:
            print(f"\n  ⚠️  {count} relations avec confiance < 0.5")

    # ========================================
    # 5. DÉTECTION ANOMALIES
    # ========================================

    def detect_anomalies(self):
        """Détecte les anomalies potentielles"""
        print("\n" + "=" * 60)
        print("🚨 DÉTECTION ANOMALIES")
        print("=" * 60)

        anomalies = []

        # Doublons exacts dans ProtoConcepts
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            WITH p.concept_name as name, collect(p) as concepts
            WHERE size(concepts) > 1
            RETURN name, size(concepts) as dup_count
            ORDER BY dup_count DESC
            LIMIT 10
        """)

        if result:
            print(f"  ⚠️  Doublons potentiels dans ProtoConcepts:")
            for row in result:
                print(f"    \"{row['name']}\" apparaît {row['dup_count']}× ")
                anomalies.append(f"Doublon: {row['name']} ({row['dup_count']}×)")

        # Concepts isolés (sans relations)
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            WHERE NOT EXISTS((p)-[]-())
            RETURN count(p) as count
        """)
        count = result[0]['count']
        if count > 0:
            print(f"\n  ℹ️  {count} ProtoConcepts isolés (sans relations)")
            # Normal si extraction non terminée

        # Concepts avec metadata JSON malformé
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            WHERE p.metadata_json IS NOT NULL
            RETURN p.concept_name as name, p.metadata_json as meta
            LIMIT 5
        """)

        malformed = []
        for row in result:
            try:
                json.loads(row['meta'])
            except:
                malformed.append(row['name'])

        if malformed:
            print(f"\n  ❌ {len(malformed)} concepts avec metadata_json malformé")
            anomalies.append(f"Metadata JSON malformé: {len(malformed)}")

        self.results['anomalies'] = anomalies
        return anomalies

    # ========================================
    # 6. EXEMPLES REPRÉSENTATIFS
    # ========================================

    def show_examples(self):
        """Affiche des exemples représentatifs"""
        print("\n" + "=" * 60)
        print("📋 EXEMPLES REPRÉSENTATIFS")
        print("=" * 60)

        # Top concepts les plus connectés
        print(f"\n  🌟 Top 10 concepts HUBs (plus connectés):")
        result = self.run_query("""
            MATCH (p:ProtoConcept)
            OPTIONAL MATCH (p)-[r]-()
            WITH p, count(r) as conn_count
            WHERE conn_count > 0
            RETURN p.concept_name as name, p.concept_type as type, conn_count
            ORDER BY conn_count DESC
            LIMIT 10
        """)

        for i, row in enumerate(result, 1):
            print(f"    {i}. {row['name']} ({row['type']}) - {row['conn_count']} connexions")

        # Exemples concepts bien structurés
        print(f"\n  ✨ Exemples concepts BIEN STRUCTURÉS (avec canonical + relations):")
        result = self.run_query("""
            MATCH (p:ProtoConcept)-[:PROMOTED_TO]->(c:CanonicalConcept)
            OPTIONAL MATCH (p)-[r]->(p2:ProtoConcept)
            WHERE type(r) NOT IN ["PROMOTED_TO", "CO_OCCURRENCE"]
            WITH p, c, collect({type: type(r), target: p2.concept_name}) as rels
            WHERE size(rels) > 0
            RETURN
              p.concept_name as proto,
              c.canonical_name as canonical,
              p.concept_type as type,
              rels
            LIMIT 5
        """)

        for row in result:
            print(f"\n    Proto: \"{row['proto']}\"")
            print(f"    Canonical: \"{row['canonical']}\" ({row['type']})")
            print(f"    Relations:")
            for rel in row['rels'][:3]:
                if rel['target']:
                    print(f"      → {rel['type']}: {rel['target']}")

    # ========================================
    # 7. SCORE QUALITÉ GLOBAL
    # ========================================

    def calculate_quality_score(self):
        """Calcule un score qualité global"""
        print("\n" + "=" * 60)
        print("🎯 SCORE QUALITÉ GLOBAL")
        print("=" * 60)

        result = self.run_query("""
            MATCH (p:ProtoConcept)
            OPTIONAL MATCH (p)-[:PROMOTED_TO]->()
            OPTIONAL MATCH (p)-[r]-()
            RETURN
              count(p) as total,
              sum(CASE WHEN p.concept_name IS NOT NULL AND p.concept_name <> "" THEN 1 ELSE 0 END) * 100.0 / count(p) as pct_with_name,
              sum(CASE WHEN p.concept_type IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / count(p) as pct_with_type,
              sum(CASE WHEN EXISTS((p)-[:PROMOTED_TO]->()) THEN 1 ELSE 0 END) * 100.0 / count(p) as pct_canonical
        """)

        row = result[0]
        print(f"  📊 Total concepts: {row['total']}")
        print(f"  ✅ Avec nom: {row['pct_with_name']:.1f}%")
        print(f"  ✅ Avec type: {row['pct_with_type']:.1f}%")
        print(f"  ✅ Canonicalisés: {row['pct_canonical']:.1f}%")

        # Score global (moyenne)
        scores = [row['pct_with_name'], row['pct_with_type'], row['pct_canonical']]
        global_score = sum(scores) / len(scores)

        print(f"\n  🎯 SCORE GLOBAL: {global_score:.1f}/100")

        if global_score >= 95:
            print(f"     🌟 EXCELLENT - Proto-KG de haute qualité")
        elif global_score >= 80:
            print(f"     ✅ BON - Qualité acceptable")
        elif global_score >= 60:
            print(f"     ⚠️  MOYEN - Amélioration recommandée")
        else:
            print(f"     ❌ FAIBLE - Problèmes à corriger")

        self.results['quality_score'] = global_score
        return global_score

    # ========================================
    # RAPPORT FINAL
    # ========================================

    def generate_report(self):
        """Génère un rapport de synthèse"""
        print("\n" + "=" * 60)
        print("📄 RAPPORT DE SYNTHÈSE")
        print("=" * 60)

        all_issues = []
        all_issues.extend(self.results.get('concept_issues', []))
        all_issues.extend(self.results.get('canonicalization_issues', []))
        all_issues.extend(self.results.get('anomalies', []))

        if not all_issues:
            print("\n  ✅ Aucun problème majeur détecté !")
        else:
            print(f"\n  ⚠️  {len(all_issues)} problèmes détectés:")
            for issue in all_issues:
                print(f"    - {issue}")

        print(f"\n  🎯 Score qualité: {self.results.get('quality_score', 0):.1f}/100")

        # Recommandations
        print(f"\n  💡 RECOMMANDATIONS:")
        if self.results.get('quality_score', 0) >= 90:
            print(f"    ✅ Proto-KG prêt pour exploitation")
            print(f"    💡 Tester recherche hybride (vectorielle + graph)")
        else:
            print(f"    ⚠️  Vérifier anomalies détectées")
            print(f"    💡 Rejouer extraction sur documents problématiques")

    # ========================================
    # RUN ALL
    # ========================================

    def run_all_validations(self):
        """Exécute toutes les validations"""
        try:
            self.get_global_stats()
            self.validate_concepts()
            self.validate_canonicalization()
            self.validate_relations()
            self.detect_anomalies()
            self.show_examples()
            self.calculate_quality_score()
            self.generate_report()

        except Exception as e:
            print(f"\n❌ Erreur lors de la validation: {e}")
            import traceback
            traceback.print_exc()


def main():
    """Point d'entrée"""
    print("🔍 OSMOSE - Validation Qualité Proto-KG")
    print("=" * 60)

    validator = ProtoKGValidator()

    try:
        validator.run_all_validations()
    finally:
        validator.close()

    print("\n" + "=" * 60)
    print("✅ Validation terminée !")
    print("=" * 60)


if __name__ == "__main__":
    main()
