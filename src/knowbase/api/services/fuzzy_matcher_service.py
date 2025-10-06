"""
FuzzyMatcherService - Matching entités avec ontologie (seuil adaptatif).

Phase 5B - Solution 3 Hybride
Step 3 - Fuzzy Matching avec seuils adaptatifs

Utilise fuzzywuzzy pour calculer similarité textuelle.
Seuils :
- >= 90% : Auto-match (haute confiance)
- 75-89% : Match suggéré (confirmation manuelle)
- < 75% : Pas de match (trop faible)
"""
from typing import Dict, List, Optional, Tuple
from fuzzywuzzy import fuzz

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "fuzzy_matcher.log")


class FuzzyMatcherService:
    """Service de fuzzy matching entre entités et ontologie."""

    # Seuils de confiance (Option C validée par user)
    THRESHOLD_HIGH = 90  # Auto-match
    THRESHOLD_LOW = 75   # Match suggéré (confirmation requise)

    def __init__(self):
        """Initialize service."""
        pass

    def match_entity_to_ontology(
        self,
        entity_name: str,
        ontology_entry: Dict
    ) -> Tuple[bool, float, str]:
        """
        Match une entité contre une entrée ontologie.

        Args:
            entity_name: Nom entité à matcher
            ontology_entry: Dict avec canonical_name et aliases

        Returns:
            Tuple (is_match, score, matched_name)
            - is_match: True si score >= THRESHOLD_LOW
            - score: Score similarité (0-100)
            - matched_name: Nom qui a matché (canonical ou alias)
        """
        canonical_name = ontology_entry.get("canonical_name", "")
        aliases = ontology_entry.get("aliases", [])

        # Tester canonical name
        canonical_score = fuzz.ratio(entity_name.lower(), canonical_name.lower())

        # Tester aliases
        best_alias_score = 0
        best_alias_name = canonical_name

        for alias in aliases:
            alias_score = fuzz.ratio(entity_name.lower(), alias.lower())
            if alias_score > best_alias_score:
                best_alias_score = alias_score
                best_alias_name = alias

        # Prendre le meilleur score
        if canonical_score > best_alias_score:
            final_score = canonical_score
            matched_name = canonical_name
        else:
            final_score = best_alias_score
            matched_name = best_alias_name

        is_match = final_score >= self.THRESHOLD_LOW

        return (is_match, final_score, matched_name)

    def compute_merge_preview(
        self,
        entities: List[Dict],
        ontology: Dict
    ) -> Dict:
        """
        Calcule preview des merges entre entités et ontologie.

        Args:
            entities: Liste entités Neo4j (uuid, name, description, etc.)
            ontology: Dict ontologie (keys = CANONICAL_KEY, values = {canonical_name, aliases, ...})

        Returns:
            Dict avec structure:
            {
                "merge_groups": [
                    {
                        "canonical_key": "SAP_S4HANA_PRIVATE_CLOUD",
                        "canonical_name": "SAP S/4HANA Private Cloud Edition",
                        "entities": [
                            {
                                "uuid": "...",
                                "name": "SAP S/4HANA PCE",
                                "score": 92,
                                "auto_match": true,
                                "selected": true
                            },
                            {
                                "uuid": "...",
                                "name": "SAP S/4 HANA Cloud",
                                "score": 78,
                                "auto_match": false,
                                "selected": false  # Confirmation manuelle requise
                            }
                        ],
                        "master_uuid": "..."  # UUID entité avec plus de relations
                    }
                ],
                "summary": {
                    "total_entities": 47,
                    "entities_matched": 35,
                    "entities_unmatched": 12,
                    "groups_proposed": 12,
                    "auto_matches": 28,
                    "manual_matches": 7
                }
            }
        """
        logger.info(
            f"🔍 Calcul preview merge: {len(entities)} entités, "
            f"{len(ontology)} groupes ontologie"
        )

        merge_groups = []
        matched_entity_uuids = set()

        for canonical_key, ontology_entry in ontology.items():
            group_entities = []

            # Tester chaque entité contre cette entrée ontologie
            for entity in entities:
                if entity["uuid"] in matched_entity_uuids:
                    continue  # Déjà matché avec un autre groupe

                is_match, score, matched_name = self.match_entity_to_ontology(
                    entity["name"],
                    ontology_entry
                )

                if is_match:
                    auto_match = score >= self.THRESHOLD_HIGH
                    selected = auto_match  # Auto-coché si >= 90%

                    group_entities.append({
                        "uuid": entity["uuid"],
                        "name": entity["name"],
                        "description": entity.get("description", ""),
                        "score": score,
                        "auto_match": auto_match,
                        "selected": selected,
                        "matched_via": matched_name
                    })

                    matched_entity_uuids.add(entity["uuid"])

            # Si au moins une entité matche, créer groupe
            if len(group_entities) > 0:
                # Choisir master (celui avec le meilleur score, ou premier)
                master = max(group_entities, key=lambda e: e["score"])

                merge_groups.append({
                    "canonical_key": canonical_key,
                    "canonical_name": ontology_entry["canonical_name"],
                    "description": ontology_entry.get("description", ""),
                    "confidence": ontology_entry.get("confidence", 0.0),
                    "entities": group_entities,
                    "master_uuid": master["uuid"]
                })

        # Calculer statistiques
        total_matched = len(matched_entity_uuids)
        total_unmatched = len(entities) - total_matched

        auto_matches = sum(
            len([e for e in g["entities"] if e["auto_match"]])
            for g in merge_groups
        )
        manual_matches = total_matched - auto_matches

        summary = {
            "total_entities": len(entities),
            "entities_matched": total_matched,
            "entities_unmatched": total_unmatched,
            "groups_proposed": len(merge_groups),
            "auto_matches": auto_matches,
            "manual_matches": manual_matches
        }

        logger.info(
            f"✅ Preview calculé: {summary['groups_proposed']} groupes, "
            f"{summary['entities_matched']}/{summary['total_entities']} matchées "
            f"({summary['auto_matches']} auto, {summary['manual_matches']} manuelles)"
        )

        return {
            "merge_groups": merge_groups,
            "summary": summary
        }

    def filter_selected_merges(
        self,
        merge_preview: Dict,
        user_selections: Dict[str, List[str]]
    ) -> Dict:
        """
        Filtre preview selon sélections utilisateur.

        Args:
            merge_preview: Preview complet généré
            user_selections: Dict {canonical_key: [uuid1, uuid2, ...]}
                            UUIDs cochés par l'utilisateur

        Returns:
            Preview filtré avec seulement entités cochées
        """
        filtered_groups = []

        for group in merge_preview["merge_groups"]:
            canonical_key = group["canonical_key"]

            if canonical_key not in user_selections:
                continue  # Groupe ignoré par user

            selected_uuids = set(user_selections[canonical_key])

            # Filtrer entités selon sélections
            filtered_entities = [
                e for e in group["entities"]
                if e["uuid"] in selected_uuids
            ]

            if len(filtered_entities) == 0:
                continue  # Aucune entité sélectionnée

            # Recalculer master parmi entités sélectionnées
            master = max(filtered_entities, key=lambda e: e["score"])

            filtered_groups.append({
                **group,
                "entities": filtered_entities,
                "master_uuid": master["uuid"]
            })

        # Recalculer summary
        total_selected = sum(len(g["entities"]) for g in filtered_groups)

        return {
            "merge_groups": filtered_groups,
            "summary": {
                "groups_selected": len(filtered_groups),
                "entities_selected": total_selected
            }
        }


__all__ = ["FuzzyMatcherService"]
