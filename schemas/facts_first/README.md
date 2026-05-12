# OSMOSIS Facts-First v1 — Schémas formels

> **Statut** : Figé 2026-05-06 (CH-41.M, livrable 1).
> **Décision source** : `doc/ongoing/ADR_V4_FACTS_FIRST.md` D-FF9 (Structured Evidence Package commun).
> **Modification** : interdite sans bump `schema_version` + plan de migration documenté.

## Vue d'ensemble

Ce dossier contient les schémas JSON Schema Draft 2020-12 qui définissent le **contrat de vérité runtime** du pipeline OSMOSIS V4 facts-first. Chaque réponse produite par le Structurer doit valider contre ces schémas avant d'être passée au Composer.

### Principe architectural

```
Question
  ↓ QuestionAnalyzer
  ↓ EvidenceCollector (Claims Neo4j + chunks Qdrant)
  ↓ Type-Adaptive Structurer  ← produit JSON validant ces schémas
  ↓ Composer (LLM cantonné formatage du JSON → prose)
  ↓ Verifier (citation déterministe + NLI ciblé)
Réponse user-facing
```

Le LLM ne décide plus de la **structure** de la réponse. Le Structurer extrait des objets structurés validés par schéma. Le Composer formate la prose **uniquement à partir du JSON** (aucun fait ajouté).

## Fichiers

| Fichier | Rôle | Trigger |
|---------|------|---------|
| `facts_first_v1_common.json` | Socle commun figé : `schema_version`, `primary_type`, `answerability`, `coverage_state`, `language`, `extracted_at`, `extraction_model`, `Source` (référence partagée), `Confidence`, `ItemId`. | Toujours présent, racine de toute réponse Structurer. |
| `facts_first_v1_list.json` | Type list : énumération exhaustive avec `items[]` + `enumeration_quality`. | Présent si `primary_type=list`. |
| `facts_first_v1_factual.json` | Type factual : faits S-P-O avec qualifiers (condition, scope, time_anchor, lifecycle_status). | Présent si `primary_type=factual`. |
| `facts_first_v1_temporal.json` | Type temporal : timeline d'événements + `current_basis`. | Présent si `primary_type=temporal`. |
| `facts_first_v1_comparison.json` | Type comparison : `compared_facts[]` (sides A/B/...) + relation typée. | Présent si `primary_type=comparison`. |
| `facts_first_v1_causal.json` | Type causal : `causal_chains[]` avec steps role-typés + `missing_links`. | Présent si `primary_type=causal`. |
| `facts_first_v1_answerability.json` | Types unanswerable / false_premise : `question_assumption` + `supporting_negative_evidence` + correction optionnelle. | Présent si `primary_type ∈ {unanswerable, false_premise}`. |
| `facts_first_v1_eav.json` | Mode EAV abstention structurée : atomes `{entity, attribute, value, source}` + `disclaimer_required:true` + diagnostic incertitude router. | Présent UNIQUEMENT si confidence QuestionAnalyzer < 0.5. **PAS un chemin de réponse généraliste** (D-FF11). |

## Contrats invariants

### Charte D-FF9 (champs communs figés)

Aucun champ commun ne peut être ajouté/modifié après tranche 1 sans :
1. Bump `schema_version` (`facts_first_v1` → `facts_first_v2`)
2. Plan de migration documenté
3. Validation Fred + relecture LLM tiers

### Charte D-FF10 (extensions Domain Pack)

Certains champs énumérés ont un **core minimal universel** + des extensions Domain Pack possibles. Toute extension doit avoir une règle `maps_to` vers le core minimal pour permettre au Composer générique de produire une réponse cohérente même sans Domain Pack chargé.

| Champ | Core minimal universel | Extensions Domain Pack |
|-------|------------------------|------------------------|
| `comparison.relation.type` | `equivalent`, `different`, `related`, `unknown` | `conflict`, `supersession`, `subset`, `superset`, `complementary`, `BLOCKS`, `REQUIRES`, `CONTRAINDICATES`, ... |
| `comparison.relation.basis` | `value`, `time`, `unknown` | `scope`, `method`, `definition`, `regulatory_framework`, `clinical_context`, ... |
| `temporal.change_type` | `added`, `removed`, `changed`, `unknown` | `replaced`, `modified`, `superseded`, `clarified`, `deprecated_by_amendment`, ... |
| `temporal.time_anchor.kind` | `date`, `version`, `unknown` | `amendment`, `release`, `effective_date`, `applicable_from`, ... |
| `causal.steps.role` | `cause`, `effect`, `condition`, `unknown` | `mechanism`, `exception`, `context`, `motivation`, ... |
| `factual.qualifiers.lifecycle_status` | `ACTIVE`, `DEPRECATED`, `UNKNOWN` | `DRAFT`, `IN_REVIEW`, `WITHDRAWN`, `SUPERSEDED`, ... |
| `list.items[].item_type` | `category`, `regulation`, `entity`, `concept`, `value`, `rule`, `exemption`, `unknown` | Domain-spécifique selon le pack actif |

Format Domain Pack : `domain_packs/<domain>/facts_first_extensions.yaml` (cf livrable 2 CH-41.M).

### Charte D-FF11 (mode EAV abstention)

Le schéma `facts_first_v1_eav.json` est utilisé EXCLUSIVEMENT comme **mode d'abstention structurée**, pas comme chemin généraliste. Activé uniquement si confidence QuestionAnalyzer < 0.5.

- Toujours `disclaimer_required: true` dans la réponse user-facing
- Si > 10% du trafic tombe en EAV → signal de revoir la typologie
- Le Composer DOIT inclure le disclaimer explicite : « Cette question ne correspond pas à un type de réponse pris en charge par OSMOSIS. Voici les faits structurés extraits, sans synthèse interprétative. »

### Citation source obligatoire

Tout objet structuré qui contient un fait/item/event/step doit avoir un `source` validant `$defs/Source` (`doc_id` + `quote` minimum, optionnellement `claim_id`/`chunk_id`/`page_no`/`section_id`). Pas de fait sans citation source verbatim ≥ 10 chars.

## Validation programmatique

### Python

```python
import json, jsonschema
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

# Charger tous les sous-schémas dans un Registry pour résoudre les $ref
registry = Registry()
for name in ["common", "list", "factual", "temporal", "comparison", "causal", "answerability", "eav"]:
    with open(f"schemas/facts_first/facts_first_v1_{name}.json") as f:
        schema = json.load(f)
        registry = registry.with_resource(
            uri=schema["$id"],
            resource=Resource.from_contents(schema)
        )

# Valider une réponse Structurer
with open("schemas/facts_first/facts_first_v1_common.json") as f:
    common_schema = json.load(f)

validator = Draft202012Validator(common_schema, registry=registry)
errors = list(validator.iter_errors(structurer_output))
if errors:
    for e in errors:
        print(f"[{'.'.join(map(str, e.path))}] {e.message}")
```

### Tests recommandés

1. **Round-trip** : pour chaque type, prendre un exemple ADR §3 (`STRUCTURER_V1_DESIGN_REFERENCE.md`), valider qu'il passe le schéma.
2. **Negative tests** : retirer un champ obligatoire → erreur attendue.
3. **Domain Pack extensions** : extension non déclarée → warning ou rejet selon strictness.

## Exemples de validation

Voir `schemas/facts_first/examples/` (à créer en CH-41.0) pour des exemples par type alignés avec le gold-set v4 enrichi.

## Évolution future

| Version | Date | Changements |
|---------|------|-------------|
| `facts_first_v1` | 2026-05-06 | Création initiale (CH-41.M livrable 1) — 7 types + EAV fallback. |

Toute évolution = nouveau fichier `facts_first_v2_common.json` + plan de migration. Pas de modification in-place de v1.
