# Plan — KG Hygiene L3 : Nettoyage des ApplicabilityAxis

**Statut** : VALIDE (v2 — post-revue)

## Contexte

Les `ApplicabilityAxis` qualifient le contexte dans lequel une claim est valide (version, annee, region...). Apres ingestion, le KG peut contenir des axes problematiques :

- **Axes redondants** : `doc_year` (1 doc, "2018") doublonne avec `publication_year` (22 docs, 12 valeurs annuelles)
- **Axes mal nommes** : `date` avec `display_name: "19 Feb 2022"` — le display_name EST une valeur, pas un label
- **Axes mal classifies** : `lifecycle_status` contient "Umbrella Review", "Clinical Trial" — ce sont des types d'etude, pas du lifecycle
- **Axes chevauchants** : `publication_date` ("December 2019") vs `publication_year` ("2019") — meme dimension, granularite differente
- **Axes orphelins** : 1 seul doc, 1 seule valeur, pas de `HAS_AXIS_VALUE` exploitable

## Schema reel (critique)

```
(:ApplicabilityAxis)
  axis_id, axis_key, axis_display_name, axis_hash
  known_values: List[str]      # PAS "values" — c'est "known_values"
  doc_count: int
  is_orderable: bool
  order_type: "total"|"partial"|"none"
  ordering_confidence: "certain"|"inferred"|"unknown"
  value_order: List[str] | null
  source_doc_ids: List[str]
  tenant_id, created_at, updated_at

(:DocumentContext)-[:HAS_AXIS_VALUE]->(:ApplicabilityAxis)
  # Pas de relation directe Claim → ApplicabilityAxis
  # Le lien est DocumentContext → ApplicabilityAxis
```

L'`applicability_frame_json` dans DocumentContext contient les champs axes avec valeurs normalisees, evidence_unit_ids, confidence, reasoning.

## Invariant epistemique

> L3 n'altere jamais les Claims ni les DocumentContext. Il agit uniquement sur les noeuds ApplicabilityAxis et leurs relations HAS_AXIS_VALUE.
> Les articles wiki lies a un axe impacte recoivent le flag `_wiki_stale: true`.

### Divergence graphe / JSON contextuel

Apres `MERGE_AXIS`, la navigation par graphe reflete le nouvel axe consolide, tandis que `applicability_frame_json` dans DocumentContext conserve la trace historique d'extraction. Cette divergence est toleree a court terme — le JSON reste une archive fidele de ce que le LLM a extrait. La normalisation contextuelle (mise a jour des JSON) est un chantier dedie futur, hors perimetre L3.

## Philosophie — Prudence maximale

Les axes sont **structurants** pour la navigation et les comparaisons cross-documents. Une fusion erronee peut fausser les aggregations et rendre les filtres inoperants. Par consequent :

- **Toutes les actions L3 sont PROPOSED** — jamais d'auto-apply
- L'admin valide chaque action depuis l'UI avant application
- Le dry run est le mode d'utilisation principal

## Architecture — 3 regles L3

### Regle 1 : Axes a faible valeur navigationnelle (`low_value_axis`)

**Quand** : `doc_count <= 1` ET `len(known_values) <= 1`

**Garde-fous** (tous doivent etre remplis pour proposer) :
- L'axe n'est PAS le seul axe du tenant (il pourrait devenir utile apres imports)
- L'axe ne partage aucun `source_doc_id` avec un autre axe de meme `axis_key` (sinon c'est peut-etre un axe en cours de construction)
- L'`axis_key` est generique (ex: `date`, `temporal`) — si la cle est specifique et informative, on preserve

**Action** : PROPOSE `SUPPRESS_AXIS`

**Raison** : Categorie `low_navigation_value` — un axe avec 1 seul doc et 1 seule valeur n'a aucune utilite pour la navigation cross-doc. Il ne permet pas de comparer ni de filtrer.

**Note** : "orphelin" ne veut pas dire "parasite". La reason distingue explicitement `low_navigation_value` de `noise` ou `incoherent`.

### Regle 2 : Axes redondants / fusionnables (`redundant_axis`)

**Detection** (deterministe, pas de LLM) :

**Pre-filtre** — grouper les axes par "famille semantique" basee sur les mots-cles de `axis_key` :
- Famille temporelle : `year`, `date`, `temporal` dans la cle
- Famille version : `version`, `release`, `edition` dans la cle
- Famille phase : `phase`, `stage` dans la cle
- Autres : pas de regroupement automatique

**Le pre-filtre est necessaire mais pas suffisant.** La proposition de merge n'emerge que si, en plus du grouping par famille :

1. Les `known_values` sont du meme type (toutes annees, toutes dates, toutes numeriques)
2. L'axe source a un `doc_count` significativement inferieur au target (ratio >= 3:1)
3. Les valeurs du source sont un sous-ensemble (ou quasi-sous-ensemble >=80%) du target
4. Fort recouvrement des `source_doc_ids` (>=50% du source present dans le target) OU le source a tres peu de docs (<=2)

**Exclusion** : Ne JAMAIS proposer la fusion si les cles sont dans `DISTINCT_TEMPORAL_KEYS` :
```
publication_year ≠ effective_year ≠ baseline_year ≠ study_year
publication_date ≠ effective_date ≠ baseline_date
launch_year ≠ end_of_life_year ≠ sunset_year
```

**Action** : PROPOSE `MERGE_AXIS` avec `after_state.merge_target_id`

**Cas typique** : `doc_year` (1 doc, ["2018"]) → fusionner dans `publication_year` (22 docs) car "2018" est deja dans les known_values de publication_year, doc_count ratio = 22:1, memes types de valeurs.

### Regle 3 : Axes mal nommes / incoherents (`misnamed_axis`)

**Pre-filtre deterministe** — ne soumettre au LLM que les axes suspects :
- `axis_display_name` ressemble a une valeur (contient des chiffres, une date, ou est tres long)
- `known_values` sont heterogenes (mix de types : annees + texte libre)
- `axis_key` est tres generique (`date`, `status`, `type`, `value`)

Les axes qui passent le pre-filtre sont evalues par LLM.

**Detection** (LLM-assisted) :

Le LLM recoit l'axe avec ses proprietes et repond :
- Le `axis_key` est-il coherent avec les `known_values` ?
- Le `axis_display_name` est-il un vrai label ou une valeur ?
- Les valeurs sont-elles homogenes entre elles ?

**Exemples de problemes detectes** :
- `lifecycle_status` avec valeurs ["Umbrella Review", "Clinical Trial"] → devrait etre `study_type`
- `date` avec `display_name: "19 Feb 2022"` → display_name est une valeur, pas un label

**Action** : PROPOSE `SUPPRESS_AXIS` avec reason categorie `incoherent` (pour les incoherents). Pour les renommages, la reason est informative ("devrait etre study_type") mais pas d'action — le renommage est un follow-up hors L3.

**Parallelisation** : ThreadPoolExecutor comme les regles L2, batch de 5 axes max. Pas de LLM sur les axes sains (grace au pre-filtre).

## Fichiers

### A creer

| Fichier | Description |
|---------|-------------|
| `src/knowbase/hygiene/rules/layer3_axes.py` | 3 regles L3 axes |
| `tests/hygiene/test_layer3_axes.py` | Tests L3 |

### A modifier

| Fichier | Modification |
|---------|-------------|
| `src/knowbase/hygiene/engine.py` | Ajouter L3 dans le registry des regles |
| `src/knowbase/hygiene/models.py` | Pas de changement (SUPPRESS_AXIS et MERGE_AXIS existent deja) |
| `frontend/src/app/admin/kg-hygiene/page.tsx` | Ajouter bouton "Layer 3" |

## Modele de donnees

Reutilise les types existants :
- `SUPPRESS_AXIS` pour les axes a faible valeur et les incoherents
- `MERGE_AXIS` pour les redondants (with `after_state.merge_target_id`)
- Status : **toujours PROPOSED** (jamais auto-apply pour les axes)
- Reasons categoriees : `low_navigation_value`, `redundant_with:<target_key>`, `incoherent`

## Apply MERGE_AXIS — logique de fusion

Quand un admin approuve un `MERGE_AXIS` :

1. Transferer les `HAS_AXIS_VALUE` du source vers le target
2. Ajouter les `known_values` manquants du source dans le target
3. Mettre a jour le `doc_count` et `source_doc_ids` du target
4. SUPPRESS le source (flag `_hygiene_status`)
5. Ne pas toucher aux `applicability_frame_json` dans les DocumentContext (invariant — voir section Divergence)

## Endpoints

Pas de nouveaux endpoints — reutilise les endpoints existants :
- `POST /api/admin/kg-hygiene/run` avec `layers: [3]`
- Les actions L3 apparaissent dans le meme tableau admin avec le badge "L3"

## UI

- Ajouter un bouton **"Layer 3 (Axes)"** (couleur violet) dans la barre d'actions
- Les actions L3 affichent `axis_key` + `known_values` dans la colonne "Cible"
- Le detail expandable montre les proprietes completes de l'axe

## Points d'attention

1. **Toujours PROPOSED** : les axes sont structurants, pas de risque d'auto-apply
2. **Schema correct** : utiliser `known_values` (pas `values`), relation `HAS_AXIS_VALUE → DocumentContext` (pas `HAS_AXIS → Claim`)
3. **DISTINCT_TEMPORAL_KEYS** : ne jamais fusionner `publication_year` avec `effective_year` meme si les valeurs sont du meme type
4. **Pas de renommage dans L3** : renommer un `axis_key` (ex: `lifecycle_status` → `study_type`) est un changement plus profond qui necessite un chantier dedie
5. **Fusion = transfert HAS_AXIS_VALUE** : la fusion ne modifie pas les DocumentContext ni les Claims
6. **Divergence graphe/JSON toleree** : apres fusion, le graphe est consolide mais les `applicability_frame_json` conservent l'etat original
7. **Pre-filtre LLM** : la regle misnamed_axis ne soumet au LLM que les axes suspects (display_name = valeur, known_values heterogenes, cle generique)
8. **Reasons categoriees** : distinguer `low_navigation_value`, `redundant_with:<key>`, `incoherent` dans les raisons — aide l'admin a comprendre la nature du probleme

## Verification

1. Dry run L3 → detection de `doc_year` comme redondant avec `publication_year`
2. Dry run L3 → detection de `date` comme axe mal nomme (display_name = valeur)
3. Dry run L3 → detection d'axes orphelins (1 doc, 1 valeur) avec raison `low_navigation_value`
4. Approbation d'un MERGE_AXIS → `HAS_AXIS_VALUE` transferees, source supprime
5. Rollback d'un MERGE_AXIS → source restaure, `HAS_AXIS_VALUE` restaurees
6. Les axes avec cles dans DISTINCT_TEMPORAL_KEYS ne sont JAMAIS proposes en fusion
7. La regle misnamed_axis ne soumet PAS les axes sains au LLM (pre-filtre efficace)
