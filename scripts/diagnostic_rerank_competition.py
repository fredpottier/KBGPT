"""
Diagnostic D1+D2: Compétition locale et concepts vides
======================================================

D1 — Pour chaque info du concept aspirateur:
     quels concepts étaient candidats (2e, 3e...) et avec quels scores?

D2 — Pour chaque concept vide:
     activation_rate=0 (triggers ne matchent rien)?
     ou perd systématiquement contre un voisin plus général?

Recalcule les scores de rerank pour TOUTES les paires (assertion, concept)
puis compare avec les gagnants effectifs dans Neo4j.

Usage:
    docker exec knowbase-app python scripts/diagnostic_rerank_competition.py
"""

import re
import sys
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Setup logging minimal
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# =============================================================================
# Helpers de scoring (reproduits depuis assertion_extractor.py)
# =============================================================================

VALUE_PATTERN = re.compile(r'^\d+(\.\d+)*[%°]?[CFc]?$|^\d+[:\-]\d+$')


def match_trigger_in_text(trigger: str, text: str) -> bool:
    """Helper unique de matching trigger → texte (identique au code prod)."""
    t = trigger.lower()
    text_lower = text.lower()
    if len(t) >= 4:
        return bool(re.search(rf'\b{re.escape(t)}\b', text_lower))
    else:
        return bool(re.search(rf'(?<![a-z]){re.escape(t)}(?![a-z])', text_lower))


def compute_lexical_bonus(
    assertion_text: str,
    triggers: List[str],
    trigger_toxicity: Dict[str, float],
    concept_activation: float,
) -> Tuple[float, str]:
    """
    Reproduit _compute_lexical_bonus() avec traçabilité.
    Retourne (bonus, raison).
    """
    if not assertion_text:
        return 1.0, "empty_text"

    # GF-A
    if concept_activation == 0.0:
        return 1.0, "GF-A:activation=0"

    max_bonus = 1.25
    if 0.0 < concept_activation < 0.01:
        max_bonus = 1.10

    if triggers:
        for trigger in triggers:
            if match_trigger_in_text(trigger, assertion_text):
                tox = trigger_toxicity.get(trigger.lower(), 0.0)
                if tox > 0.08:
                    continue  # toxique
                elif tox > 0.03:
                    return min(1.10, max_bonus), f"trigger_weak:{trigger}(tox={tox:.1%})"
                else:
                    return min(1.25, max_bonus), f"trigger_match:{trigger}(tox={tox:.1%})"

    return 1.0, "no_trigger_match"


# =============================================================================
# Neo4j queries
# =============================================================================

def get_neo4j_driver():
    """Crée un driver Neo4j."""
    from neo4j import GraphDatabase
    import os
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def fetch_concepts(session) -> List[Dict]:
    """Récupère tous les concepts avec triggers."""
    result = session.run("""
        MATCH (c:Concept)
        WHERE c.tenant_id = 'default'
        OPTIONAL MATCH (c)-[:HAS_INFORMATION]->(i:Information)
        WITH c, count(i) as info_count
        RETURN c.concept_id as concept_id,
               c.name as name,
               c.role as role,
               c.lexical_triggers as triggers,
               info_count
        ORDER BY info_count DESC
    """)
    return [dict(r) for r in result]


def fetch_informations_for_concept(session, concept_id: str) -> List[Dict]:
    """Récupère les informations d'un concept."""
    result = session.run("""
        MATCH (c:Concept {concept_id: $cid})-[:HAS_INFORMATION]->(i:Information)
        RETURN i.info_id as info_id,
               i.text as text,
               i.confidence as confidence,
               i.type as type
        ORDER BY i.confidence DESC
    """, cid=concept_id)
    return [dict(r) for r in result]


def fetch_all_assertion_texts(session) -> List[Dict]:
    """Récupère toutes les assertions (Information + AssertionLog) pour coverage."""
    # Informations = assertions qui ont été liées
    result = session.run("""
        MATCH (i:Information)
        WHERE i.tenant_id = 'default'
        RETURN i.info_id as id, i.text as text, i.confidence as confidence,
               i.type as type
    """)
    return [dict(r) for r in result]


# =============================================================================
# D1: Compétition locale autour du concept aspirateur
# =============================================================================

@dataclass
class CompetitionEntry:
    concept_id: str
    concept_name: str
    role: str
    bonus: float
    bonus_reason: str
    simulated_score: float  # conf_finale * bonus


def diagnostic_d1(session, concepts: List[Dict], trigger_toxicity: Dict[str, float],
                  concept_activations: Dict[str, float]):
    """
    D1: Pour le concept aspirateur (max infos), recalculer la compétition
    sur chacune de ses 39 assertions.
    """
    print("\n" + "=" * 80)
    print("D1 — COMPÉTITION LOCALE AUTOUR DU CONCEPT ASPIRATEUR")
    print("=" * 80)

    # Trouver le concept aspirateur (max info_count)
    aspirator = concepts[0]
    print(f"\nConcept aspirateur: {aspirator['name']} ({aspirator['concept_id']})")
    print(f"  Rôle: {aspirator['role']}, Infos: {aspirator['info_count']}")
    print(f"  Triggers: {aspirator['triggers']}")

    # Récupérer ses informations
    infos = fetch_informations_for_concept(session, aspirator['concept_id'])
    print(f"\n  {len(infos)} informations à analyser")

    # Pour chaque assertion, calculer le score pour TOUS les concepts
    close_losses = 0     # 2e candidat à < 0.10 du gagnant
    no_competitor = 0    # Pas de 2e candidat viable
    clear_wins = 0       # Gagnant clairement devant
    competitor_stats = defaultdict(int)  # {concept_name: nb fois 2e}

    for idx, info in enumerate(infos):
        text = info['text']
        conf = info['confidence']

        # Calculer bonus pour tous les concepts
        candidates = []
        for c in concepts:
            triggers = c.get('triggers') or []
            activation = concept_activations.get(c['concept_id'], 0.0)
            bonus, reason = compute_lexical_bonus(text, triggers, trigger_toxicity, activation)

            # Simuler le score central
            bonus_central = 1.10 if c['role'] == 'CENTRAL' else 1.0
            simulated = conf * bonus * bonus_central

            candidates.append(CompetitionEntry(
                concept_id=c['concept_id'],
                concept_name=c['name'],
                role=c['role'],
                bonus=bonus,
                bonus_reason=reason,
                simulated_score=simulated
            ))

        # Trier par score décroissant
        candidates.sort(key=lambda x: -x.simulated_score)

        # Le gagnant devrait être le concept aspirateur (sinon intéressant aussi)
        winner = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None

        # Analyser la compétition
        if runner_up is None or runner_up.simulated_score < 0.35:
            no_competitor += 1
        elif winner.simulated_score - runner_up.simulated_score < 0.10:
            close_losses += 1
            competitor_stats[runner_up.concept_name] += 1
        else:
            clear_wins += 1

        # Afficher les 5 premières et les plus intéressantes
        if idx < 5 or (runner_up and winner.simulated_score - runner_up.simulated_score < 0.10):
            print(f"\n  [{idx}] \"{text[:80]}...\"")
            print(f"      Conf Neo4j: {conf:.2f}")
            for rank, c in enumerate(candidates[:4]):
                marker = "★" if c.concept_id == aspirator['concept_id'] else " "
                print(
                    f"      {marker} #{rank+1} {c.concept_name:45s} "
                    f"score={c.simulated_score:.2f} "
                    f"(bonus={c.bonus:.2f} {c.bonus_reason})"
                )

    # Résumé D1
    print(f"\n{'─' * 60}")
    print(f"RÉSUMÉ D1 — Compétition sur {len(infos)} infos du concept aspirateur:")
    print(f"  Victoires claires (écart > 0.10):     {clear_wins}")
    print(f"  Compétitions serrées (écart < 0.10):  {close_losses}")
    print(f"  Pas de concurrent viable:             {no_competitor}")

    if close_losses > 0:
        print(f"\n  → {close_losses}/{len(infos)} = {close_losses/len(infos):.0%} "
              f"sont des TIE-BREAKING serrés")
        print(f"\n  Top concurrents (2e position fréquente):")
        for name, count in sorted(competitor_stats.items(), key=lambda x: -x[1])[:5]:
            print(f"    - {name}: {count}x 2e")
    else:
        print(f"\n  → Pas de problème de tie-breaking, le concept aspirateur gagne clairement")

    return {
        "clear_wins": clear_wins,
        "close_losses": close_losses,
        "no_competitor": no_competitor,
        "competitor_stats": dict(competitor_stats),
    }


# =============================================================================
# D2: Pourquoi concept vide?
# =============================================================================

def diagnostic_d2(session, concepts: List[Dict], trigger_toxicity: Dict[str, float],
                  concept_activations: Dict[str, float]):
    """
    D2: Pour chaque concept à 0 info, diagnostiquer:
    - activation_rate = 0 ? (triggers matchent 0 assertion)
    - ou perd toujours contre un voisin ?
    """
    print("\n" + "=" * 80)
    print("D2 — POURQUOI CONCEPT VIDE ?")
    print("=" * 80)

    # Récupérer toutes les informations (= assertions liées)
    all_infos = fetch_all_assertion_texts(session)
    all_texts = [i['text'] for i in all_infos]
    print(f"\n  Total informations en base: {len(all_infos)}")

    empty_concepts = [c for c in concepts if c['info_count'] == 0]
    print(f"  Concepts vides à analyser: {len(empty_concepts)}")

    # Catégories de diagnostic
    cat_no_trigger = []          # Pas de triggers du tout
    cat_activation_zero = []     # Triggers ne matchent aucune assertion
    cat_all_toxic = []           # Tous triggers toxiques
    cat_loses_competition = []   # Matche mais perd toujours
    cat_threshold_filtered = []  # Matche mais sous le seuil

    for c in empty_concepts:
        triggers = c.get('triggers') or []
        activation = concept_activations.get(c['concept_id'], -1.0)
        name = c['name']

        if not triggers:
            cat_no_trigger.append(c)
            continue

        # Calculer le matching sur toutes les assertions
        matching_assertions = []
        for text in all_texts:
            bonus, reason = compute_lexical_bonus(
                text, triggers, trigger_toxicity, activation
            )
            if bonus > 1.0:
                matching_assertions.append((text, bonus, reason))

        # Trigger toxicité
        all_toxic = all(
            trigger_toxicity.get(t.lower(), 0.0) > 0.08
            for t in triggers
        )

        if all_toxic:
            cat_all_toxic.append({**c, 'detail': f"triggers={triggers}"})
            continue

        if activation == 0.0 and not matching_assertions:
            cat_activation_zero.append({
                **c,
                'detail': f"triggers={triggers}, 0 match sur {len(all_texts)} assertions"
            })
            continue

        if matching_assertions:
            # Il matche des assertions mais n'a gagné aucune compétition
            # Vérifier contre qui il perd
            losses = defaultdict(int)
            for text, bonus, reason in matching_assertions[:20]:  # Échantillon
                # Qui a gagné cette assertion?
                best_concept = None
                best_score = 0
                for other_c in concepts:
                    if other_c['info_count'] == 0:
                        continue
                    other_triggers = other_c.get('triggers') or []
                    other_activation = concept_activations.get(other_c['concept_id'], 0.0)
                    other_bonus, _ = compute_lexical_bonus(
                        text, other_triggers, trigger_toxicity, other_activation
                    )
                    other_central = 1.10 if other_c['role'] == 'CENTRAL' else 1.0
                    score = other_bonus * other_central
                    if score > best_score:
                        best_score = score
                        best_concept = other_c['name']

                if best_concept:
                    losses[best_concept] += 1

            cat_loses_competition.append({
                **c,
                'n_matches': len(matching_assertions),
                'losses': dict(losses),
                'sample_match': matching_assertions[0] if matching_assertions else None,
            })
        else:
            cat_threshold_filtered.append({
                **c,
                'detail': f"activation={activation:.1%}, triggers={triggers}"
            })

    # Affichage D2
    print(f"\n{'─' * 60}")
    print(f"DIAGNOSTIC D2 — {len(empty_concepts)} concepts vides:")
    print()

    if cat_no_trigger:
        print(f"  📭 PAS DE TRIGGERS ({len(cat_no_trigger)}):")
        for c in cat_no_trigger:
            print(f"     - {c['name']} ({c['role']})")

    if cat_activation_zero:
        print(f"\n  🔇 ACTIVATION = 0 — triggers ne matchent rien ({len(cat_activation_zero)}):")
        for c in cat_activation_zero:
            print(f"     - {c['name']} ({c['role']})")
            print(f"       triggers: {c.get('triggers', [])}")

    if cat_all_toxic:
        print(f"\n  ☠️  TOUS TRIGGERS TOXIQUES ({len(cat_all_toxic)}):")
        for c in cat_all_toxic:
            print(f"     - {c['name']} ({c['role']})")
            print(f"       {c['detail']}")

    if cat_loses_competition:
        print(f"\n  🥊 PERD LA COMPÉTITION — matche mais un voisin gagne ({len(cat_loses_competition)}):")
        for c in cat_loses_competition:
            print(f"     - {c['name']} ({c['role']}), {c['n_matches']} matches potentiels")
            if c.get('losses'):
                top_rival = max(c['losses'].items(), key=lambda x: x[1])
                print(f"       Rival principal: {top_rival[0]} ({top_rival[1]}x)")
            if c.get('sample_match'):
                text, bonus, reason = c['sample_match']
                print(f"       Exemple: \"{text[:70]}...\" (bonus={bonus:.2f}, {reason})")

    if cat_threshold_filtered:
        print(f"\n  🚫 FILTRÉ PAR SEUIL ({len(cat_threshold_filtered)}):")
        for c in cat_threshold_filtered:
            print(f"     - {c['name']} ({c['role']})")
            print(f"       {c['detail']}")

    # Résumé
    print(f"\n{'─' * 60}")
    print("RÉSUMÉ D2:")
    print(f"  Pas de triggers:          {len(cat_no_trigger)}")
    print(f"  Activation = 0:           {len(cat_activation_zero)}")
    print(f"  Tous triggers toxiques:   {len(cat_all_toxic)}")
    print(f"  Perd la compétition:      {len(cat_loses_competition)}")
    print(f"  Filtré par seuil:         {len(cat_threshold_filtered)}")

    n_trigger_problem = len(cat_no_trigger) + len(cat_activation_zero) + len(cat_all_toxic)
    n_scoring_problem = len(cat_loses_competition)
    print(f"\n  → Problème de TRIGGERS: {n_trigger_problem} concepts "
          f"({n_trigger_problem}/{len(empty_concepts)})")
    print(f"  → Problème de SCORING:  {n_scoring_problem} concepts "
          f"({n_scoring_problem}/{len(empty_concepts)})")

    if n_trigger_problem > n_scoring_problem:
        print(f"\n  ⚡ VERDICT: Améliorer les TRIGGERS (pick-list) serait plus rentable")
    elif n_scoring_problem > n_trigger_problem:
        print(f"\n  ⚡ VERDICT: Améliorer le SCORING / compétition (rerank) serait plus rentable")
    else:
        print(f"\n  ⚡ VERDICT: Les deux axes sont nécessaires")

    return {
        "no_trigger": len(cat_no_trigger),
        "activation_zero": len(cat_activation_zero),
        "all_toxic": len(cat_all_toxic),
        "loses_competition": len(cat_loses_competition),
        "threshold_filtered": len(cat_threshold_filtered),
    }


# =============================================================================
# Pré-calcul toxicité (identique au code prod)
# =============================================================================

def precompute_toxicity(concepts: List[Dict], all_texts: List[str]) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Recalcule trigger_toxicity et concept_activation."""
    total = len(all_texts)
    if total == 0:
        return {}, {}

    # Collecter tous les triggers
    all_triggers = set()
    for c in concepts:
        for t in (c.get('triggers') or []):
            all_triggers.add(t.lower())

    # Compter matches
    trigger_toxicity = {}
    for t_lower in all_triggers:
        count = sum(1 for text in all_texts if match_trigger_in_text(t_lower, text))
        trigger_toxicity[t_lower] = count / total

    # Activation par concept
    concept_activation = {}
    for c in concepts:
        triggers = c.get('triggers') or []
        if not triggers:
            concept_activation[c['concept_id']] = 0.0
            continue

        non_toxic = [t for t in triggers if trigger_toxicity.get(t.lower(), 0.0) <= 0.08]
        if not non_toxic:
            concept_activation[c['concept_id']] = 0.0
            continue

        matching = sum(
            1 for text in all_texts
            if any(match_trigger_in_text(t, text) for t in non_toxic)
        )
        concept_activation[c['concept_id']] = matching / total

    return trigger_toxicity, concept_activation


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 80)
    print("DIAGNOSTIC RERANK — Compétition locale + concepts vides")
    print("=" * 80)

    driver = get_neo4j_driver()

    with driver.session() as session:
        # Récupérer données
        concepts = fetch_concepts(session)
        all_infos = fetch_all_assertion_texts(session)
        all_texts = [i['text'] for i in all_infos]

        print(f"\n  Concepts: {len(concepts)}")
        print(f"  Informations: {len(all_infos)}")

        # Distribution rapide
        print(f"\n  Distribution info/concept:")
        for c in concepts[:10]:
            bar = "█" * min(c['info_count'], 40)
            print(f"    {c['name']:45s} {c['info_count']:3d} {bar}")
        if len(concepts) > 10:
            empty = sum(1 for c in concepts if c['info_count'] == 0)
            print(f"    ... +{len(concepts) - 10} concepts ({empty} vides)")

        # Pré-calculer toxicité
        print(f"\n  Calcul toxicité des triggers...")
        trigger_toxicity, concept_activations = precompute_toxicity(concepts, all_texts)

        # Afficher triggers toxiques
        toxic = {t: f for t, f in trigger_toxicity.items() if f > 0.08}
        if toxic:
            print(f"  Triggers toxiques (>8%): {len(toxic)}")
            for t, f in sorted(toxic.items(), key=lambda x: -x[1])[:10]:
                print(f"    - \"{t}\": {f:.1%}")

        # D1
        d1_result = diagnostic_d1(session, concepts, trigger_toxicity, concept_activations)

        # D2
        d2_result = diagnostic_d2(session, concepts, trigger_toxicity, concept_activations)

    driver.close()

    # Verdict final
    print("\n" + "=" * 80)
    print("VERDICT FINAL")
    print("=" * 80)

    close_pct = d1_result['close_losses'] / max(1, sum(d1_result[k] for k in ['clear_wins', 'close_losses', 'no_competitor']))
    trigger_problem = d2_result['no_trigger'] + d2_result['activation_zero'] + d2_result['all_toxic']
    scoring_problem = d2_result['loses_competition']

    print(f"\n  D1: {close_pct:.0%} des liens du concept aspirateur sont des tie-breaks serrés")
    print(f"  D2: {trigger_problem} concepts vides par problème de triggers, "
          f"{scoring_problem} par problème de scoring")

    if close_pct > 0.30 and scoring_problem > trigger_problem:
        print(f"\n  → PRIORITÉ: Améliorer le scoring/compétition (rerank sémantique)")
        print(f"    Le concept aspirateur gagne par défaut, pas par mérite")
    elif trigger_problem > scoring_problem:
        print(f"\n  → PRIORITÉ: Améliorer les triggers (pick-list / TF-IDF)")
        print(f"    Les concepts vides n'ont pas de signal lexical")
    else:
        print(f"\n  → Les deux axes sont nécessaires (triggers + scoring)")

    print()


if __name__ == "__main__":
    main()
