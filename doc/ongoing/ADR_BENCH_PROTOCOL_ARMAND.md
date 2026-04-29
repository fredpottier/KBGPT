# ADR — Protocole de bench préalable au test Armand

**Date** : 2026-04-26
**Statut** : Proposition (à valider)
**Auteur** : Fred + Claude Code
**Portée** : Méthodologie de bench OSMOSIS sur corpus aerospace_compliance, mesure des seuils définis dans `ARMAND_TEST_READINESS_TARGET`

---

## 1. Le problème

La carte cible `ARMAND_TEST_READINESS_TARGET` fixe des seuils chiffrés (plancher report / cible confort) pour 6 capacités Must et 5 capacités Should. Mais elle ne dit pas **comment mesurer** ces seuils ni **avec quel jeu de test**.

Sans protocole formalisé, deux risques structurels :

- **Mesure invalide** : les chiffres produits ne reflètent pas la réalité de ce qu'OSMOSIS sait faire, parce que les questions sont trop faciles, trop difficiles, ou non représentatives du test Armand
- **Mesure non reproductible** : le bench produit un score à un moment T mais on ne peut pas répéter l'opération pour valider l'impact d'un chantier (ADR n°1 par exemple)

Le bench n'est pas une formalité administrative. C'est la **base décisionnelle** pour deux choix critiques :

1. Atteindre ou non le test Armand (feu vert/orange/rouge selon les seuils)
2. Mesurer l'efficacité réelle des chantiers ADR (ADR n°1 améliore-t-il M2 de combien de points exactement ?)

### Ce qui existe déjà

OSMOSIS dispose d'un écosystème de bench mature :

- **Benchmark RAGAS** : 275+20 questions, dual-judge (Qwen+Claude, convergence 0.3%), faithfulness + context_relevance + answer_relevance
- **Benchmark factual/relevant/false_idk/false_answer** sur SAP : 0.360 / 0.490 / 0.375 / 0.220 (v2prompt)
- **Canary test** (`benchmark/canary_test.py`) : 15 questions Type A pour validation rapide
- **Compare runs** (`benchmark/compare_runs.py`) : diff régression entre runs
- **Juge LLM calibré** : factual ≥ 0.8 = correct, vrai false_answer = 17%

### Ce qui manque

Aucun de ces outils ne couvre, avec la granularité requise pour M/S, les capacités spécifiquement testées par Armand :

- **M1 + M2 — détection et classification de tensions** : nécessite un jeu de paires de tensions vraies/fausses annotées par classe attendue. Pas dans RAGAS, pas dans le factual.
- **M4 — abstention calibrée hors-corpus** : nécessite des questions délibérément hors-corpus. RAGAS suppose la réponse dans les chunks, ne mesure donc pas l'abstention.
- **S1 — décomposition différentielle** : nécessite des questions implicitement comparatives ; le RAGAS générique ne distingue pas.
- **S4 — mode validation /verify** : nécessite des assertions à classifier en 4 statuts. Pas dans le bench actuel.

---

## 2. Approches écartées et pourquoi

### 2a. Réutiliser tel quel le benchmark RAGAS existant

**Écarté parce que** :

- RAGAS mesure la qualité d'une réponse retournée, pas la classification de tensions ou la calibration d'abstention
- Le corpus actuel des questions RAGAS est SAP/biomédical, pas aérospatial/juridique
- L'ajout de questions ad hoc dans RAGAS n'est pas la même chose qu'un jeu de test conçu pour valider chaque M/S

RAGAS est **complémentaire** au bench M/S, pas substitut. Il continuera de tourner pour la qualité globale ; le bench M/S adresse une autre question.

### 2b. Bench monolithique unique

Construire un seul jeu de 200+ questions couvrant tous les M/S de manière mélangée.

**Écarté parce que** :

- Une question peut tester plusieurs M en même temps (par exemple M3 traçabilité + M5 baseline) — un mélange empêche d'attribuer un score à un M précis
- L'analyse post-bench devient difficile : si M2 plante, est-ce parce que la classification est mauvaise ou parce que la détection M1 est mauvaise ?

### 2c. Annotation 100% manuelle par Fred

**Écarté parce que** :

- Le coût en temps Fred (annotateur expert) est prohibitif pour 200+ questions sur la fenêtre 2-6 semaines
- L'auto-annotation est sujette au biais de confirmation : l'annotateur connaît la réponse attendue par OSMOSIS

### 2d. Annotation 100% automatique par LLM

**Écarté parce que** :

- Sur les classifications fines (M2 `value_conflict` vs `scope_conflict`), un LLM annoteur peut commettre les mêmes erreurs que le classifier qu'on évalue → biais de méthode
- La qualité des Change Notes EASA et des analyses de cabinets est trop précieuse pour être ignorée comme vérité terrain

---

## 3. Architecture cible : protocole en 5 axes

### 3a. Cinq jeux de test distincts, un par M/S

Le protocole produit cinq jeux de test annotés, chacun ciblant un M ou groupe de M. Cette séparation permet d'attribuer chaque score à une capacité précise.

| Jeu | Cible | Taille | Source d'annotation |
|-----|-------|--------|---------------------|
| **JT-1 Tensions** | M1 + M2 + S2 | 20 vraies tensions + 20 non-tensions | Change Notes EASA (vérité terrain officielle) + analyses cabinets pour 428→821 (Hogan Lovells, Sidley, SIPRI, Hughes Hubbard) |
| **JT-2 Factuelles** | M5 (baseline RAG) | 30 questions factuelles | Annotation Fred sur questions à réponse unique non contestable |
| **JT-3 Hors-corpus** | M4 (abstention) | 15 questions plausibles mais hors-corpus | Annotation Fred par construction (questions choisies pour être hors-corpus) |
| **JT-4 Différentielles** | S1 (décomposition) | 5 questions implicitement comparatives | Annotation Fred + Change Notes EASA |
| **JT-5 Validation** | S4 (/verify 4 statuts) | 20 assertions, 5 par statut attendu | Annotation Fred + corpus comme oracle |

**Total : 110 items annotés**. Volume soutenable, granularité suffisante.

### 3b. Construction des annotations — vérité terrain prioritaire

Pour les jeux où une vérité terrain externe existe, elle est utilisée en première intention :

- **Change Notes EASA** (4 documents disponibles : amdt 23, 24, 26, 28) : chaque note liste explicitement les changements vs la version précédente. Chaque changement = candidat pour `JT-1` ou `JT-4`. La nature de la tension est donnée par EASA elle-même (modification, ajout, suppression, précision).
- **Analyses cabinets pour 428→821** (Hogan Lovells, Sidley Austin, Hughes Hubbard, SIPRI, Portolano Cavallo) : identifient les vraies divergences entre le règlement abrogé et le recast. Chaque divergence = candidat pour `JT-1` avec classe `value_conflict` ou `scope_conflict` selon l'analyse cabinet.
- **Délégués Annex I** (4 documents : 2023/66, 2023/996, 2024/2025, 2024/2547) : chaque délégué modifie l'Annex I de 2021/821. Ces modifications sont des `temporal_conflict` par construction.

L'annotation Fred intervient en seconde intention, là où la vérité terrain externe ne couvre pas (questions factuelles M5, hors-corpus M4, certaines validations S4).

### 3c. Méthodologie de scoring — qui juge quoi

| Type de score | Juge | Raison |
|---------------|------|--------|
| Détection (M1 binaire vraie/fausse tension) | Comparaison automatique avec annotation | Décision binaire, pas d'ambiguïté |
| Classification (M2, S2) | LLM-juge calibré + spot-check Fred sur 20% | Le LLM-juge fournit le volume, Fred valide sur échantillon. Le spot-check est ici essentiel à cause du critère « erreur défendable vs aberrante » qui demande un humain |
| Traçabilité (M3 source valide ?) | Vérification automatique : la source citée existe-t-elle vraiment dans le corpus ? | Décision binaire, automatisable par parsing |
| Abstention (M4) | Annotation par Fred sur 4 catégories : abstention claire / abstention ambiguë / réponse synthétisée / hallucination nette | Catégories qualitatives, jugement humain requis |
| Factual (M5) | Juge LLM calibré (factual ≥ 0.8 = correct) déjà en place | Réutilise outil existant, comparaison vs RAG pur |
| Différentielle (S1) | Présence d'une structure de diff dans la réponse, vérifiée par parsing puis spot-check Fred | La structure peut être détectée automatiquement (sections, comparaisons explicites) |
| /verify (S4) | Comparaison automatique du statut retourné vs attendu | Décision discrète, automatisable |
| UX raisonnement (M6) | Test à la main sur 5 requêtes par Fred + idéalement un tiers non-OSMOSIS | UX = jugement humain, pas de score automatisable |

**Critère défendable vs aberrante (M2)** : sur les erreurs de classification détectées par le juge LLM, Fred annote chaque erreur en deux colonnes : `defendable` (un juriste hésiterait aussi) ou `aberrant` (absurde). La pondération finale applique : aberrante = 5 × défendable (cf. carte cible §2).

### 3d. Reproductibilité

Chaque run de bench produit un artefact JSON traçable contenant :

- Hash du commit OSMOSIS (`git rev-parse HEAD`)
- Versions des prompts (`config/synthesis_prompts.yaml` hash)
- Versions des modèles LLM utilisés (Qwen2.5-72B via DeepInfra, Claude judge, Haiku synthesis...)
- Seed des opérations stochastiques (température, retrieval top-k)
- Date et durée du run
- Pour chaque item : question, annotation attendue, réponse OSMOSIS, score, traces

Le format permet :

- Comparaison run-à-run (`compare_runs.py` adapté pour le format M/S)
- Détection de régression (alerte si un score Must passe sous le plancher)
- Audit a posteriori (« en juin, OSMOSIS répondait quoi à cette question ? »)

### 3e. Stockage et exécution

Le bench M/S réutilise l'infrastructure du benchmark existant :

- Worker RQ existant (cf. memory : RQ worker + cockpit widget + frontend page opérationnels)
- Stockage résultats dans `data/benchmark/results/` (purgé à l'étape 4c, à recréer)
- Cockpit widget pour suivre la progression d'un run

Différence avec RAGAS : le bench M/S est lancé **à la main** par Fred avant des décisions critiques (validation pré-RDV, validation post-chantier). Pas de planification automatique nécessaire à ce stade.

---

## 4. Plan d'implémentation

### Phase 1 — Construction des jeux de test annotés (3-4 jours)

1. **JT-1 Tensions** (le plus volumineux, faire en premier)
   - Lire les Change Notes EASA (amdt 23, 24, 26, 28 ; ~270 pages au total) et extraire 20-30 modifications candidates
   - Lire les analyses cabinets pour 428→821 et extraire 10-15 divergences candidates
   - Filtrer pour avoir 20 vraies tensions diversifiées par classe (`value_conflict`, `scope_conflict`, `temporal_conflict`, `complementary`)
   - Construire 20 non-tensions apparentes : reformulations, renumérotations d'articles, précisions sans modification de fond
   - Stocker chaque item dans un format JSON avec : question_attendue, claims_attendues, classe_attendue_M2, raison

2. **JT-2 Factuelles** (1 jour)
   - 30 questions à réponse unique non contestable (date d'entrée en vigueur, numéro d'article, valeur numérique)
   - Annotation Fred sur la réponse correcte attendue

3. **JT-3 Hors-corpus** (1 jour)
   - 15 questions plausibles aéronautique/dual-use mais sans réponse dans le corpus chargé
   - Vérification manuelle par Fred que la réponse n'est effectivement pas dans le corpus

4. **JT-4 Différentielles** (0.5 jour)
   - 5 questions implicitement comparatives : « Qu'est-ce qui change entre amdt 26 et 28 sur les recorders ? », « Qu'est-ce que 2021/821 introduit que 428/2009 ne couvrait pas ? »

5. **JT-5 Validation** (1 jour)
   - 20 assertions structurées (5 par statut attendu)

### Phase 2 — Implémentation du runner de bench (2 jours)

1. Adapter `benchmark/runner.py` (s'il existe) ou créer `benchmark/armand_runner.py` qui :
   - Charge les 5 JT depuis JSON
   - Lance OSMOSIS sur chaque item via les bonnes routes API (`/search`, `/verify`, etc.)
   - Compare la réponse à l'annotation
   - Produit le rapport JSON traçable

2. Implémenter le scoring par M/S avec les règles de §3c

### Phase 3 — Run baseline (0.5 jour)

1. Lancer le bench sur OSMOSIS post-ingestion corpus aerospace_compliance, AVANT tout chantier ADR n°1
2. Produire le rapport baseline et le **comparer aux seuils de la carte cible**
3. Décision préliminaire : feu vert / orange / rouge à ce stade

### Phase 4 — Run post-chantier (0.5 jour, exécuté après ADR n°1)

1. Après implémentation des leviers A+B+C de l'ADR n°1, relancer le bench
2. `compare_runs.py` produit le delta vs baseline
3. Validation : les seuils de la carte cible sont-ils atteints ?

### Phase 5 — Itérations

Selon résultats Phase 4, soit le test Armand est validé (cf. règle de décision carte cible §6), soit un nouveau cycle d'amélioration / re-bench est nécessaire.

---

## 5. Format de l'artefact de rapport

Format JSON proposé :

```json
{
  "run_id": "armand-bench-2026-05-12-14-30",
  "git_commit": "630bb76...",
  "config_hashes": {
    "synthesis_prompts": "abc123...",
    "llm_models": "def456..."
  },
  "models_used": {
    "ingestion": "Qwen2.5-72B-DeepInfra",
    "synthesis": "claude-haiku-3-5",
    "judge": "claude-sonnet-4-6",
    "classifier": "Qwen2.5-72B-DeepInfra"
  },
  "corpus_signature": "aerospace_compliance/v1 (17 PDFs, 10471 pages)",
  "scores": {
    "M1": {"recall": 0.85, "precision": 0.78, "verdict": "comfort"},
    "M2": {"accuracy": 0.72, "aberrant_pct": 0.08, "verdict": "comfort", "weighted_score": 0.68},
    "M3": {"valid_source_pct": 1.0, "verdict": "comfort"},
    "M4": {"clear_abstention_pct": 0.93, "hallucination_count": 0, "verdict": "comfort"},
    "M5": {"factual_delta_vs_rag_pp": -3, "false_idk_pct": 0.08, "verdict": "comfort"},
    "M6": {"clear_ux_count": 4, "verdict": "near_comfort"},
    "S1": {"diff_structure_count": 4, "verdict": "comfort"},
    "S2": {"covered_by_M2": true},
    "S3": {"automatic_reconstruction_pct": 0.4, "verdict": "below_target"},
    "S4": {"correct_status_count": 17, "verdict": "near_comfort"},
    "S5": {"crossref_detection_count": 2, "verdict": "below_target"}
  },
  "decision": "GREEN",
  "items": [...]
}
```

Le champ `decision` applique automatiquement les règles de la carte cible §6.

---

## 6. Risques et points de vigilance

### Risque 1 — JT-1 trop facile ou trop difficile

Le risque le plus important. Si les 20 vraies tensions sont toutes triviales (deux versions consécutives avec un seul mot différent), M1+M2 paraîtront brillants alors qu'ils ne sont pas testés. Si elles sont trop subtiles (jurisprudence implicite), M1+M2 paraîtront ratés alors que c'est l'annotation qui est trop dure.

**Mitigation** : équilibrer le JT-1 sur trois niveaux de difficulté (facile / moyen / difficile), avec ~7 items par niveau, et reporter le score par niveau dans le rapport.

### Risque 2 — Auto-validation par OSMOSIS

Si on utilise OSMOSIS pour aider à annoter (« montre-moi les différences entre amdt 26 et 28 »), on biaise l'évaluation. Solution : **n'utiliser que les sources externes** (Change Notes EASA, analyses cabinets) et l'annotation manuelle Fred pour construire le JT.

### Risque 3 — Stagnation lors d'itérations multiples

Si Phase 5 s'enchaîne sur plusieurs itérations sans progrès net, il faut savoir s'arrêter. Critère d'arrêt proposé : **trois itérations sans amélioration de plus de 2 points sur le M concerné** → on accepte le score actuel et on recalibre la décision feu vert/orange/rouge en transparence.

---

## 7. Articulation avec d'autres ADRs

| ADR | Articulation |
|-----|--------------|
| `ADR_TENSION_CLASSIFICATION` (n°1) | Le JT-1 mesure l'efficacité des leviers A+B+C de l'ADR n°1 |
| `ADR_RAISONNEMENT_UI` (n°3, conditionnel) | Si rédigé, le JT-6 UX (ad hoc) le mesurera |
| `ARMAND_TEST_READINESS_TARGET` | Le bench produit les chiffres qui appliquent la règle de décision §6 |

---

## 8. Décision

**Adopter le protocole en 5 jeux de test distincts**, avec annotation prioritaire sur vérité terrain externe (Change Notes EASA + analyses cabinets pour 428→821) et annotation Fred en complément.

Le protocole nécessite **~5-6 jours de travail au total** (3-4 j construction JT, 2 j runner, 1 j runs et analyses). C'est l'investissement structurant qui rend tout le reste mesurable et défendable.

Le bench n'est **pas** un livrable Armand — il est interne. Mais ses résultats déterminent si le test Armand a lieu et avec quelle posture (vert / transparence orange / report).
