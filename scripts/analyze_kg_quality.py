"""
Script d'analyse qualité du Knowledge Graph OSMOSE.
"""
from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from collections import defaultdict
import re

def main():
    s = get_settings()
    neo4j = Neo4jClient(uri=s.neo4j_uri, user=s.neo4j_user, password=s.neo4j_password)

    print("=" * 70)
    print("  ANALYSE QUALITE KG - PARTIE 2: DETECTION DOUBLONS")
    print("=" * 70)

    with neo4j.driver.session(database="neo4j") as session:
        # 1. Doublons exacts
        r = session.run("""
            MATCH (c:CanonicalConcept {tenant_id: "default"})
            WITH toLower(trim(c.canonical_name)) AS name_lower, collect(c.canonical_name) AS names
            WHERE size(names) > 1
            RETURN name_lower, size(names) AS count, names[0..2] AS samples
            ORDER BY count DESC
            LIMIT 15
        """)
        exact_dupes = list(r)

        print("\n1. DOUBLONS EXACTS (meme nom, case-insensitive):")
        if exact_dupes:
            total = sum(d["count"] for d in exact_dupes)
            print(f"   ALERTE: {len(exact_dupes)} groupes ({total} concepts au total)")
            for d in exact_dupes[:8]:
                print(f"   - \"{d['name_lower'][:45]}\": {d['count']}x")
        else:
            print("   OK Aucun doublon exact")

        # 2. Tous les concepts pour analyse
        r = session.run("""
            MATCH (c:CanonicalConcept {tenant_id: "default"})
            RETURN c.canonical_name AS name
        """)
        all_names = [rec["name"] for rec in r if rec["name"]]

        # Normaliser et grouper
        def normalize(name):
            n = name.lower().strip()
            n = re.sub(r"[^a-z0-9\s]", " ", n)
            n = re.sub(r"\s+", " ", n).strip()
            return n

        groups = defaultdict(list)
        for name in all_names:
            norm = normalize(name)
            if len(norm) > 3:
                groups[norm].append(name)

        quasi = [(k, v) for k, v in groups.items() if len(v) > 1]
        quasi.sort(key=lambda x: -len(x[1]))

        print("\n2. QUASI-DOUBLONS (apres normalisation ponctuation):")
        if quasi:
            print(f"   ALERTE: {len(quasi)} groupes")
            for norm, names in quasi[:8]:
                print(f"   - \"{norm[:40]}\": {len(names)}x")
        else:
            print("   OK Aucun quasi-doublon")

        # 3. Concepts courts
        r = session.run("""
            MATCH (c:CanonicalConcept {tenant_id: "default"})
            WHERE size(c.canonical_name) <= 3
            RETURN c.canonical_name AS name
        """)
        short = list(r)
        print(f"\n3. CONCEPTS TROP COURTS (<=3 chars): {len(short)}")
        if short:
            for sh in short[:5]:
                print(f"   - \"{sh['name']}\"")

        # 4. Concepts longs
        r = session.run("""
            MATCH (c:CanonicalConcept {tenant_id: "default"})
            WHERE size(c.canonical_name) > 80
            RETURN c.canonical_name AS name
        """)
        long_c = list(r)
        print(f"\n4. CONCEPTS TROP LONGS (>80 chars): {len(long_c)}")
        if long_c:
            for lc in long_c[:3]:
                print(f"   - \"{lc['name'][:55]}...\"")

        # 5. Stats longueur
        r = session.run("""
            MATCH (c:CanonicalConcept {tenant_id: "default"})
            RETURN avg(size(c.canonical_name)) AS avg_len,
                   percentileDisc(size(c.canonical_name), 0.5) AS median
        """)
        stats = r.single()
        print(f"\n5. LONGUEUR MOYENNE: {stats['avg_len']:.1f} chars (mediane: {stats['median']})")

    neo4j.close()

if __name__ == "__main__":
    main()
