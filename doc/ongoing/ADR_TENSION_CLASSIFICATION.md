# ADR — Classification fine des tensions : combler le gap `scope_conflict`

**Date** : 2026-04-26
**Statut** : Proposition (à valider)
**Auteur** : Fred + Claude Code
**Portée** : Architecture cible du `ContradictionClassifier`, alignée sur la cible M2 d'`ARMAND_TEST_READINESS_TARGET`

---

## 1. Le problème

OSMOSIS sait **détecter** des tensions entre claims. Il sait moins bien les **classifier**.

Le pitch préparé pour Armand (« il te met en position de décider si c'est une vraie contradiction ou une différence de scope ») suppose que la classification produite par OSMOSIS est suffisamment fiable pour qu'un juriste senior la reçoive comme un signal utile, pas comme du bruit. Aujourd'hui, sur les corpus actuels, le `ContradictionClassifier` confond fréquemment `value_conflict` et `scope_conflict` — c'est précisément l'erreur qu'un juriste qualifie d'« absurde » et qui érode la confiance en quelques exemples.

### Ce qui marche déjà

L'architecture de classification est solide et bien construite :

- `ContradictionClassifier` (LLM-based, Qwen2.5-72B via DeepInfra) avec prompt evidence-locked et 4 axes (`tension_nature`, `tension_level`, `scope_a`, `scope_b`)
- 6 classes de nature : `value_conflict`, `scope_conflict`, `temporal_conflict`, `methodological`, `complementary`, `unknown`
- 4 niveaux d'intensité : `hard`, `soft`, `none`, `unknown`
- Pipeline 2-passes : règles structurelles pré-LLM puis LLM sur paires non résolues
- `value_contradicts.py` : architecture 5 couches (ClaimKey, ContextGate, ValueFrame, FormalComparator, LLM Arbiter) qui filtre les `COMPATIBLE` et `INCOMPARABLE` avant l'arbitrage LLM
- Logique `is_non_exclusive_predicate` : `X SUPPORTS Y` et `X SUPPORTS Z` ne sont pas contradictoires (alternatives co-existantes)
- Persistance sur la relation Neo4j `CONTRADICTS` avec flags d'affichage dérivés (`show_in_article`, `show_in_chat`, `show_in_homepage`, `requires_review`)

### Ce qui manque

Le diagnostic précis tient en trois constats :

**Constat 1 — Aucune règle structurelle ne couvre `scope_conflict`.** `contradiction_rules.py` contient deux règles seulement :

1. Opposition `≤`/`≥` sur la même `ClaimKey` → `COMPLEMENTARY` / `SOFT`
2. Unités d'une même famille convertible → `METHODOLOGICAL` / `SOFT`

Aucune règle ne capture le cas archétypal du `scope_conflict` : deux claims qui partagent la même `ClaimKey` apparente (subject | PREDICATE) mais portent sur des **portées d'application différentes** — civil vs militaire, EU vs US, version N vs version N+1, sous-catégorie A vs sous-catégorie B. Le LLM est livré seul face à ces cas, sans aide structurelle, et confond facilement « valeurs différentes » avec « scopes différents ».

**Constat 2 — Le `ValueFrame` ne porte aucune information de scope.** `parse_value_frame` extrait `NUMBER`, `VERSION` ou `UNTYPED` à partir du texte de l'objet uniquement. Les qualifiers du `ApplicabilityFrame` (release_id, jurisdiction, edition, sous-catégorie, période d'application) ne sont pas injectés dans l'input du classifier. Le LLM ne voit donc pas la dimension qui devrait précisément lui faire choisir `scope_conflict`.

**Constat 3 — Le prompt LLM ne distingue pas explicitement `value_conflict` vs `scope_conflict`.** Le prompt actuel donne une définition générique de chaque classe mais aucun exemple de désambiguïsation entre les deux cas voisins. Sur des paires où la valeur diffère ET le scope diffère, le LLM choisit presque toujours `value_conflict` (la classe la plus saillante lexicalement).

Le résultat opérationnel : sur les corpus testés, la classe `value_conflict` est sur-représentée et la classe `scope_conflict` sous-représentée. Le ratio inverse devrait probablement être observé dans un corpus juridique multi-juridictionnel comme CS-25 + 2021/821.

---

## 2. Approches écartées et pourquoi

### 2a. Augmenter uniquement la qualité du prompt LLM (proposition naïve)

Réécrire le `CLASSIFIER_SYSTEM` avec plus d'exemples et plus d'instructions de désambiguïsation.

**Écarté seul parce que** :

- Le prompt LLM passe **toutes** les paires `NEED_LLM` à classifier, sans aide structurelle. Améliorer le prompt n'aide pas le LLM à voir des informations qui ne sont pas dans son input (les qualifiers de scope).
- Plus le prompt est long et calibré sur un domaine, moins il est domain-agnostic — alors qu'OSMOSIS revendique l'agnosticisme par construction (`INV-AGNOSTIC`).
- Les améliorations de prompt LLM ont un effet plafond et instable d'une version de modèle à l'autre.

Cette piste reste **partiellement retenue** dans la proposition (cf. §3c) mais comme complément, pas comme solution principale.

### 2b. Remplacer le LLM par un classifier ML supervisé

Entraîner un classifier (random forest, MLP, ou fine-tuned BERT) sur des paires annotées.

**Écarté parce que** :

- Le coût d'annotation pour avoir des données suffisantes (≥ 2 000 paires par domaine pour un classifier solide) est prohibitif sur cette fenêtre de 2-6 semaines.
- Un classifier supervisé est **mono-domaine** par construction. OSMOSIS doit fonctionner sur du SAP, du biomédical, du juridique, de l'aéronautique — un classifier par domaine = dette de maintenance.
- Le LLM evidence-locked reste le bon compromis pour la majorité des paires non résolues par les règles. La performance du LLM dépend surtout de la qualité de son input — c'est ce qu'on adresse.

### 2c. Hardcoder une grille `SCOPE_CONFLICT` par domaine

Ajouter dans le pack `aerospace_compliance` (et tous les autres) une liste de qualifiers spécifiques au domaine qui déclencheraient `SCOPE_CONFLICT`.

**Écarté parce que** :

- Casse l'agnosticisme. Le pack apporte du recall (entités), pas des règles de classification (cf. `INV-PACK`).
- Tout nouveau domaine demanderait une re-grille à hardcoder. Pour OSMOSIS, c'est l'opposé de la promesse produit.

---

## 3. Architecture cible : trois leviers complémentaires

L'idée centrale : aider le `ContradictionClassifier` à voir le scope, par trois leviers indépendants qui se renforcent mutuellement.

### 3a. Levier A — Règles structurelles pour `SCOPE_CONFLICT`

Étendre `contradiction_rules.py` avec une troisième règle, **domain-agnostic** :

> **Règle 3 — Scope mismatch via `ApplicabilityFrame`** : si les deux claims partagent la même `ClaimKey` mais que leurs `ApplicabilityFrame` respectifs ont **au moins un qualifier dont les valeurs diffèrent** (et ne sont pas vides), classer comme `SCOPE_CONFLICT` avec niveau `SOFT` (vraie divergence mais explicable par la portée).

Conditions de déclenchement :

- Les `ClaimKey` sont compatibles (chemin principal `value_contradicts.have_comparable_claim_keys`)
- Au moins un `applicability_axis` du frame de A a une valeur **non vide ET différente** de la valeur du même axis dans le frame de B
- Aucun `ApplicabilityFrame` n'a de valeur vide sur cet axis (sinon on ne peut rien conclure)

Exemple sur le corpus :

- Claim A (CS-25 Amendment 26, contexte = `large aeroplanes`) : « VFTO must not be less than 1.18 VS1g »
- Claim B (CS-25 Amendment 28, contexte = `large aeroplanes`) : « VFTO must not be less than 1.13 VS1g »
- → axis `amendment` diffère (26 vs 28), tous deux non vides → **`SCOPE_CONFLICT` (temporal sub-class) `SOFT`**

Cette règle ne **promet pas** la classification fine entre `temporal_conflict` (sous-cas de scope) et `scope_conflict` pur (différence de catégorie applicative) — elle lève juste le doute principal, en évitant la classification erronée `VALUE_CONFLICT`. La distinction fine reste au LLM avec un prompt restructuré (cf. 3c).

**Pourquoi domain-agnostic** : la règle s'appuie sur la structure du `ApplicabilityFrame` (présence de qualifiers nommés et valués), pas sur leur contenu sémantique. Tout corpus qui produit des `ApplicabilityFrame` bénéficie de la règle, sans liste hardcodée.

### 3b. Levier B — Injection des qualifiers de scope dans le prompt LLM

Modifier `build_llm_input` du `ContradictionClassifier` pour injecter, dans la structure passée au LLM, les `applicability_qualifiers` des deux claims :

```json
{
  "claim_a": {
    "text": "...",
    "doc_title": "...",
    "doc_type": "...",
    "value_frame": {...},
    "applicability_qualifiers": {
      "amendment": "26",
      "jurisdiction": "EU"
    }
  },
  "claim_b": {
    ...
    "applicability_qualifiers": {
      "amendment": "28",
      "jurisdiction": "EU"
    }
  }
}
```

Le prompt LLM doit explicitement nommer ces qualifiers comme **signaux à examiner** pour distinguer `value_conflict` de `scope_conflict`. Sans cette injection, le LLM ne dispose que du `doc_title` et du `doc_type` — informations indirectes et bruyantes pour le scope.

**Effet attendu** : sur les paires `NEED_LLM` (celles que les règles structurelles n'ont pas filtrées), le LLM dispose d'une preuve directe pour préférer `scope_conflict` aux cas où les qualifiers diffèrent.

### 3c. Levier C — Restructuration du prompt avec exemples de désambiguïsation

Le prompt actuel énumère les classes. Le prompt cible doit aussi montrer **comment trancher entre classes voisines** sur des cas où la frontière est subtile :

- Couple (`value_conflict`, `scope_conflict`) — quand les deux semblent applicables
- Couple (`temporal_conflict`, `scope_conflict`) — quand l'évolution temporelle est *un* type de scope
- Couple (`complementary`, `value_conflict`) — quand un avenant précise sans modifier le fond

Format d'exemple à ajouter dans le prompt :

> **Cas — `scope_conflict` plutôt que `value_conflict`** :
> A : « VFTO must not be less than 1.18 VS1g » (amendment 26, civil, EASA)
> B : « VFTO must not be less than 1.13 VS1g » (amendment 28, civil, EASA)
> Verdict : `scope_conflict` (temporal sub-class), `soft`. Les deux claims diffèrent sur la valeur, mais le qualifier `amendment` diffère également — c'est l'évolution réglementaire qui explique la différence, pas une vraie contradiction.

Trois à cinq exemples archétypaux suffisent — il ne s'agit pas d'apprendre au LLM par few-shot mais de le **calibrer sur la frontière**. La taille du prompt augmente d'environ 400 tokens, acceptable.

### 3d. Préservation de l'agnosticisme

Aucun des trois leviers n'introduit de contenu domain-specific :

- Levier A repose sur la structure du `ApplicabilityFrame` (existant, populé via `frame_builder.py`)
- Levier B injecte les qualifiers tels qu'ils sont, sans interpréter leur contenu
- Levier C utilise des exemples archétypaux (le `VFTO` ci-dessus est un exemple de prompt, pas une règle)

Un nouveau domaine OSMOSIS bénéficie automatiquement des trois leviers dès lors que ses claims produisent des `ApplicabilityFrame` peuplés.

---

## 4. Plan d'implémentation

### Phase 1 — Règle structurelle Scope (1-2 jours)

1. Implémenter `_rule_scope_mismatch` dans `contradiction_rules.py` qui consomme les `ApplicabilityFrame` des deux claims via le `claim_persister` ou directement depuis Neo4j
2. Ajouter test unitaire avec couples synthétiques (corpus aerospace : amendment 26 vs 28 ; corpus dual-use : 428/2009 vs 2021/821)
3. Mesurer le taux de paires capturées par cette règle sur le corpus de test

### Phase 2 — Injection qualifiers dans prompt LLM (1 jour)

1. Modifier `ContradictionClassifier.build_llm_input` pour ajouter la clé `applicability_qualifiers`
2. Adapter `CLASSIFIER_USER_TEMPLATE` pour rendre lisibles les qualifiers
3. Mettre à jour le `CLASSIFIER_SYSTEM` pour nommer explicitement les qualifiers comme signal de scope

### Phase 3 — Exemples de désambiguïsation dans le prompt (1 jour)

1. Rédiger 3 à 5 cas archétypaux couvrant les frontières de classes les plus confusantes
2. Insérer dans le `CLASSIFIER_SYSTEM` après les définitions de classes
3. Vérifier que le prompt reste sous la limite de tokens du modèle

### Phase 4 — Benchmark dédié à la classification (2-3 jours)

Cf. ADR n°2 (`ADR_BENCH_PROTOCOL_ARMAND`) — la phase 4 de cet ADR consomme la sortie du protocole de bench pour mesurer l'amélioration apportée par les leviers A+B+C.

Cibles de validation (cf. carte cible §3 M2) :

- Taux de classifications justes ≥ 70% sur 20 paires annotées du corpus de test
- Taux d'erreurs aberrantes < 10%
- En particulier : taux de confusion `value_conflict` ↔ `scope_conflict` divisé par au moins 2 par rapport à la baseline pré-leviers

### Phase 5 — Itération si nécessaire

Si la phase 4 ne livre pas les seuils, deux pistes complémentaires :

- Ajouter une règle structurelle pour la frontière `complementary` ↔ `value_conflict` (mécanisme similaire au levier A mais sur les marqueurs textuels d'avenant/précision)
- Évaluer le gain marginal d'un fine-tuning léger du prompt sur quelques exemples annotés du corpus aerospace

---

## 5. Risques et points de vigilance

### Risque 1 — `ApplicabilityFrame` mal peuplé

La règle 3 (levier A) suppose que les frames sont peuplés. Sur SAP corpus, l'historique mentionne « ApplicabilityAxis = 0 » résolu par fix dans `ContextExtractor` (cf. memory `project_sprint1_progress`). Avant de mesurer l'impact des leviers, **vérifier sur le corpus aerospace que les frames sont peuplés**, sinon le levier A ne se déclenche jamais et seuls B et C jouent.

### Risque 2 — Faux positifs sur la règle 3

Si deux claims partagent une `ClaimKey` mais ont des qualifiers différents qui sont en réalité **la même portée nommée différemment** (ex : `EU` vs `European Union`, ou `Amendment 26` vs `26`), la règle 3 produira un `SCOPE_CONFLICT` à tort. Mitigation : normaliser les valeurs des qualifiers via le pack `aerospace_compliance` (canonical_aliases) avant la comparaison.

### Risque 3 — Erreur aberrante du LLM même avec qualifiers

Le levier B aide mais ne garantit pas. Cas résiduels possibles : qualifiers présents mais mal alignés (ex : `amendment` sur A, mais `release_id` sur B pour le même axe). Mitigation : `frame_adapter.py` doit aligner les axes connus du KG avant la comparaison.

---

## 6. Articulation avec ADRs existants

| ADR existant | Articulation |
|--------------|--------------|
| `ADR_KG_QUALITY_PIPELINE_V3.md` | M2 est l'un des 6 chantiers KG quality déjà identifiés |
| `ADR_UNITE_PREUVE_VS_UNITE_LECTURE.md` | Confirme que la classification opère sur unit-of-proof (claim atomique), pas unit-of-reading |
| `ADR_ENTITY_EXTRACTION_DOMAIN_AGNOSTIC.md` | Le pack `aerospace_compliance` produit le gazetteer qui alimente la canonicalisation des qualifiers (mitigation risque 2) |

---

## 7. Décision

**Adopter les trois leviers A + B + C** dans l'ordre proposé en Phase 1-3 (3-4 jours d'implémentation), puis valider via Phase 4 (bench dédié).

La maturité de l'architecture existante est suffisante — l'ADR ne demande pas de refonte mais des **compléments ciblés** (règle structurelle + enrichissement input + calibrage prompt) qui s'inscrivent dans l'architecture en place.

Si après les trois leviers le seuil de confort de M2 n'est pas atteint, on est en feu orange (cf. `ARMAND_TEST_READINESS_TARGET §6`) et la décision passe à **transparence assumée auprès d'Armand** plutôt que report — l'amélioration partielle reste démontrable et défendable.
