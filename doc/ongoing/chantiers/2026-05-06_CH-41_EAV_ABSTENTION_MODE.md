# Mode EAV — Abstention structurée (Facts-First v1)

> **Status** : Figé 2026-05-06 (CH-41.M, livrable 3)
> **Décision source** : `ADR_V4_FACTS_FIRST.md` D-FF11
> **Schéma associé** : `schemas/facts_first/facts_first_v1_eav.json`

## 1. Pourquoi ce mode existe

Le pipeline V4 facts-first reconnait **6 types primaires** (factual, list, temporal, comparison, causal, unanswerable/false_premise). Mais une question utilisateur peut tomber **hors typologie** :
- Multi-label avec confidence basse (< 0.5)
- Question méta sur le système OSMOSIS lui-même
- Question composite à plusieurs intentions floues
- Question dans un domaine non encore couvert par un Domain Pack

**Sans mode EAV** → le pipeline retomberait silencieusement en LLM-libre (V3 actuel) → réintroduction du problème de compression sémantique destructive qu'on cherche à fuir.

**Avec mode EAV** → extraction d'atomes minimaux `{entity, attribute, value, source}` + disclaimer explicite à l'utilisateur. La structure subsiste même quand la typologie échoue.

## 2. Activation — quand ce mode se déclenche

Le QuestionAnalyzer (composant [A] du pipeline) renvoie un type primaire avec une confidence. Trois cas :

| Confidence top-1 | Action pipeline |
|------------------|-----------------|
| ≥ 0.7 | Type unique → schéma type-specific complet |
| 0.5 - 0.7 | Multi-label top-2 → composition combinée des deux schémas |
| **< 0.5** | **Mode EAV activé** — schéma `facts_first_v1_eav.json` |

Aucune autre condition d'activation. Pas de heuristique métier, pas de keyword, pas de règle conditionnelle. Le seul signal est la confidence du router.

## 3. Caractéristiques du mode EAV

### 3.1 Schéma minimal universel

Le schéma EAV contient :
- `disclaimer_required: true` (toujours, garde-fou figé)
- `atoms[]` : array d'atomes `{atom_id, entity, attribute, value, source, confidence}`
- `router_uncertainty` : diagnostic de l'incertitude qui a déclenché le mode

Pas de qualifiers, pas de relations typées, pas de timeline. **Le minimum strict pour préserver la traçabilité source.**

### 3.2 Pas de normalisation

En mode EAV, les `value` sont stockés verbatim sans normalisation (ex pas de date ISO, pas d'unité standardisée). Justification : on n'a pas confiance dans la typologie de la question, donc on ne sait pas quel type de normalisation appliquer. Mieux vaut le verbatim brut que des normalisations hasardeuses.

### 3.3 Persistance Neo4j

Les atomes EAV ne sont **pas persistés** dans Neo4j (pas de nœud `:StructuredEAV`). Runtime-only. Justification : si la typologie est incertaine, on ne veut pas polluer le KG avec des atomes mal qualifiés.

## 4. Disclaimer obligatoire

Le Composer reçoit le JSON EAV avec `disclaimer_required: true`. Sa réponse user-facing **DOIT** commencer par un disclaimer explicite.

### Disclaimer canonique (FR)
```
Cette question ne correspond pas à un type de réponse pris en charge par OSMOSIS.
Voici les faits structurés extraits, sans synthèse interprétative.
```

### Disclaimer canonique (EN)
```
This question does not match a supported answer type in OSMOSIS.
Here are the structured facts extracted, without interpretive synthesis.
```

Ces disclaimers peuvent être adaptés (formulation tone-of-voice produit) mais doivent contenir les 2 informations critiques :
1. **Le système n'est pas confiant** sur la typologie (transparence)
2. **Pas de synthèse interprétative** (pas de réponse fabriquée)

### Format de réponse user-facing en mode EAV

```
[Disclaimer]

[Liste des atomes formatés en bullet points avec citation source par atome]

[Optionnel] : suggestion de reformulation si plausible.
```

Exemple :
```
Cette question ne correspond pas à un type de réponse pris en charge par OSMOSIS.
Voici les faits structurés extraits, sans synthèse interprétative.

- OSMOSIS — décrit comme — "un système RAG+KG pour Q&A sur corpus régulé"
  [doc=osmose_internal, p.1, "OSMOSIS construit un système RAG+KG..."]

- Pipeline V3 — synthesizer — "Qwen2.5-72B via DeepInfra"
  [doc=osmose_internal, p.2, "synthesis = Qwen2.5-72B-Instruct (DeepInfra)"]

Suggestion : reformulez votre question en spécifiant ce que vous cherchez
(une définition, une liste d'éléments, une comparaison, etc.).
```

## 5. Anti-patterns interdits

Le mode EAV existe pour **éviter** ces dérives :

### 5.1 ❌ Pas de fallback LLM-libre silencieux
Si confidence < 0.5, **NE PAS** rebasculer sur le pipeline V3 LLM-centric. C'est exactement le pattern qu'on a abandonné post-Sprint S0 (factual_correctness 0.37, item_recall 0.07).

### 5.2 ❌ Pas de chemin généraliste
Le mode EAV n'est **pas** un chemin de réponse à part entière qu'on optimiserait. C'est une abstention contrôlée. Tout effort d'amélioration doit aller vers :
- Améliorer le router (réduire le taux EAV)
- Étendre la typologie (ajouter type 8e/9e si patterns récurrents)
- Étendre via Domain Pack (si problème domain-spécifique)

Pas vers : « rendre le mode EAV plus intelligent ».

### 5.3 ❌ Pas de tentative de typer rétroactivement
Le Structurer EAV ne doit pas essayer de deviner le primary_type a posteriori en regardant les atomes extraits. Si le router a dit `< 0.5 confidence`, on respecte ce signal.

### 5.4 ❌ Pas d'omission du disclaimer
Le Composer ne peut **jamais** retirer le disclaimer même si la réponse semble cohérente. Le `disclaimer_required: true` est une contrainte schéma figée.

## 6. Garde-fou opérationnel — alerte > 10% trafic EAV

### Métrique de surveillance
```
eav_rate = (#requests routed to EAV) / (#total requests)
```

### Seuils
| Seuil | Action |
|-------|--------|
| `eav_rate < 5%` | Normal — la typologie couvre bien les usages |
| `5% ≤ eav_rate < 10%` | Surveillance — analyser les questions EAV pour patterns récurrents |
| `eav_rate ≥ 10%` | **Alerte** — la typologie est insuffisante, revoir |

### Diagnostic en cas d'alerte
Quand `eav_rate ≥ 10%` :
1. Extraire les `router_uncertainty.top_candidate_type` des dernières 100 requêtes EAV
2. Identifier les patterns (ex 30% sont multi-label list+temporal, 20% sont des questions méta...)
3. Décider : ajouter un type, étendre via Domain Pack, ou améliorer le router (retraining sur les exemples)

### Tableau de bord recommandé
- Graphe `eav_rate` glissant 7 jours
- Top 10 patterns `router_uncertainty.reason` agrégés
- Échantillon de 20 questions EAV récentes pour audit qualité

## 7. Évaluation du mode EAV

### Métriques mesurées
- **EAV rate** (cf §6)
- **Atom extraction precision** : sur un sample EAV, % atomes dont l'`source.quote` est verbatim dans le doc cité
- **User satisfaction proxy** : taux de re-formulation suivante par l'utilisateur (signal négatif si > 50%)

### Gates qualité
- Atom extraction precision ≥ 0.85 (atomes verbatim correctement attribués)
- Source citation rate = 100% (pas d'atome sans source)
- Disclaimer présent dans 100% des réponses EAV (vérifié déterministiquement)

### Métriques NON utilisées en EAV
- **PAS** factual_correctness (pas de référence ground_truth pour questions hors-typologie)
- **PAS** item_recall (pas d'enumeration attendue)
- **PAS** faithfulness RAGAS (le contexte est trop variable)

Le mode EAV ne se mesure pas en qualité de réponse end-to-end. Il se mesure en **fidélité d'extraction** + **honnêteté du disclaimer**.

## 8. Évolution future

### Quand ajouter un nouveau type primaire ?
Quand l'analyse `router_uncertainty.top_candidate_type` révèle un pattern stable (≥ 50 questions sur 1 mois avec un même type implicite mal couvert), on peut :
1. Définir un nouveau type primaire (ex `procedural` pour questions how-to)
2. Définir son schéma type-specific
3. Étendre le QuestionAnalyzer pour le détecter

C'est exactement comme ça qu'on devrait passer de 6 → 7 → 8 types si nécessaire — pas en élargissant le mode EAV.

### Quand étendre via Domain Pack ?
Si l'EAV rate est élevé sur un domaine spécifique (ex software docs : 25%) mais bas ailleurs, c'est un signal pour étendre le Domain Pack avec des hints + extensions de schéma (cf D-FF10).

### Versioning du mode EAV
Le mode EAV est figé à `facts_first_v1`. Si bump à `v2`, le mode EAV peut évoluer mais reste contraint par les invariants ci-dessus (disclaimer obligatoire, pas de fallback LLM-libre, pas de chemin généraliste).

## 9. Référentiels

- ADR : `doc/ongoing/ADR_V4_FACTS_FIRST.md` D-FF11
- Schéma : `schemas/facts_first/facts_first_v1_eav.json`
- README schémas : `schemas/facts_first/README.md`
- Charte anti-V2 maintenue : pas de fallback LLM-libre silencieux, multi-langue par construction, pas de listing métier hardcodé.
