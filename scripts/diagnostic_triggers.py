"""
DIAGNOSTIC: Bonus Lexical Activation Rate
==========================================
Mesure M1 / M2 / M3 pour déterminer H1 vs H2 vs H3.

M1: Taux d'activation du bonus lexical (triggers matchent-ils les assertions ?)
M2: Distribution de longueur des triggers (mono-mot vs n-gram)
M3: Rareté réelle (doc-global vs assertion-local)

Usage: python scripts/diagnostic_triggers.py
"""

import re
import json
from collections import defaultdict
from neo4j import GraphDatabase

import os
URI = os.environ.get("NEO4J_URI", "bolt://knowbase-neo4j:7687")
AUTH = ("neo4j", os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass"))


def get_data(driver):
    """Récupère concepts + triggers + assertions depuis Neo4j."""
    with driver.session() as session:
        # Concepts avec triggers
        concepts = session.run("""
            MATCH (c:Concept) WHERE c.tenant_id = 'default'
            RETURN c.name AS name, c.role AS role,
                   c.lexical_triggers AS triggers, c.concept_id AS id
        """).data()

        # Toutes les assertions
        assertions = session.run("""
            MATCH (a:AssertionLog) WHERE a.tenant_id = 'default'
            RETURN a.assertion_id AS id, a.text AS text
        """).data()

        # Liens existants (concept → info)
        links = session.run("""
            MATCH (c:Concept)-[:HAS_INFORMATION]->(i:Information)
            WHERE c.tenant_id = 'default'
            RETURN c.concept_id AS concept_id, c.name AS concept_name,
                   i.text AS info_text
        """).data()

    return concepts, assertions, links


def match_exact(trigger: str, text: str) -> bool:
    """Match word-boundary strict (logique actuelle du code)."""
    t = trigger.lower()
    text_lower = text.lower()
    if len(t) >= 4:
        pattern = rf'\b{re.escape(t)}\b'
    else:
        pattern = rf'(?<![a-z]){re.escape(t)}(?![a-z])'
    return bool(re.search(pattern, text_lower))


def match_normalized(trigger: str, text: str) -> bool:
    """Match normalisé: underscore/tiret → espace, case-insensitive."""
    # Normaliser le trigger
    t_norm = trigger.lower().replace('_', ' ').replace('-', ' ')
    t_norm = re.sub(r'\s+', ' ', t_norm).strip()

    # Normaliser le texte
    text_norm = text.lower().replace('_', ' ').replace('-', ' ')
    text_norm = re.sub(r'\s+', ' ', text_norm)

    # D'abord essai substring simple
    if t_norm in text_norm:
        return True

    # Puis word-boundary sur la version normalisée
    if len(t_norm) >= 4:
        pattern = rf'\b{re.escape(t_norm)}\b'
        return bool(re.search(pattern, text_norm))

    return False


def count_tokens(trigger: str) -> int:
    """Nombre de tokens dans un trigger."""
    # Traiter snake_case comme multi-token
    expanded = trigger.replace('_', ' ').replace('-', ' ')
    tokens = [t for t in expanded.split() if len(t) >= 1]
    return len(tokens)


def run_diagnostic(concepts, assertions, links):
    """Diagnostic complet M1/M2/M3."""

    all_assertion_texts = [a['text'] for a in assertions if a.get('text')]
    total_assertions = len(all_assertion_texts)

    print("=" * 80)
    print("DIAGNOSTIC BONUS LEXICAL - OSMOSE Pipeline V2")
    print(f"Date: 2026-01-28 | Assertions: {total_assertions} | Concepts: {len(concepts)}")
    print("=" * 80)

    # =========================================================================
    # M2: Distribution de longueur des triggers
    # =========================================================================
    print("\n" + "=" * 80)
    print("M2: DISTRIBUTION DE LONGUEUR DES TRIGGERS")
    print("=" * 80)

    all_triggers = []
    trigger_lengths = defaultdict(int)  # nb_tokens → count

    for c in concepts:
        triggers = c.get('triggers') or []
        for t in triggers:
            if not t:
                continue
            all_triggers.append(t)
            n_tok = count_tokens(t)
            trigger_lengths[n_tok] += 1

    total_triggers = len(all_triggers)
    print(f"\nTotal triggers: {total_triggers}")
    print(f"\nDistribution par nombre de tokens:")
    for n_tok in sorted(trigger_lengths.keys()):
        count = trigger_lengths[n_tok]
        pct = 100 * count / total_triggers if total_triggers else 0
        bar = "#" * int(pct / 2)
        print(f"  {n_tok} token(s): {count:3d} ({pct:5.1f}%) {bar}")

    # Longueur en caractères
    char_lengths = [len(t) for t in all_triggers]
    if char_lengths:
        char_lengths.sort()
        median_idx = len(char_lengths) // 2
        p90_idx = int(len(char_lengths) * 0.9)
        print(f"\nLongueur en caractères:")
        print(f"  Min: {char_lengths[0]}, Median: {char_lengths[median_idx]}, "
              f"P90: {char_lengths[p90_idx]}, Max: {char_lengths[-1]}")

    # Exemples mono-mot
    mono_word = [t for t in all_triggers if count_tokens(t) == 1]
    if mono_word:
        print(f"\nTriggers MONO-MOT ({len(mono_word)}):")
        for t in sorted(set(mono_word)):
            print(f"  - \"{t}\"")

    # =========================================================================
    # M1: Taux d'activation du bonus lexical
    # =========================================================================
    print("\n" + "=" * 80)
    print("M1: TAUX D'ACTIVATION DU BONUS LEXICAL")
    print("=" * 80)

    concept_stats = []

    for c in concepts:
        triggers = c.get('triggers') or []
        if not triggers:
            continue

        name = c['name']
        role = c.get('role', '?')

        # Pour chaque trigger, combien d'assertions matchent ?
        trigger_match_exact = {}
        trigger_match_norm = {}

        for t in triggers:
            if not t:
                continue
            exact_count = sum(1 for a in all_assertion_texts if match_exact(t, a))
            norm_count = sum(1 for a in all_assertion_texts if match_normalized(t, a))
            trigger_match_exact[t] = exact_count
            trigger_match_norm[t] = norm_count

        # Taux d'activation: % d'assertions qui matchent AU MOINS 1 trigger
        assertions_with_exact_match = sum(
            1 for a in all_assertion_texts
            if any(match_exact(t, a) for t in triggers if t)
        )
        assertions_with_norm_match = sum(
            1 for a in all_assertion_texts
            if any(match_normalized(t, a) for t in triggers if t)
        )

        exact_rate = 100 * assertions_with_exact_match / total_assertions
        norm_rate = 100 * assertions_with_norm_match / total_assertions

        concept_stats.append({
            'name': name,
            'role': role,
            'triggers': triggers,
            'exact_rate': exact_rate,
            'norm_rate': norm_rate,
            'exact_count': assertions_with_exact_match,
            'norm_count': assertions_with_norm_match,
            'trigger_detail_exact': trigger_match_exact,
            'trigger_detail_norm': trigger_match_norm,
        })

    # Trier par exact_rate
    concept_stats.sort(key=lambda x: x['exact_rate'])

    # Résumé global
    zero_exact = sum(1 for s in concept_stats if s['exact_rate'] == 0)
    low_exact = sum(1 for s in concept_stats if 0 < s['exact_rate'] <= 5)
    medium_exact = sum(1 for s in concept_stats if 5 < s['exact_rate'] <= 30)
    high_exact = sum(1 for s in concept_stats if s['exact_rate'] > 30)

    print(f"\nRésumé global (match EXACT = logique actuelle du code):")
    print(f"  0% activation:  {zero_exact} concepts (bonus JAMAIS activé)")
    print(f"  1-5%:           {low_exact} concepts (rare)")
    print(f"  5-30%:          {medium_exact} concepts (utile)")
    print(f"  >30%:           {high_exact} concepts (trop générique?)")

    # Gain avec normalisation
    gain_norm = sum(1 for s in concept_stats if s['norm_rate'] > s['exact_rate'] + 0.5)
    print(f"\n  Concepts qui GAGNENT avec normalisation: {gain_norm}")

    # Détail par concept
    print(f"\n{'Concept':<45} {'Role':<12} {'Exact%':>7} {'Norm%':>7} {'Gain':>6} Triggers")
    print("-" * 130)

    for s in concept_stats:
        gain = s['norm_rate'] - s['exact_rate']
        gain_str = f"+{gain:.1f}" if gain > 0.5 else ""
        triggers_str = str(s['triggers'][:3])
        if len(triggers_str) > 50:
            triggers_str = triggers_str[:50] + "..."
        print(f"  {s['name']:<43} {s['role']:<12} {s['exact_rate']:6.1f}% {s['norm_rate']:6.1f}% {gain_str:>5} {triggers_str}")

    # =========================================================================
    # M1 DETAIL: Top 20 concepts à 0% + exemples de match manqué
    # =========================================================================
    print("\n" + "=" * 80)
    print("M1 DETAIL: CONCEPTS A 0% ACTIVATION + EXEMPLES DE MATCH MANQUÉ")
    print("=" * 80)

    zero_concepts = [s for s in concept_stats if s['exact_rate'] == 0]
    for s in zero_concepts[:20]:
        print(f"\n  ** {s['name']} ({s['role']})")
        print(f"     Triggers: {s['triggers']}")

        # Chercher les assertions qui DEVRAIENT matcher (contiennent des mots du concept)
        concept_words = set(w.lower() for w in re.findall(r'\b\w{4,}\b', s['name']))
        if not concept_words:
            concept_words = set(w.lower() for w in s['name'].split() if len(w) >= 3)

        near_misses = []
        for a in all_assertion_texts:
            a_words = set(w.lower() for w in re.findall(r'\b\w{4,}\b', a))
            overlap = concept_words & a_words
            if overlap and len(overlap) >= 1:
                near_misses.append((a, overlap))

        if near_misses:
            print(f"     Near-misses ({len(near_misses)} assertions partagent des mots du concept):")
            for a_text, overlap in near_misses[:3]:
                truncated = a_text[:100] + "..." if len(a_text) > 100 else a_text
                print(f"       → \"{truncated}\"")
                print(f"         Mots communs: {overlap}")
        else:
            print(f"     Aucun near-miss trouvé")

    # =========================================================================
    # M3: Rareté réelle des triggers
    # =========================================================================
    print("\n" + "=" * 80)
    print("M3: RARETÉ DES TRIGGERS (dans assertions)")
    print("=" * 80)

    print(f"\n{'Trigger':<45} {'Tokens':>6} {'Exact':>6} {'Norm':>6} {'Concept'}")
    print("-" * 110)

    # Collect all trigger stats
    all_trigger_stats = []
    for s in concept_stats:
        for t in s['triggers']:
            if not t:
                continue
            exact = s['trigger_detail_exact'].get(t, 0)
            norm = s['trigger_detail_norm'].get(t, 0)
            all_trigger_stats.append({
                'trigger': t,
                'tokens': count_tokens(t),
                'exact': exact,
                'norm': norm,
                'concept': s['name'],
            })

    # Trier par exact count
    all_trigger_stats.sort(key=lambda x: x['exact'])

    for ts in all_trigger_stats:
        print(f"  {ts['trigger']:<43} {ts['tokens']:>6} {ts['exact']:>6} {ts['norm']:>6}   {ts['concept']}")

    # =========================================================================
    # DIAGNOSTIC FINAL
    # =========================================================================
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)

    # H2: Triggers mono-mot
    mono_pct = 100 * len(mono_word) / total_triggers if total_triggers else 0
    print(f"\n  H2 (Triggers mono-mot):    {len(mono_word)}/{total_triggers} = {mono_pct:.0f}%", end="")
    if mono_pct > 30:
        print(" → ** H2 CONFIRMÉ **")
    else:
        print(" → H2 faible")

    # H1: Triggers valides doc mais absents assertions
    doc_present_assertion_absent = sum(
        1 for ts in all_trigger_stats
        if ts['tokens'] >= 2 and ts['exact'] == 0
    )
    multi_triggers = sum(1 for ts in all_trigger_stats if ts['tokens'] >= 2)
    h1_pct = 100 * doc_present_assertion_absent / multi_triggers if multi_triggers else 0
    print(f"  H1 (Multi-mot, 0 match):   {doc_present_assertion_absent}/{multi_triggers} = {h1_pct:.0f}%", end="")
    if h1_pct > 50:
        print(" → ** H1 CONFIRMÉ **")
    else:
        print(" → H1 faible")

    # H3: Gain normalisation
    h3_gain = sum(1 for ts in all_trigger_stats if ts['norm'] > ts['exact'])
    h3_pct = 100 * h3_gain / total_triggers if total_triggers else 0
    print(f"  H3 (Gain normalisation):   {h3_gain}/{total_triggers} = {h3_pct:.0f}%", end="")
    if h3_pct > 20:
        print(" → ** H3 CONFIRMÉ **")
    else:
        print(" → H3 faible")

    # Taux global d'activation
    any_match = sum(1 for s in concept_stats if s['exact_rate'] > 0)
    activation_pct = 100 * any_match / len(concept_stats) if concept_stats else 0
    print(f"\n  Taux global d'activation:  {any_match}/{len(concept_stats)} concepts = {activation_pct:.0f}%")

    # =========================================================================
    # 5 EXEMPLES CONCRETS
    # =========================================================================
    print("\n" + "=" * 80)
    print("5 EXEMPLES CONCRETS (concept + triggers + assertions attendues)")
    print("=" * 80)

    # Choisir 5 concepts intéressants (liés dans Neo4j ou importants)
    examples = [
        "Business Continuity Management Systems",
        "Patch Management",
        "TLS 1.2 Encryption",
        "Customer Gateway Server",
        "Security Operations",
    ]

    for ex_name in examples:
        matching = [s for s in concept_stats if s['name'] == ex_name]
        if not matching:
            continue
        s = matching[0]

        print(f"\n  === {s['name']} ===")
        print(f"  Role: {s['role']}")
        print(f"  Triggers: {s['triggers']}")
        print(f"  Activation: exact={s['exact_rate']:.1f}%, norm={s['norm_rate']:.1f}%")

        # Détail par trigger
        for t in s['triggers']:
            if not t:
                continue
            exact = s['trigger_detail_exact'].get(t, 0)
            norm = s['trigger_detail_norm'].get(t, 0)
            n_tok = count_tokens(t)
            print(f"    Trigger \"{t}\" ({n_tok} tok): exact={exact}, norm={norm}")

        # Assertions qui matchent
        matching_assertions = [
            a for a in all_assertion_texts
            if any(match_exact(t, a) for t in s['triggers'] if t)
        ]
        if matching_assertions:
            print(f"  Assertions matchées ({len(matching_assertions)}):")
            for a in matching_assertions[:3]:
                print(f"    ✓ \"{a[:120]}\"")

        # Assertions qui DEVRAIENT matcher
        concept_words = set(w.lower() for w in re.findall(r'\b\w{4,}\b', s['name']))
        near_misses = [
            a for a in all_assertion_texts
            if not any(match_exact(t, a) for t in s['triggers'] if t)
            and len(concept_words & set(w.lower() for w in re.findall(r'\b\w{4,}\b', a))) >= 1
        ]
        if near_misses:
            print(f"  Near-misses NON captés ({len(near_misses)}):")
            for a in near_misses[:3]:
                overlap = concept_words & set(w.lower() for w in re.findall(r'\b\w{4,}\b', a))
                print(f"    ✗ \"{a[:120]}\"")
                print(f"      Mots communs: {overlap}")


if __name__ == "__main__":
    driver = GraphDatabase.driver(URI, auth=AUTH)
    try:
        concepts, assertions, links = get_data(driver)
        run_diagnostic(concepts, assertions, links)
    finally:
        driver.close()
